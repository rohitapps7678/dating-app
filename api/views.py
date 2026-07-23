from rest_framework import status, generics, permissions, serializers
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.pagination import PageNumberPagination
from rest_framework_simplejwt.tokens import RefreshToken
from django.db.models import Q, OuterRef, Subquery
from django.utils import timezone
from django.conf import settings
from datetime import timedelta
import cloudinary, cloudinary.uploader

from .models import (
    User, Profile,
    Like, Match, Conversation,
    Message, Block, Report, INTEREST_CHOICES, POSITION_CHOICES,
    Subscription, PLAN_CONFIG, PLAN_FEATURES, FREE_TRIAL_DAYS,
)
from .serializers import (
    UserSerializer,
    RegisterSerializer, LoginSerializer,
    FirebaseAuthSerializer,
    ProfileSerializer, NearbyProfileSerializer,
    LikeSerializer, MatchSerializer,
    ConversationSerializer, MessageSerializer,
    BlockSerializer, ReportSerializer,
    SubscriptionSerializer, CreateSubscriptionOrderSerializer,
    VerifySubscriptionPaymentSerializer,
    get_user_from_id,
)
from .utils import get_nearby_users, get_interest_suggestions
from .razorpay_client import create_order, verify_webhook_signature


# ─────────────────────────────────────────
# HELPER
# ─────────────────────────────────────────

def get_tokens(user):
    refresh = RefreshToken.for_user(user)
    return {"refresh": str(refresh), "access": str(refresh.access_token)}

class FastPagination(PageNumberPagination):
    """Chhote pages = fast response. Query string: ?page=2&page_size=10"""
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 50


# ─────────────────────────────────────────
# HEALTH
# ─────────────────────────────────────────

class HealthView(APIView):
    """
    Lightweight Health Check - Neon CU bachane ke liye
    Database check completely removed.
    Sirf yeh check karega ki Django app chal raha hai.
    """

    permission_classes = [permissions.AllowAny]

    def get(self, request):
        return Response({
            "status": "ok",
            "timestamp": timezone.now().isoformat(),
            "checks": {
                "database": "skipped",   # ← Ab check nahi hoga
                "api": "ok"
            },
            "message": "API is running (Database check disabled to save Neon CU)",
            "version": "1.0.0",
        }, status=200)


# ─────────────────────────────────────────
# INTERESTS
# ─────────────────────────────────────────

class InterestsListView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        return Response({"interests": INTEREST_CHOICES})


class InterestSuggestionsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        try:
            my_profile = request.user.profile
        except Profile.DoesNotExist:
            return Response({"results": []})
        if not my_profile.interests:
            return Response({"results": [], "message": "Add interests to get suggestions"})
        profiles = get_interest_suggestions(my_profile, limit=20)
        return Response({"results": NearbyProfileSerializer(
            profiles, many=True, context={"request": request}).data})


# ─────────────────────────────────────────
# AUTH — Phone OTP via Firebase
# ─────────────────────────────────────────
# Flutter app khud Firebase se OTP bhejta/verify karta hai (FirebaseAuth
# .verifyPhoneNumber + signInWithCredential). Uske baad Flutter yahan
# sirf Firebase ka ID token bhejta hai — hum usse verify karke apna JWT
# issue karte hain. Isliye ek hi endpoint kaafi hai (koi "send otp" /
# "verify otp" split backend mein nahi hai, wo kaam Firebase SDK khud
# app ke andar karta hai).

class FirebaseAuthView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        s = FirebaseAuthSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        user, is_new = s.get_or_create_user(s.validated_data)

        if not user.is_active:
            return Response({"error": "Account disabled hai"}, status=403)

        profile_complete = hasattr(user, "profile") and user.profile.is_complete

        return Response({
            "tokens": get_tokens(user),
            "user": UserSerializer(user).data,
            "profile_complete": profile_complete,
            "is_new_user": is_new,
        })


# ─────────────────────────────────────────
# AUTH — Username + Password
# ─────────────────────────────────────────

class RegisterView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        s = RegisterSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        user = s.save()

        return Response({
            "tokens": get_tokens(user),
            "user": UserSerializer(user).data,
            "profile_complete": hasattr(user, "profile") and user.profile.is_complete,
            "is_new_user": True,
        }, status=201)


