"""
dating_backend/api/admin_urls.py
Main urls.py mein include karo:
  path("api/admin/", include("api.admin_urls")),
"""
from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from .admin_views import (
    AdminLoginView,
    AdminDashboardView,
    AdminUserListView, AdminUserDetailView, AdminUserDeleteView,
    AdminReportListView, AdminReportDeleteView,
    AdminMatchListView, AdminMatchDeleteView,
    AdminMessageListView,
    AdminStatsView,
)

urlpatterns = [
    # Auth
    path("login/",         AdminLoginView.as_view(),    name="admin-login"),
    path("token/refresh/", TokenRefreshView.as_view(),  name="admin-token-refresh"),

    # Dashboard
    path("dashboard/",     AdminDashboardView.as_view(), name="admin-dashboard"),
    path("stats/",         AdminStatsView.as_view(),     name="admin-stats"),

    # Users
    path("users/",                      AdminUserListView.as_view(),   name="admin-users"),
    path("users/<str:user_id>/",        AdminUserDetailView.as_view(), name="admin-user-detail"),
    path("users/<str:user_id>/delete/", AdminUserDeleteView.as_view(), name="admin-user-delete"),

    # Reports
    path("reports/",               AdminReportListView.as_view(),  name="admin-reports"),
    path("reports/<int:report_id>/", AdminReportDeleteView.as_view(), name="admin-report-delete"),

    # Matches
    path("matches/",               AdminMatchListView.as_view(),   name="admin-matches"),
    path("matches/<int:match_id>/", AdminMatchDeleteView.as_view(), name="admin-match-delete"),

    # Messages
    path("messages/", AdminMessageListView.as_view(), name="admin-messages"),
]