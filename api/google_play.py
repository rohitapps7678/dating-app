"""
Google Play Billing — server-side verification + sync.

Flow:
  1. App buys via Play Billing  → gets a `purchaseToken`.
  2. App POSTs token to /api/subscriptions/google/verify/.
  3. We ask Google (purchases.subscriptionsv2.get) what that token really
     is — NEVER trust the client — then upsert a Subscription row.
  4. Google also pushes Real-time Developer Notifications (RTDN, via
     Pub/Sub) on renew / cancel / expire / refund → /subscriptions/google/rtdn/
     which re-syncs the same row.

Env / settings needed:
  GOOGLE_PLAY_PACKAGE_NAME            e.g. com.yourco.opentalk
  GOOGLE_PLAY_SERVICE_ACCOUNT_JSON    full JSON key content (string)
  GOOGLE_PLAY_RTDN_TOKEN              long random string (query param secret)
"""
import json
import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import Subscription, User, PLAN_CONFIG

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/androidpublisher"]

# Access while in these states (CANCELED = user turned off auto-renew but
# already paid till expiry; GRACE_PERIOD = payment retry, Google says keep access).
ENTITLED_STATES = {
    "SUBSCRIPTION_STATE_ACTIVE",
    "SUBSCRIPTION_STATE_CANCELED",
    "SUBSCRIPTION_STATE_IN_GRACE_PERIOD",
}

PRODUCT_TO_PLAN = {cfg["product_id"]: key for key, cfg in PLAN_CONFIG.items()}


class GooglePlayError(Exception):
    pass


def _client():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    raw = getattr(settings, "GOOGLE_PLAY_SERVICE_ACCOUNT_JSON", "")
    if not raw:
        raise GooglePlayError("GOOGLE_PLAY_SERVICE_ACCOUNT_JSON not configured")
    creds = service_account.Credentials.from_service_account_info(
        json.loads(raw), scopes=SCOPES)
    return build("androidpublisher", "v3", credentials=creds, cache_discovery=False)


def fetch_subscription(purchase_token):
    from googleapiclient.errors import HttpError
    try:
        return (
            _client().purchases().subscriptionsv2()
            .get(packageName=settings.GOOGLE_PLAY_PACKAGE_NAME, token=purchase_token)
            .execute()
        )
    except HttpError as e:
        status = getattr(e.resp, "status", None)
        logger.warning("Play API error %s for token …%s", status, purchase_token[-6:])
        if status in (400, 404, 410):
            raise GooglePlayError("Invalid or expired purchase token")
        raise GooglePlayError("Google Play is unavailable, try again")


def acknowledge(product_id, purchase_token):
    """Unacknowledged purchases are auto-refunded by Google after 3 days."""
    try:
        (_client().purchases().subscriptions()
         .acknowledge(packageName=settings.GOOGLE_PLAY_PACKAGE_NAME,
                      subscriptionId=product_id, token=purchase_token, body={})
         .execute())
    except Exception:
        # already acknowledged by the client (completePurchase) → harmless
        logger.info("acknowledge skipped for …%s", purchase_token[-6:])


def parse_subscription(data):
    items = data.get("lineItems") or []
    if not items:
        raise GooglePlayError("Purchase has no line items")
    item = max(items, key=lambda i: i.get("expiryTime", ""))
    expiry = parse_datetime(item["expiryTime"])
    start = parse_datetime(data["startTime"]) if data.get("startTime") else None
    state = data.get("subscriptionState", "")
    ext = data.get("externalAccountIdentifiers") or {}
    return {
        "product_id": item.get("productId"),
        "expiry": expiry,
        "start": start,
        "state": state,
        "entitled": state in ENTITLED_STATES and expiry > timezone.now(),
        "ack_pending": data.get("acknowledgementState") == "ACKNOWLEDGEMENT_STATE_PENDING",
        "order_id": data.get("latestOrderId"),
        "account_id": ext.get("obfuscatedExternalAccountId"),
        "auto_renewing": bool(
            (item.get("autoRenewingPlan") or {}).get("autoRenewEnabled")),
    }


def _user_from_account_id(account_id):
    if not account_id:
        return None
    try:
        return User.objects.filter(id=account_id).first()
    except Exception:
        return None


@transaction.atomic
def sync_purchase(purchase_token, user=None):
    """
    Pull the truth from Google and upsert the Subscription row.
    `user` = logged-in user (verify endpoint) or None (RTDN → resolved from
    the obfuscated account id we attached at purchase time).
    Returns (subscription | None, parsed dict).
    """
    p = parse_subscription(fetch_subscription(purchase_token))

    plan = PRODUCT_TO_PLAN.get(p["product_id"])
    if not plan:
        raise GooglePlayError("Unknown product")

    sub = (Subscription.objects.select_for_update()
           .filter(google_purchase_token=purchase_token).first())

    if sub and user and sub.user_id != user.id:
        raise GooglePlayError("This purchase belongs to another account")

    # Bind to the account that started the purchase (stops token sharing).
    if user and p["account_id"] and p["account_id"] != str(user.id):
        raise GooglePlayError("This purchase belongs to another account")

    owner = sub.user if sub else (user or _user_from_account_id(p["account_id"]))
    if owner is None:
        logger.warning("RTDN for unknown owner …%s", purchase_token[-6:])
        return None, p

    fields = dict(
        user=owner,
        plan=plan,
        amount=PLAN_CONFIG[plan]["price_inr"] * 100,
        currency="INR",
        status="paid" if p["entitled"] else "cancelled",
        source="google_play",
        is_trial=False,
        starts_at=p["start"],
        expires_at=p["expiry"],
        google_product_id=p["product_id"],
        google_order_id=p["order_id"] or "",
        auto_renewing=p["auto_renewing"],
    )
    if sub:
        for k, v in fields.items():
            setattr(sub, k, v)
        sub.save()
    else:
        sub = Subscription.objects.create(
            google_purchase_token=purchase_token, **fields)

    if p["entitled"] and p["ack_pending"]:
        acknowledge(p["product_id"], purchase_token)

    return sub, p