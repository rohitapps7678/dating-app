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
import os

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


def _package_name():
    pkg = (getattr(settings, "GOOGLE_PLAY_PACKAGE_NAME", "")
           or os.environ.get("GOOGLE_PLAY_PACKAGE_NAME", ""))
    if not pkg:
        raise GooglePlayError("GOOGLE_PLAY_PACKAGE_NAME is not configured on the server")
    return pkg


def _client():
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError:
        logger.exception("Google API libraries missing")
        raise GooglePlayError(
            "Server is missing google-api-python-client / google-auth")

    raw = (getattr(settings, "GOOGLE_PLAY_SERVICE_ACCOUNT_JSON", "")
           or os.environ.get("GOOGLE_PLAY_SERVICE_ACCOUNT_JSON", ""))
    if not raw:
        raise GooglePlayError("GOOGLE_PLAY_SERVICE_ACCOUNT_JSON not configured")
    try:
        info = json.loads(raw)
    except ValueError:
        logger.exception("GOOGLE_PLAY_SERVICE_ACCOUNT_JSON is not valid JSON")
        raise GooglePlayError("GOOGLE_PLAY_SERVICE_ACCOUNT_JSON is not valid JSON")
    try:
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=SCOPES)
        return build("androidpublisher", "v3", credentials=creds,
                     cache_discovery=False)
    except Exception:
        logger.exception("Could not build Google Play client")
        raise GooglePlayError("Service account key is invalid")


def fetch_subscription(purchase_token):
    try:
        from googleapiclient.errors import HttpError
    except ImportError:
        logger.exception("google-api-python-client not installed")
        raise GooglePlayError(
            "Server is missing google-api-python-client / google-auth")
    package = _package_name()
    try:
        return (
            _client().purchases().subscriptionsv2()
            .get(packageName=package, token=purchase_token)
            .execute()
        )
    except GooglePlayError:
        raise
    except HttpError as e:
        status = getattr(e.resp, "status", None)
        # full Google reply goes to the server log — this is what tells you
        # whether it is permissions, wrong package, bad token, etc.
        logger.error("Play API HttpError %s for token ...%s: %s",
                     status, purchase_token[-6:], e.content)
        if status in (400, 404, 410):
            raise GooglePlayError("Invalid or expired purchase token")
        if status in (401, 403):
            raise GooglePlayError(
                "Server is not authorised on Google Play. Give the service "
                "account 'View financial data' + 'Manage orders and "
                "subscriptions' in Play Console > Users and permissions.")
        raise GooglePlayError("Google Play is unavailable, try again")
    except Exception:
        # google.auth RefreshError / TransportError etc.
        logger.exception("Play API call failed for token ...%s", purchase_token[-6:])
        raise GooglePlayError("Could not authenticate with Google Play")


def acknowledge(product_id, purchase_token):
    """Unacknowledged purchases are auto-refunded by Google after 3 days."""
    try:
        (_client().purchases().subscriptions()
         .acknowledge(packageName=_package_name(),
                      subscriptionId=product_id, token=purchase_token, body={})
         .execute())
    except Exception as e:
        # already acknowledged by the client (completePurchase) → harmless
        logger.info("acknowledge skipped for ...%s: %s", purchase_token[-6:], e)


def parse_subscription(data):
    items = data.get("lineItems") or []
    if not items:
        raise GooglePlayError("Purchase has no line items")
    item = max(items, key=lambda i: i.get("expiryTime", ""))
    expiry = parse_datetime(item.get("expiryTime") or "")
    if expiry is None:
        raise GooglePlayError("Purchase has no expiry time")
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