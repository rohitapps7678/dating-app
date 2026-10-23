"""
Single source of truth for "can this user use the app right now?".

  • first 7 days  → free trial (auto-started, no card)
  • after that    → needs an active Google Play subscription
  • TEST_PHONE_NUMBER (Play review / QA account) → always allowed
"""
import os
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import APIException
from rest_framework.permissions import BasePermission

from .models import Subscription, FREE_TRIAL_DAYS


class SubscriptionRequired(APIException):
    status_code    = 402
    default_detail = "Your free trial has ended. Please subscribe to continue."
    default_code   = "subscription_required"


def is_review_account(user):
    test_phone = os.getenv("TEST_PHONE_NUMBER", "+918171639413").strip()
    return bool(test_phone) and user.phone == test_phone


def ensure_trial(user):
    """Start the one-time trial if this user never had one. True if created."""
    if Subscription.objects.filter(user=user, is_trial=True).exists():
        return False
    now = timezone.now()
    try:
        with transaction.atomic():
            Subscription.objects.create(
                user=user, plan="month", amount=0,
                status="paid", is_trial=True, source="trial",
                starts_at=now, expires_at=now + timedelta(days=FREE_TRIAL_DAYS),
            )
        return True
    except IntegrityError:          # parallel request already created it
        return False


def user_has_access(user):
    if is_review_account(user):
        return True
    if user.is_premium:             # trial OR paid, not expired
        return True
    # Never seen before (new signup / pre-existing user) → start trial now.
    return ensure_trial(user)


class HasActiveAccess(BasePermission):
    """Use AFTER IsAuthenticated:  [IsAuthenticated, HasActiveAccess]"""

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user_has_access(user):
            return True
        raise SubscriptionRequired()