class LoginView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        s = LoginSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        user = s.validated_data["user"]

        return Response({
            "tokens": get_tokens(user),
            "user": UserSerializer(user).data,
            "profile_complete": hasattr(user, "profile") and user.profile.is_complete,
            "is_new_user": False,
        })


class LogoutView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        try:
            RefreshToken(request.data["refresh"]).blacklist()
            return Response({"message": "Logged out"})
        except Exception:
            return Response({"error": "Invalid token"}, status=400)


# ─────────────────────────────────────────
# PHOTO UPLOAD
# ─────────────────────────────────────────

class PhotoUploadView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes     = [MultiPartParser, FormParser, JSONParser]

    def post(self, request):
        profile, _ = Profile.objects.get_or_create(user=request.user)
        photo_url  = request.data.get("photo_url")
        if photo_url:
            profile.photo_url = photo_url
            profile.save(update_fields=["photo_url"])
            return Response({"photo_url": photo_url})
        photo_file = request.FILES.get("photo")
        if not photo_file:
            return Response({"error": "photo or photo_url required"}, status=400)
        try:
            result = cloudinary.uploader.upload(
                photo_file,
                folder=f"dating_app/profiles/{request.user.id}",
                transformation=[
                    {"width": 800, "height": 800, "crop": "fill", "gravity": "face"},
                    {"quality": "auto", "fetch_format": "auto"},
                ],
            )
            url = result.get("secure_url")
            profile.photo_url = url
            profile.save(update_fields=["photo_url"])
            return Response({"photo_url": url})
        except Exception as e:
            return Response({"error": str(e)}, status=500)


# ─────────────────────────────────────────
# PROFILE
# ─────────────────────────────────────────

class ProfileView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes     = [JSONParser, MultiPartParser, FormParser]

    def get(self, request):
        profile, _ = Profile.objects.get_or_create(user=request.user)
        return Response(ProfileSerializer(profile, context={"request": request}).data)

    def post(self, request):
        if hasattr(request.user, "profile"):
            return Response({"error": "Use PUT to update"}, status=400)
        s = ProfileSerializer(data=request.data, context={"request": request})
        s.is_valid(raise_exception=True)
        s.save(user=request.user)
        return Response(s.data, status=201)

    def put(self, request):
        profile, _ = Profile.objects.get_or_create(user=request.user)
        s = ProfileSerializer(
            profile, data=request.data, partial=True,
            context={"request": request})
        s.is_valid(raise_exception=True)
        s.save()
        return Response(s.data)

    def patch(self, request):
        return self.put(request)


class OtherProfileView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, user_id):
        # ✅ FIX: get_user_from_id dono handle karta hai —
        # Profile.id (int, jo Nearby/Match serializers bhejte hain)
        # aur User.id (UUID) dono. Pehle sirf user__id=user_id se
        # direct lookup hoti thi, jo Profile.id ke liye fail ho jaati
        # thi aur "Profile not found" 404 aata tha.
        try:
            user = get_user_from_id(user_id)
        except serializers.ValidationError:
            return Response({"error": "Profile not found"}, status=404)

        try:
            profile = user.profile
        except Profile.DoesNotExist:
            return Response({"error": "Profile not found"}, status=404)

        return Response(ProfileSerializer(profile, context={"request": request}).data)


class LiveToggleView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        profile, _ = Profile.objects.get_or_create(user=request.user)
        go_live = request.data.get("is_live", True)
        if go_live:
            profile.go_live()
            return Response({"is_live": True, "live_since": profile.live_since,
                             "message": "You are now live!"})
        else:
            profile.go_offline()
            return Response({"is_live": False, "message": "You are now offline."})


# ─────────────────────────────────────────
# SEARCH
# ─────────────────────────────────────────

class SearchView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        query   = request.query_params.get("q", "").strip()
        gender  = request.query_params.get("gender", "").strip()
        min_age = request.query_params.get("min_age")
        max_age = request.query_params.get("max_age")
        if not query:
            return Response({"error": "q is required"}, status=400)

        blocked_ids = list(Block.objects.filter(
            blocker=request.user).values_list("blocked_id", flat=True))

        qs = Profile.objects.select_related("user").filter(
            user__is_active=True, is_complete=True,
        ).exclude(user=request.user).exclude(
            user__id__in=blocked_ids
        ).filter(Q(name__icontains=query) | Q(user__phone__icontains=query))

        if gender in ("M", "F", "O"):
            qs = qs.filter(gender=gender)
        if min_age:
            try: qs = qs.filter(age__gte=int(min_age))
            except ValueError: pass
        if max_age:
            try: qs = qs.filter(age__lte=int(max_age))
            except ValueError: pass

        return Response(ProfileSerializer(
            qs.order_by("name")[:30], many=True,
            context={"request": request}).data)


