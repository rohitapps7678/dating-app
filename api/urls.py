from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from .views import (
    HealthView,
    InterestsListView, InterestSuggestionsView,
    FirebaseAuthView, LogoutView,
    RegisterView, LoginView,
    ProfileView, OtherProfileView,
    PhotoUploadView, LiveToggleView,
    SearchView, NearbyUsersView,
    LikeView, MatchListView,
    ConversationListView, MessageListView, StartConversationView,
    BlockView, ReportView,
    SubscriptionPlansView, SubscriptionStatusView,
    CreateSubscriptionOrderView, VerifySubscriptionPaymentView,
    RazorpayWebhookView, ClaimFreeTrialView,
)

urlpatterns = [
    path("health/",                HealthView.as_view(),            name="health"),

    # ── AUTH (Phone OTP via Firebase) ──
    path("auth/firebase/",         FirebaseAuthView.as_view(),      name="firebase-auth"),
    path("auth/logout/",           LogoutView.as_view(),            name="logout"),
    path("auth/token/refresh/",    TokenRefreshView.as_view(),      name="token-refresh"),

    # ── AUTH (Username + Password) ──
    path("auth/register/",         RegisterView.as_view(),          name="register"),
    path("auth/login/",            LoginView.as_view(),             name="login"),

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
    path("conversations/start/",   StartConversationView.as_view(), name="start-conversation"),
    path("conversations/<int:conv_id>/messages/", MessageListView.as_view(), name="message-list"),

    # ── BLOCK / REPORT ──
    path("block/",                 BlockView.as_view(),             name="block"),
    path("block/<str:user_id>/",   BlockView.as_view(),             name="unblock"),
    path("report/",                ReportView.as_view(),            name="report"),

    # ── SUBSCRIPTION / RAZORPAY ──
    path("subscriptions/plans/",        SubscriptionPlansView.as_view(),         name="subscription-plans"),
    path("subscriptions/status/",       SubscriptionStatusView.as_view(),        name="subscription-status"),
    path("subscriptions/create-order/", CreateSubscriptionOrderView.as_view(),   name="subscription-create-order"),
    path("subscriptions/verify/",       VerifySubscriptionPaymentView.as_view(), name="subscription-verify"),
    path("subscriptions/claim-trial/",  ClaimFreeTrialView.as_view(),            name="subscription-claim-trial"),
    path("subscriptions/webhook/",      RazorpayWebhookView.as_view(),           name="subscription-webhook"),
]