from rest_framework import serializers
from django.contrib.auth import authenticate

from .models import (
    User, Profile, Like, Match, Conversation,
    Message, Block, Report, INTEREST_CHOICES, POSITION_CHOICES,
    Subscription, PLAN_CONFIG,
)


def get_user_from_id(value):
    try:
        return Profile.objects.get(id=int(value)).user
    except (ValueError, Profile.DoesNotExist):
        pass
    try:
        return User.objects.get(id=value)
    except (User.DoesNotExist, Exception):
        raise serializers.ValidationError("User not found")


# ─────────────────────────────────────────
# AUTH — Username + Password
# ─────────────────────────────────────────
# Note: User.phone is the model's unique USERNAME_FIELD. For username/password
# accounts we simply store the chosen username in that same column (it already
# doubles up as the email for Email-OTP accounts) — so a username must not
# collide with an existing email/username in the system.

class RegisterSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=30)
    password = serializers.CharField(min_length=6, write_only=True)

    def validate_username(self, value):
        value = value.strip().lower()
        if len(value) < 3:
            raise serializers.ValidationError("Username kam se kam 3 characters ka hona chahiye")
        if not value.replace("_", "").replace(".", "").isalnum():
            raise serializers.ValidationError(
                "Username sirf letters, numbers, '_' aur '.' contain kar sakta hai")
        if User.objects.filter(phone=value).exists():
            raise serializers.ValidationError("Ye username already liya ja chuka hai")
        return value

    def create(self, validated_data):
        return User.objects.create_user(
            phone=validated_data["username"],
            password=validated_data["password"],
        )


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=30)
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        username = data["username"].strip().lower()
        user = authenticate(username=username, password=data["password"])
        if not user:
            raise serializers.ValidationError("Galat username ya password")
        if not user.is_active:
            raise serializers.ValidationError("Account is disabled")
        data["user"] = user
        return data


# ─────────────────────────────────────────
# AUTH — Firebase (OTP + Google) ✅
# ─────────────────────────────────────────

class FirebaseAuthSerializer(serializers.Serializer):
    """
    Flutter → Firebase → ID Token → Yahan bhejo
    provider: 'phone' ya 'google'
    """
    firebase_token = serializers.CharField(write_only=True)
    provider       = serializers.ChoiceField(
        choices=['phone', 'google'], write_only=True)

    def validate(self, data):
        from .firebase_auth import verify_firebase_token

        decoded = verify_firebase_token(data["firebase_token"])
        if not decoded:
            raise serializers.ValidationError("Invalid or expired Firebase token")

        provider = data["provider"]
        sign_in_provider = decoded.get("firebase", {}).get("sign_in_provider", "")

        # Provider match check
        if provider == "phone" and sign_in_provider != "phone":
            raise serializers.ValidationError("Token is not from phone auth")
        if provider == "google" and sign_in_provider != "google.com":
            raise serializers.ValidationError("Token is not from Google auth")

        data["decoded"] = decoded
        return data

    def get_or_create_user(self, validated_data):
        decoded  = validated_data["decoded"]
        provider = validated_data["provider"]

        if provider == "phone":
            phone = decoded.get("phone_number", "").strip()
            if not phone:
                raise serializers.ValidationError("Phone number not found in token")

            user, created = User.objects.get_or_create(
                phone=phone,
                defaults={"is_active": True}
            )
            if created:
                user.set_unusable_password()
                user.save()
            return user, created

        else:  # google
            email = decoded.get("email", "").strip()
            name  = decoded.get("name", "")
            photo = decoded.get("picture", "")

            if not email:
                raise serializers.ValidationError("Email not found in Google token")

            # Google user ke liye phone = email (unique identifier)
            # Ya alag field — yahan email ko phone field mein store karte hain
            user, created = User.objects.get_or_create(
                phone=email,
                defaults={"is_active": True}
            )
            if created:
                user.set_unusable_password()
                user.save()

                # Profile bhi bana do Google info se
                if name:
                    profile, _ = Profile.objects.get_or_create(user=user)
                    if not profile.name:
                        profile.name = name
                    if not profile.photo_url and photo:
                        profile.photo_url = photo
                    profile.save()

            return user, created


# ─────────────────────────────────────────
# USER
# ─────────────────────────────────────────

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model        = User
        fields       = ["id", "phone", "created_at"]
        read_only_fields = fields


# ─────────────────────────────────────────
# PROFILE
# ─────────────────────────────────────────