# ─────────────────────────────────────────
# NEARBY
# ─────────────────────────────────────────

class NearbyUsersView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        try:
            lat    = float(request.query_params.get("lat", 0))
            lng    = float(request.query_params.get("lng", 0))
            radius = float(request.query_params.get("radius", 10))
            radius = max(0.5, min(20.0, radius))
        except ValueError:
            return Response({"error": "Invalid coordinates"}, status=400)

        profile, _ = Profile.objects.get_or_create(user=request.user)
        profile.latitude  = lat
        profile.longitude = lng
        profile.save(update_fields=["latitude", "longitude"])

        blocked_ids = list(Block.objects.filter(
            blocker=request.user).values_list("blocked_id", flat=True))

        min_age      = request.query_params.get("min_age")
        max_age      = request.query_params.get("max_age")
        online_only  = request.query_params.get("online_only", "false").lower() == "true"
        position     = request.query_params.get("position")
        has_room_str = request.query_params.get("has_room")

        has_room = None
        if has_room_str == "true":  has_room = True
        if has_room_str == "false": has_room = False

        profiles = get_nearby_users(
            lat, lng, radius,
            exclude_user_id  = request.user.id,
            blocked_ids      = blocked_ids,
            only_live        = True,
            my_interests     = profile.interests or [],
            min_age          = int(min_age) if min_age else None,
            max_age          = int(max_age) if max_age else None,
            show_online_only = online_only,
            position         = position if position else None,
            has_room         = has_room,
        )
        return Response(NearbyProfileSerializer(
            profiles, many=True, context={"request": request}).data)


# ─────────────────────────────────────────
# LIKE / MATCH
# ─────────────────────────────────────────

class LikeView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        s = LikeSerializer(data=request.data, context={"request": request})
        s.is_valid(raise_exception=True)
        like = s.save()
        response_data = s.data
        if response_data.get("is_matched"):
            match = Match.objects.filter(
                user1__in=[request.user, like.receiver],
                user2__in=[request.user, like.receiver]
            ).first()
            if match and hasattr(match, "conversation"):
                response_data["conversation_id"] = match.conversation.id
        return Response(response_data, status=201)


# ─────────────────────────────────────────
# START CONVERSATION — bina match/like ke kisi ko bhi message karo
# ─────────────────────────────────────────

