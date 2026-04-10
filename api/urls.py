from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from .views import (
    HealthView,
    InterestsListView, InterestSuggestionsView,
    EmailOtpSendView, EmailOtpVerifyView, LogoutView,
    ProfileView, OtherProfileView,
    PhotoUploadView, LiveToggleView,
    SearchView, NearbyUsersView,
    LikeView, MatchListView,
    ConversationListView, MessageListView,
    BlockView, ReportView,
)

urlpatterns = [
    path("health/",                HealthView.as_view(),            name="health"),

    # ── AUTH (Email OTP via Brevo) ──
    path("auth/email-otp/send/",   EmailOtpSendView.as_view(),      name="email-otp-send"),
    path("auth/email-otp/verify/", EmailOtpVerifyView.as_view(),    name="email-otp-verify"),
    path("auth/logout/",           LogoutView.as_view(),            name="logout"),
    path("auth/token/refresh/",    TokenRefreshView.as_view(),      name="token-refresh"),

    # ── PROFILE ──
    path("profile/",               ProfileView.as_view(),           name="my-profile"),
    path("profile/upload-photo/",  PhotoUploadView.as_view(),       name="upload-photo"),
    path("profile/live/",          LiveToggleView.as_view(),        name="live-toggle"),
    path("profile/<str:user_id>/", OtherProfileView.as_view(),      name="other-profile"),

    # ── INTERESTS ──
    path("interests/",             InterestsListView.as_view(),     name="interests-list"),
    path("interests/suggestions/", InterestSuggestionsView.as_view(),name="interest-suggestions"),

    # ── SEARCH + NEARBY ──
    path("search/",                SearchView.as_view(),            name="search"),
    path("nearby/",                NearbyUsersView.as_view(),       name="nearby-users"),

    # ── LIKE / MATCH ──
    path("like/",                  LikeView.as_view(),              name="like"),
    path("matches/",               MatchListView.as_view(),         name="match-list"),

    # ── CHAT ──
    path("conversations/",         ConversationListView.as_view(),  name="conversation-list"),
    path("conversations/<int:conv_id>/messages/", MessageListView.as_view(), name="message-list"),

    # ── BLOCK / REPORT ──
    path("block/",                 BlockView.as_view(),             name="block"),
    path("block/<str:user_id>/",   BlockView.as_view(),             name="unblock"),
    path("report/",                ReportView.as_view(),            name="report"),
]