class ProfileSerializer(serializers.ModelSerializer):
    phone          = serializers.CharField(source="user.phone", read_only=True)
    position_label = serializers.SerializerMethodField()

    class Meta:
        model  = Profile
        fields = [
            "id", "phone", "name", "bio", "age", "gender",
            "photo_url", "interests",
            "position", "position_label",
            "has_room",
            "latitude", "longitude",
            "is_complete", "is_live", "live_since", "updated_at",
        ]
        read_only_fields = [
            "id", "phone", "is_complete",
            "live_since", "updated_at", "position_label"
        ]

    def get_position_label(self, obj):
        if not obj.position:
            return None
        return dict(POSITION_CHOICES).get(obj.position, obj.position)

    def validate_age(self, value):
        if value and value < 18:
            raise serializers.ValidationError("Age must be 18 or above")
        return value

    def validate_interests(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("Interests must be a list")
        if len(value) > 10:
            raise serializers.ValidationError("Maximum 10 interests allowed")
        invalid = [i for i in value if i not in INTEREST_CHOICES]
        if invalid:
            raise serializers.ValidationError(f"Invalid interests: {invalid}")
        return value

    def update(self, instance, validated_data):
        instance = super().update(instance, validated_data)
        if instance.name and instance.age and instance.gender and instance.photo_url:
            instance.is_complete = True
            instance.save(update_fields=["is_complete"])
        return instance


class NearbyProfileSerializer(serializers.ModelSerializer):
    distance         = serializers.FloatField(read_only=True)
    common_interests = serializers.SerializerMethodField()
    interest_score   = serializers.SerializerMethodField()
    position_label   = serializers.SerializerMethodField()

    class Meta:
        model  = Profile
        fields = [
            "id", "name", "age", "gender", "photo_url",
            "interests", "position", "position_label",
            "has_room", "distance", "is_live",
            "common_interests", "interest_score",
        ]

    def get_common_interests(self, obj):
        request = self.context.get("request")
        if not request: return []
        try:
            return obj.common_interests(request.user.profile)
        except Exception:
            return []

    def get_interest_score(self, obj):
        request = self.context.get("request")
        if not request: return 0
        try:
            return obj.interest_score(request.user.profile)
        except Exception:
            return 0

    def get_position_label(self, obj):
        if not obj.position: return None
        return dict(POSITION_CHOICES).get(obj.position, obj.position)


# ─────────────────────────────────────────
# LIKE / MATCH
# ─────────────────────────────────────────

class LikeSerializer(serializers.ModelSerializer):
    receiver_id = serializers.CharField(write_only=True)
    is_matched  = serializers.SerializerMethodField()

    class Meta:
        model        = Like
        fields       = ["id", "receiver_id", "is_matched", "created_at"]
        read_only_fields = ["id", "is_matched", "created_at"]

    def get_is_matched(self, obj):
        return Like.objects.filter(
            sender=obj.receiver, receiver=obj.sender).exists()

    def validate_receiver_id(self, value):
        request  = self.context["request"]
        receiver = get_user_from_id(value)
        if receiver == request.user:
            raise serializers.ValidationError("Apne aap ko like nahi kar sakte")
        if not receiver.is_active:
            raise serializers.ValidationError("User not found")
        if Like.objects.filter(sender=request.user, receiver=receiver).exists():
            raise serializers.ValidationError("Already liked")
        if Block.objects.filter(blocker=request.user, blocked=receiver).exists():
            raise serializers.ValidationError("You have blocked this user")
        return str(receiver.id)

    def create(self, validated_data):
        sender   = self.context["request"].user
        receiver = User.objects.get(id=validated_data["receiver_id"])
        like     = Like.objects.create(sender=sender, receiver=receiver)
        if Like.objects.filter(sender=receiver, receiver=sender).exists():
            u1, u2 = sorted([sender, receiver], key=lambda u: str(u.id))
            match, created = Match.objects.get_or_create(user1=u1, user2=u2)
            if created:
                Conversation.objects.create(match=match)
        return like


class MatchSerializer(serializers.ModelSerializer):
    other_user       = serializers.SerializerMethodField()
    conversation_id  = serializers.IntegerField(source="conversation.id", read_only=True)
    common_interests = serializers.SerializerMethodField()

    class Meta:
        model  = Match
        fields = ["id", "other_user", "conversation_id", "common_interests", "created_at"]

    def get_other_user(self, obj):
        request = self.context["request"]
        other   = obj.user2 if obj.user1 == request.user else obj.user1
        try:
            return ProfileSerializer(other.profile, context=self.context).data
        except Profile.DoesNotExist:
            return {"id": str(other.id), "phone": other.phone}

    def get_common_interests(self, obj):
        request = self.context["request"]
        try:
            my    = request.user.profile
            other = (obj.user2 if obj.user1 == request.user else obj.user1).profile
            return my.common_interests(other)
        except Exception:
            return []


# ─────────────────────────────────────────
# CHAT
# ─────────────────────────────────────────

class MessageSerializer(serializers.ModelSerializer):
    sender_id = serializers.UUIDField(source="sender.id", read_only=True)

    class Meta:
        model        = Message
        fields       = ["id", "sender_id", "text", "is_read", "created_at"]
        read_only_fields = ["id", "sender_id", "is_read", "created_at"]

    def validate_text(self, value):
        if not value.strip():
            raise serializers.ValidationError("Message cannot be empty")
        return value


class ConversationSerializer(serializers.ModelSerializer):
    other_user   = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()

    class Meta:
        model  = Conversation
        fields = ["id", "other_user", "last_message", "created_at"]

    def get_other_user(self, obj):
        request = self.context["request"]
        match   = obj.match
        other   = match.user2 if match.user1 == request.user else match.user1
        try:
            return NearbyProfileSerializer(other.profile, context=self.context).data
        except Profile.DoesNotExist:
            return {"id": str(other.id)}

    def get_last_message(self, obj):
        # ✅ Ye values ab view mein annotate() se already attached hain
        #    (Subquery), isliye yahan koi extra DB query nahi lagti.
        msg_id = getattr(obj, "last_message_id", None)
        if not msg_id:
            # fallback (agar kabhi annotate ke bina call ho)
            msg = obj.messages.order_by("-created_at").first()
            return MessageSerializer(msg).data if msg else None

        return {
            "id":         msg_id,
            "sender_id":  str(obj.last_message_sender_id),
            "text":       obj.last_message_text,
            "is_read":    obj.last_message_is_read,
            "created_at": obj.last_message_created_at,
        }


# ─────────────────────────────────────────
# BLOCK / REPORT
# ─────────────────────────────────────────

class BlockSerializer(serializers.ModelSerializer):
    blocked_id = serializers.CharField(write_only=True)

    class Meta:
        model        = Block
        fields       = ["id", "blocked_id", "created_at"]
        read_only_fields = ["id", "created_at"]

    def validate_blocked_id(self, value):
        request = self.context["request"]
        blocked = get_user_from_id(value)
        if blocked == request.user:
            raise serializers.ValidationError("Apne aap ko block nahi kar sakte")
        if Block.objects.filter(blocker=request.user, blocked=blocked).exists():
            raise serializers.ValidationError("Already blocked")
        return str(blocked.id)

    def create(self, validated_data):
        return Block.objects.create(
            blocker=self.context["request"].user,
            blocked=User.objects.get(id=validated_data["blocked_id"])
        )


class ReportSerializer(serializers.ModelSerializer):
    reported_id = serializers.CharField(write_only=True)

    class Meta:
        model        = Report
        fields       = ["id", "reported_id", "reason", "description", "created_at"]
        read_only_fields = ["id", "created_at"]

    def validate_reported_id(self, value):
        request  = self.context["request"]
        reported = get_user_from_id(value)
        if reported == request.user:
            raise serializers.ValidationError("Apne aap ko report nahi kar sakte")
        return str(reported.id)

    def create(self, validated_data):
        reported = User.objects.get(id=validated_data.pop("reported_id"))
        return Report.objects.create(
            reporter=self.context["request"].user,
            reported=reported,
            **validated_data
        )


# ─────────────────────────────────────────
# SUBSCRIPTION  (Razorpay)
# ─────────────────────────────────────────

class SubscriptionSerializer(serializers.ModelSerializer):
    plan_label = serializers.SerializerMethodField()

    class Meta:
        model  = Subscription
        fields = [
            "id", "plan", "plan_label", "amount", "currency",
            "status", "is_trial", "starts_at", "expires_at", "created_at",
        ]
        read_only_fields = fields

    def get_plan_label(self, obj):
        return PLAN_CONFIG.get(obj.plan, {}).get("label", obj.plan)


class CreateSubscriptionOrderSerializer(serializers.Serializer):
    plan = serializers.ChoiceField(choices=list(PLAN_CONFIG.keys()))


class VerifySubscriptionPaymentSerializer(serializers.Serializer):
    """
    Frontend Razorpay checkout success ke baad ye teeno fields deta hai.
    Signature verify karke hi subscription 'paid' mark hoti hai — kabhi
    bhi client se aaye 'success' flag pe bharosa nahi karte.
    """
    razorpay_order_id   = serializers.CharField()
    razorpay_payment_id = serializers.CharField()
    razorpay_signature  = serializers.CharField()

    def validate(self, data):
        subscription = Subscription.objects.filter(
            razorpay_order_id=data["razorpay_order_id"]
        ).first()
        if not subscription:
            raise serializers.ValidationError("Order not found")

        request = self.context["request"]
        if subscription.user != request.user:
            raise serializers.ValidationError("Not allowed")

        # Idempotent — agar webhook ne already mark_paid kar diya ho
        if subscription.status == "paid":
            data["subscription"] = subscription
            return data

        from .razorpay_client import verify_payment_signature
        valid = verify_payment_signature(
            data["razorpay_order_id"],
            data["razorpay_payment_id"],
            data["razorpay_signature"],
        )
        if not valid:
            subscription.status = "failed"
            subscription.save(update_fields=["status", "updated_at"])
            raise serializers.ValidationError("Payment verification failed")

        data["subscription"] = subscription
        return data