class StartConversationView(APIView):
    """
    POST { "user_id": "<id>" } → get-or-create a conversation with that
    user, even if there's no mutual like/match. Reuses the existing
    Match/Conversation tables (Match ab sirf "do users ke beech connection"
    ka record hai, mutual-like hona zaroori nahi raha).
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        other_id = request.data.get("user_id") or request.data.get("receiver_id")
        if not other_id:
            return Response({"error": "user_id required"}, status=400)

        other = get_user_from_id(other_id)

        if other == request.user:
            return Response({"error": "Apne aap ko message nahi kar sakte"}, status=400)
        if not other.is_active:
            return Response({"error": "User not found"}, status=404)

        # Block check (dono taraf)
        if Block.objects.filter(
            Q(blocker=request.user, blocked=other) |
            Q(blocker=other, blocked=request.user)
        ).exists():
            return Response({"error": "Cannot message this user"}, status=403)

        u1, u2 = sorted([request.user, other], key=lambda u: str(u.id))
        match, _      = Match.objects.get_or_create(user1=u1, user2=u2)
        conversation, _ = Conversation.objects.get_or_create(match=match)

        return Response({"conversation_id": conversation.id}, status=200)


class MatchListView(generics.ListAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class   = MatchSerializer
    pagination_class    = FastPagination

    def get_queryset(self):
        user = self.request.user
        # ✅ Single query with OR instead of two queries combined in Python
        # ✅ select_related pulls user1/user2 + their profiles + conversation
        #    in the SAME query — no extra query per row (fixes N+1)
        return (
            Match.objects
            .filter(Q(user1=user) | Q(user2=user))
            .select_related(
                "user1__profile", "user2__profile", "conversation",
            )
            .order_by("-created_at")
        )

    def get_serializer_context(self):
        return {"request": self.request}


# ─────────────────────────────────────────
# CHAT
# ─────────────────────────────────────────

class ConversationListView(generics.ListAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class   = ConversationSerializer
    pagination_class    = FastPagination

    def get_queryset(self):
        user = self.request.user

        # ✅ Last message ab ek Subquery se aata hai (annotate) —
        #    pehle har conversation ke liye ALAG query lagti thi (N+1),
        #    ab sab ek hi query mein aa jaata hai.
        last_msg = Message.objects.filter(
            conversation=OuterRef("pk")
        ).order_by("-created_at")

        return (
            Conversation.objects
            .filter(Q(match__user1=user) | Q(match__user2=user))
            .select_related(
                "match__user1__profile", "match__user2__profile",
            )
            .annotate(
                last_message_text       = Subquery(last_msg.values("text")[:1]),
                last_message_created_at = Subquery(last_msg.values("created_at")[:1]),
                last_message_sender_id  = Subquery(last_msg.values("sender_id")[:1]),
                last_message_is_read    = Subquery(last_msg.values("is_read")[:1]),
                last_message_id         = Subquery(last_msg.values("id")[:1]),
            )
            .order_by("-created_at")
        )

    def get_serializer_context(self):
        return {"request": self.request}


class MessageListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def _get_conv(self, request, conv_id):
        try:
            conv = Conversation.objects.get(id=conv_id)
        except Conversation.DoesNotExist:
            return None, Response({"error": "Not found"}, status=404)
        if request.user not in [conv.match.user1, conv.match.user2]:
            return None, Response({"error": "Not allowed"}, status=403)
        return conv, None

    def get(self, request, conv_id):
        conv, err = self._get_conv(request, conv_id)
        if err: return err
        # ✅ select_related sender so serializer doesn't hit DB per message
        msgs = list(conv.messages.select_related("sender").order_by("created_at"))
        # Mark unread as read in one UPDATE query using already-known ids
        # (pehle wala queryset do baar evaluate hota tha — DB pe 2x load)
        unread_ids = [m.id for m in msgs if not m.is_read and m.sender_id != request.user.id]
        if unread_ids:
            Message.objects.filter(id__in=unread_ids).update(is_read=True)
        return Response(MessageSerializer(msgs, many=True).data)

    def post(self, request, conv_id):
        conv, err = self._get_conv(request, conv_id)
        if err: return err
        s = MessageSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        s.save(conversation=conv, sender=request.user)
        return Response(s.data, status=201)


# ─────────────────────────────────────────
# BLOCK / REPORT
# ─────────────────────────────────────────

class BlockView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        blocks = Block.objects.filter(
            blocker=request.user).select_related("blocked__profile")
        data = []
        for b in blocks:
            try:
                data.append({"user_id": str(b.blocked.id),
                             "name": b.blocked.profile.name,
                             "blocked_at": b.created_at})
            except Profile.DoesNotExist:
                data.append({"user_id": str(b.blocked.id),
                             "name": b.blocked.phone,
                             "blocked_at": b.created_at})
        return Response(data)

    def post(self, request):
        s = BlockSerializer(data=request.data, context={"request": request})
        s.is_valid(raise_exception=True)
        s.save()
        return Response({"message": "User blocked"}, status=201)

    def delete(self, request, user_id):
        deleted, _ = Block.objects.filter(
            blocker=request.user, blocked_id=user_id).delete()
        if deleted:
            return Response({"message": "User unblocked"})
        return Response({"error": "Block not found"}, status=404)


class ReportView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        s = ReportSerializer(data=request.data, context={"request": request})
        s.is_valid(raise_exception=True)
        s.save()
        return Response({"message": "Report submitted"}, status=201)


# ─────────────────────────────────────────
# SUBSCRIPTION  (Razorpay)
# ─────────────────────────────────────────

class SubscriptionPlansView(APIView):
    """Public — Flutter paywall screen loads this before login-gating anything."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        plans = [
            {
                "id":            key,
                "label":         cfg["label"],
                "price_inr":     cfg["price_inr"],
                "duration_days": cfg["duration_days"],
                "tag":           cfg["tag"],
                "features":      PLAN_FEATURES,
            }
            for key, cfg in PLAN_CONFIG.items()
        ]
        return Response({
            "plans":            plans,
            "razorpay_key_id":  settings.RAZORPAY_KEY_ID,
            "free_trial_days":  FREE_TRIAL_DAYS,
        })


