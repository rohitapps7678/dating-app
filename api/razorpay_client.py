"""
Thin wrapper around the `razorpay` Python SDK — keeps views.py clean and
gives one place to mock/stub Razorpay calls in tests.

Setup:
    pip install razorpay

settings.py:
    RAZORPAY_KEY_ID        = env("RAZORPAY_KEY_ID")
    RAZORPAY_KEY_SECRET    = env("RAZORPAY_KEY_SECRET")
    RAZORPAY_WEBHOOK_SECRET= env("RAZORPAY_WEBHOOK_SECRET")   # optional, for webhook
"""
import razorpay
from django.conf import settings

_client = None


def get_client():
    global _client
    if _client is None:
        _client = razorpay.Client(
            auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
        )
    return _client


def create_order(amount_paise, receipt, notes=None):
    """amount_paise: integer, smallest currency unit (₹1 = 100 paise)."""
    client = get_client()
    return client.order.create({
        "amount": amount_paise,
        "currency": "INR",
        "receipt": receipt,
        "notes": notes or {},
        "payment_capture": 1,   # auto-capture — no separate capture call needed
    })


def verify_payment_signature(order_id, payment_id, signature):
    """Call this after checkout success, before trusting the payment."""
    client = get_client()
    try:
        client.utility.verify_payment_signature({
            "razorpay_order_id":   order_id,
            "razorpay_payment_id": payment_id,
            "razorpay_signature":  signature,
        })
        return True
    except razorpay.errors.SignatureVerificationError:
        return False


def verify_webhook_signature(payload, signature):
    """
    payload: raw request body (str), signature: X-Razorpay-Signature header.
    Requires RAZORPAY_WEBHOOK_SECRET to be set (from Razorpay Dashboard →
    Settings → Webhooks → the secret you set when adding the webhook URL).
    """
    if not getattr(settings, "RAZORPAY_WEBHOOK_SECRET", None):
        return False
    client = get_client()
    try:
        client.utility.verify_webhook_signature(
            payload, signature, settings.RAZORPAY_WEBHOOK_SECRET
        )
        return True
    except razorpay.errors.SignatureVerificationError:
        return False