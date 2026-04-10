"""
Dating App — Admin API Views
Mount karo dating_backend/api/admin_views.py pe
"""
from rest_framework import status, permissions
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import authenticate
from django.db.models import Count, Q
from django.utils import timezone
from datetime import timedelta

from .models import User, Profile, Like, Match, Conversation, Message, Block, Report


# ─────────────────────────────────────────
# PERMISSION
# ─────────────────────────────────────────

class IsAdminUser(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated and request.user.is_staff


# ─────────────────────────────────────────
# ADMIN LOGIN
# ─────────────────────────────────────────

class AdminLoginView(APIView):
    """POST /api/admin/login/"""
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        phone    = request.data.get("phone", "")
        password = request.data.get("password", "")
        user     = authenticate(username=phone, password=password)

        if not user or not user.is_staff:
            return Response(
                {"error": "Invalid credentials or not an admin"},
                status=status.HTTP_401_UNAUTHORIZED
            )

        refresh = RefreshToken.for_user(user)
        return Response({
            "access":  str(refresh.access_token),
            "refresh": str(refresh),
            "admin": {
                "id":    str(user.id),
                "phone": user.phone,
            }
        })


# ─────────────────────────────────────────
# DASHBOARD STATS
# ─────────────────────────────────────────

class AdminDashboardView(APIView):
    """GET /api/admin/dashboard/"""
    permission_classes = [IsAdminUser]

    def get(self, request):
        now       = timezone.now()
        today     = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_ago  = now - timedelta(days=7)
        month_ago = now - timedelta(days=30)

        total_users    = User.objects.count()
        active_users   = User.objects.filter(is_active=True).count()
        live_users     = Profile.objects.filter(is_live=True).count()
        new_today      = User.objects.filter(created_at__gte=today).count()
        new_this_week  = User.objects.filter(created_at__gte=week_ago).count()
        new_this_month = User.objects.filter(created_at__gte=month_ago).count()

        total_matches  = Match.objects.count()
        total_likes    = Like.objects.count()
        total_messages = Message.objects.count()
        total_reports  = Report.objects.filter().count()
        pending_reports = Report.objects.count()  # all reports

        # Gender breakdown
        male_count   = Profile.objects.filter(gender='M').count()
        female_count = Profile.objects.filter(gender='F').count()
        other_count  = Profile.objects.filter(gender='O').count()

        # Daily signups last 7 days
        daily_signups = []
        for i in range(6, -1, -1):
            day_start = now - timedelta(days=i)
            day_start = day_start.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end   = day_start + timedelta(days=1)
            count     = User.objects.filter(
                created_at__gte=day_start, created_at__lt=day_end
            ).count()
            daily_signups.append({
                "date":  day_start.strftime("%d %b"),
                "count": count,
            })

        # Top interests
        all_interests = {}
        for profile in Profile.objects.exclude(interests=[]):
            for interest in (profile.interests or []):
                all_interests[interest] = all_interests.get(interest, 0) + 1
        top_interests = sorted(all_interests.items(), key=lambda x: -x[1])[:10]

        return Response({
            "users": {
                "total":      total_users,
                "active":     active_users,
                "live_now":   live_users,
                "new_today":  new_today,
                "new_week":   new_this_week,
                "new_month":  new_this_month,
            },
            "activity": {
                "total_matches":  total_matches,
                "total_likes":    total_likes,
                "total_messages": total_messages,
                "pending_reports": pending_reports,
            },
            "gender_breakdown": {
                "male":   male_count,
                "female": female_count,
                "other":  other_count,
            },
            "daily_signups":  daily_signups,
            "top_interests":  [{"name": k, "count": v} for k, v in top_interests],
        })


# ─────────────────────────────────────────
# USERS
# ─────────────────────────────────────────

class AdminUserListView(APIView):
    """GET /api/admin/users/?page=1&q=&gender=&is_active=&is_live="""
    permission_classes = [IsAdminUser]

    def get(self, request):
        qs = User.objects.select_related("profile").order_by("-created_at")

        # Filters
        q         = request.query_params.get("q", "").strip()
        gender    = request.query_params.get("gender", "")
        is_active = request.query_params.get("is_active", "")
        is_live   = request.query_params.get("is_live", "")
        is_staff  = request.query_params.get("is_staff", "")

        if q:
            qs = qs.filter(
                Q(phone__icontains=q) |
                Q(profile__name__icontains=q)
            )
        if gender in ("M", "F", "O"):
            qs = qs.filter(profile__gender=gender)
        if is_active in ("true", "false"):
            qs = qs.filter(is_active=is_active == "true")
        if is_live == "true":
            qs = qs.filter(profile__is_live=True)
        if is_staff in ("true", "false"):
            qs = qs.filter(is_staff=is_staff == "true")

        # Pagination
        page      = int(request.query_params.get("page", 1))
        page_size = 20
        total     = qs.count()
        qs        = qs[(page - 1) * page_size: page * page_size]

        users = []
        for user in qs:
            try:
                p = user.profile
                users.append({
                    "id":         str(user.id),
                    "phone":      user.phone,
                    "name":       p.name,
                    "age":        p.age,
                    "gender":     p.gender,
                    "photo_url":  p.photo_url,
                    "is_live":    p.is_live,
                    "is_complete": p.is_complete,
                    "is_active":  user.is_active,
                    "is_staff":   user.is_staff,
                    "created_at": user.created_at.isoformat(),
                })
            except Profile.DoesNotExist:
                users.append({
                    "id":        str(user.id),
                    "phone":     user.phone,
                    "name":      "",
                    "is_active": user.is_active,
                    "is_staff":  user.is_staff,
                    "created_at": user.created_at.isoformat(),
                })

        return Response({
            "total":    total,
            "page":     page,
            "pages":    (total + page_size - 1) // page_size,
            "results":  users,
        })


class AdminUserDetailView(APIView):
    """GET/PATCH /api/admin/users/<user_id>/"""
    permission_classes = [IsAdminUser]

    def get(self, request, user_id):
        try:
            user = User.objects.select_related("profile").get(id=user_id)
        except User.DoesNotExist:
            return Response({"error": "User not found"}, status=404)

        try:
            p = user.profile
            profile_data = {
                "name":        p.name,
                "bio":         p.bio,
                "age":         p.age,
                "gender":      p.gender,
                "photo_url":   p.photo_url,
                "interests":   p.interests,
                "position":    p.position,
                "has_room":    p.has_room,
                "is_live":     p.is_live,
                "is_complete": p.is_complete,
                "latitude":    p.latitude,
                "longitude":   p.longitude,
            }
        except Profile.DoesNotExist:
            profile_data = {}

        # Stats
        likes_sent     = Like.objects.filter(sender=user).count()
        likes_received = Like.objects.filter(receiver=user).count()
        matches        = (Match.objects.filter(user1=user) | Match.objects.filter(user2=user)).count()
        messages_sent  = Message.objects.filter(sender=user).count()
        reports_made   = Report.objects.filter(reporter=user).count()
        reports_received = Report.objects.filter(reported=user).count()
        blocks_made    = Block.objects.filter(blocker=user).count()

        # Recent reports against this user
        recent_reports = []
        for r in Report.objects.filter(reported=user).select_related("reporter__profile").order_by("-created_at")[:5]:
            try:
                reporter_name = r.reporter.profile.name
            except Profile.DoesNotExist:
                reporter_name = r.reporter.phone
            recent_reports.append({
                "reporter": reporter_name,
                "reason":   r.reason,
                "desc":     r.description,
                "date":     r.created_at.isoformat(),
            })

        return Response({
            "id":         str(user.id),
            "phone":      user.phone,
            "is_active":  user.is_active,
            "is_staff":   user.is_staff,
            "created_at": user.created_at.isoformat(),
            "profile":    profile_data,
            "stats": {
                "likes_sent":       likes_sent,
                "likes_received":   likes_received,
                "matches":          matches,
                "messages_sent":    messages_sent,
                "reports_made":     reports_made,
                "reports_received": reports_received,
                "blocks_made":      blocks_made,
            },
            "recent_reports": recent_reports,
        })

    def patch(self, request, user_id):
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response({"error": "User not found"}, status=404)

        # Ban / unban
        if "is_active" in request.data:
            user.is_active = request.data["is_active"]
            user.save(update_fields=["is_active"])

        # Make admin / remove admin
        if "is_staff" in request.data:
            user.is_staff = request.data["is_staff"]
            user.save(update_fields=["is_staff"])

        return Response({"success": True, "is_active": user.is_active, "is_staff": user.is_staff})


class AdminUserDeleteView(APIView):
    """DELETE /api/admin/users/<user_id>/delete/"""
    permission_classes = [IsAdminUser]

    def delete(self, request, user_id):
        try:
            user = User.objects.get(id=user_id)
            user.delete()
            return Response({"success": True})
        except User.DoesNotExist:
            return Response({"error": "User not found"}, status=404)


# ─────────────────────────────────────────
# REPORTS
# ─────────────────────────────────────────

class AdminReportListView(APIView):
    """GET /api/admin/reports/?page=1&reason="""
    permission_classes = [IsAdminUser]

    def get(self, request):
        qs = Report.objects.select_related(
            "reporter__profile", "reported__profile"
        ).order_by("-created_at")

        reason = request.query_params.get("reason", "")
        if reason:
            qs = qs.filter(reason=reason)

        page      = int(request.query_params.get("page", 1))
        page_size = 20
        total     = qs.count()
        qs        = qs[(page - 1) * page_size: page * page_size]

        results = []
        for r in qs:
            try:
                reporter_name = r.reporter.profile.name or r.reporter.phone
            except Profile.DoesNotExist:
                reporter_name = r.reporter.phone
            try:
                reported_name = r.reported.profile.name or r.reported.phone
                reported_photo = r.reported.profile.photo_url
            except Profile.DoesNotExist:
                reported_name  = r.reported.phone
                reported_photo = None

            results.append({
                "id":            r.id,
                "reporter_name": reporter_name,
                "reporter_id":   str(r.reporter.id),
                "reported_name": reported_name,
                "reported_id":   str(r.reported.id),
                "reported_photo": reported_photo,
                "reason":        r.reason,
                "description":   r.description,
                "created_at":    r.created_at.isoformat(),
            })

        return Response({
            "total":   total,
            "page":    page,
            "pages":   (total + page_size - 1) // page_size,
            "results": results,
        })


class AdminReportDeleteView(APIView):
    """DELETE /api/admin/reports/<report_id>/"""
    permission_classes = [IsAdminUser]

    def delete(self, request, report_id):
        try:
            Report.objects.get(id=report_id).delete()
            return Response({"success": True})
        except Report.DoesNotExist:
            return Response({"error": "Not found"}, status=404)


# ─────────────────────────────────────────
# MATCHES
# ─────────────────────────────────────────

class AdminMatchListView(APIView):
    """GET /api/admin/matches/?page=1"""
    permission_classes = [IsAdminUser]

    def get(self, request):
        qs = Match.objects.select_related(
            "user1__profile", "user2__profile"
        ).order_by("-created_at")

        page      = int(request.query_params.get("page", 1))
        page_size = 20
        total     = qs.count()
        qs        = qs[(page - 1) * page_size: page * page_size]

        results = []
        for m in qs:
            try: u1_name = m.user1.profile.name
            except: u1_name = m.user1.phone
            try: u2_name = m.user2.profile.name
            except: u2_name = m.user2.phone
            try: u1_photo = m.user1.profile.photo_url
            except: u1_photo = None
            try: u2_photo = m.user2.profile.photo_url
            except: u2_photo = None

            msg_count = 0
            try:
                msg_count = m.conversation.messages.count()
            except Exception:
                pass

            results.append({
                "id":         m.id,
                "user1":      {"id": str(m.user1.id), "name": u1_name, "photo": u1_photo},
                "user2":      {"id": str(m.user2.id), "name": u2_name, "photo": u2_photo},
                "msg_count":  msg_count,
                "created_at": m.created_at.isoformat(),
            })

        return Response({
            "total":   total,
            "page":    page,
            "pages":   (total + page_size - 1) // page_size,
            "results": results,
        })


class AdminMatchDeleteView(APIView):
    """DELETE /api/admin/matches/<match_id>/"""
    permission_classes = [IsAdminUser]

    def delete(self, request, match_id):
        try:
            Match.objects.get(id=match_id).delete()
            return Response({"success": True})
        except Match.DoesNotExist:
            return Response({"error": "Not found"}, status=404)


# ─────────────────────────────────────────
# MESSAGES (monitoring)
# ─────────────────────────────────────────

class AdminMessageListView(APIView):
    """GET /api/admin/messages/?conv_id=&page=1"""
    permission_classes = [IsAdminUser]

    def get(self, request):
        conv_id = request.query_params.get("conv_id")
        page    = int(request.query_params.get("page", 1))
        page_size = 30

        if conv_id:
            qs = Message.objects.filter(
                conversation_id=conv_id
            ).select_related("sender__profile").order_by("created_at")
        else:
            qs = Message.objects.select_related(
                "sender__profile"
            ).order_by("-created_at")

        total = qs.count()
        qs    = qs[(page - 1) * page_size: page * page_size]

        results = []
        for m in qs:
            try: sender_name = m.sender.profile.name
            except: sender_name = m.sender.phone
            results.append({
                "id":          m.id,
                "sender_name": sender_name,
                "sender_id":   str(m.sender.id),
                "text":        m.text,
                "conv_id":     m.conversation_id,
                "created_at":  m.created_at.isoformat(),
            })

        return Response({
            "total":   total,
            "page":    page,
            "pages":   (total + page_size - 1) // page_size,
            "results": results,
        })


# ─────────────────────────────────────────
# APP STATS (for charts)
# ─────────────────────────────────────────

class AdminStatsView(APIView):
    """GET /api/admin/stats/?period=7  (7 or 30 days)"""
    permission_classes = [IsAdminUser]

    def get(self, request):
        period = int(request.query_params.get("period", 7))
        now    = timezone.now()

        signups = []
        matches = []
        for i in range(period - 1, -1, -1):
            day_start = (now - timedelta(days=i)).replace(
                hour=0, minute=0, second=0, microsecond=0)
            day_end   = day_start + timedelta(days=1)
            label     = day_start.strftime("%d %b")
            signups.append({
                "date":  label,
                "count": User.objects.filter(
                    created_at__gte=day_start, created_at__lt=day_end).count()
            })
            matches.append({
                "date":  label,
                "count": Match.objects.filter(
                    created_at__gte=day_start, created_at__lt=day_end).count()
            })

        return Response({
            "signups": signups,
            "matches": matches,
        })