class SubscriptionStatusView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        sub = request.user.active_subscription
        has_used_trial = Subscription.objects.filter(
            user=request.user, is_trial=True).exists()
        return Response({
            "is_premium":     sub is not None,
            "subscription":   SubscriptionSerializer(sub).data if sub else None,
            "has_used_trial": has_used_trial,
        })


class ClaimFreeTrialView(APIView):
    """
    ₹0, no Razorpay order — activates FREE_TRIAL_DAYS of premium once per
    user. This is what backs the '1-DAY FREE TRIAL' banner on the paywall.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        if Subscription.objects.filter(user=request.user, is_trial=True).exists():
            return Response({"error": "Free trial already used"}, status=400)
        if request.user.is_premium:
            return Response({"error": "Aap already Premium ho"}, status=400)

        now = timezone.now()
        sub = Subscription.objects.create(
            user=request.user,
            plan="week",
            amount=0,
            razorpay_order_id=f"trial_{request.user.id}_{int(now.timestamp())}",
            status="paid",
            is_trial=True,
            starts_at=now,
            expires_at=now + timedelta(days=FREE_TRIAL_DAYS),
        )
        return Response({
            "message":      f"{FREE_TRIAL_DAYS}-day free trial activated!",
            "subscription": SubscriptionSerializer(sub).data,
        }, status=201)


class CreateSubscriptionOrderView(APIView):
    """
    Step 1 of checkout — creates a Razorpay order + a local 'created'
    Subscription row, and returns everything the Flutter Razorpay SDK
    needs to open the checkout sheet.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        s = CreateSubscriptionOrderSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        plan = s.validated_data["plan"]
        cfg  = PLAN_CONFIG[plan]
        amount_paise = cfg["price_inr"] * 100

        try:
            order = create_order(
                amount_paise,
                receipt=f"sub_{request.user.id}_{int(timezone.now().timestamp())}",
                notes={"user_id": str(request.user.id), "plan": plan},
            )
        except Exception as e:
            return Response({"error": f"Razorpay order banane mein problem: {e}"}, status=502)

        subscription = Subscription.objects.create(
            user=request.user,
            plan=plan,
            amount=amount_paise,
            razorpay_order_id=order["id"],
        )

        email = request.user.phone if "@" in request.user.phone else ""
        return Response({
            "order_id":         order["id"],
            "amount":           amount_paise,
            "currency":         "INR",
            "key_id":           settings.RAZORPAY_KEY_ID,
            "plan":             plan,
            "subscription_id":  subscription.id,
            "user_email":       email,
        }, status=201)


class VerifySubscriptionPaymentView(APIView):
    """
    Step 2 of checkout — client calls this right after Razorpay's
    checkout sheet reports success. Signature is verified server-side
    before the subscription is ever marked 'paid'.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        s = VerifySubscriptionPaymentSerializer(
            data=request.data, context={"request": request})
        s.is_valid(raise_exception=True)
        subscription = s.validated_data["subscription"]

        if subscription.status != "paid":
            subscription.mark_paid(
                s.validated_data["razorpay_payment_id"],
                s.validated_data["razorpay_signature"],
            )

        return Response({
            "message":      "Payment verified. Subscription activated!",
            "subscription": SubscriptionSerializer(subscription).data,
        })


class RazorpayWebhookView(APIView):
    """
    Optional but strongly recommended for production: Razorpay calls this
    directly from its servers, so a payment still gets recorded even if
    the app crashes/loses network right after checkout (before it could
    call /verify/). Configure this URL in Razorpay Dashboard → Settings →
    Webhooks, subscribe to the 'payment.captured' event, and set the same
    secret as RAZORPAY_WEBHOOK_SECRET in your env.
    """
    permission_classes     = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        signature = request.headers.get("X-Razorpay-Signature", "")
        payload   = request.body.decode("utf-8")

        if not verify_webhook_signature(payload, signature):
            return Response({"error": "Invalid signature"}, status=400)

        event = request.data.get("event")
        if event == "payment.captured":
            payment    = request.data["payload"]["payment"]["entity"]
            order_id   = payment["order_id"]
            payment_id = payment["id"]

            sub = Subscription.objects.filter(razorpay_order_id=order_id).first()
            if sub and sub.status != "paid":
                sub.mark_paid(payment_id, signature="webhook-verified")

        return Response({"status": "ok"})