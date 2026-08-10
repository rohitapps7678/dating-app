"""
Firebase Cloud Messaging (FCM) — real push notifications.

Firebase Admin SDK phone-OTP verification ke liye pehle se use ho raha
hai (`firebase_admin.auth.verify_id_token` in FirebaseAuthView) — is
module mein firebase_admin ko dobara initialize NAHI kiya jaata agar
wo already ho chuka ho (`firebase_admin._apps` check). Agar abhi tak
kahin init nahi hua, ye khud `FIREBASE_SERVICE_ACCOUNT_JSON` env var
(poora service-account JSON ek string ke roop mein — file nahi) se
initialize kar leta hai, taaki dono jagah (OTP verify + push) ek hi
Firebase app instance use karein.
"""

import json
import logging
import os
import threading

from django.conf import settings

logger = logging.getLogger(__name__)

_init_lock    = threading.Lock()
_initialized  = False
_push_enabled = False


def _ensure_firebase_initialized():
    global _initialized, _push_enabled
    if _initialized:
        return
    with _init_lock:
        if _initialized:
            return
        try:
            import firebase_admin
            from firebase_admin import credentials

            if firebase_admin._apps:
                # ✅ OTP verify wale view ne (ya kisi aur jagah) pehle se
                # ek Firebase app initialize kar rakha hai — wahi reuse
                # karo, dobara initialize karne ki koshish karne se
                # ValueError ("app already exists") aayega.
                _push_enabled = True
            else:
                raw = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON") or getattr(
                    settings, "FIREBASE_SERVICE_ACCOUNT_JSON", None
                )
                if not raw:
                    logger.warning(
                        "FIREBASE_SERVICE_ACCOUNT_JSON env var set nahi hai — "
                        "push notifications disabled (in-app notifications "
                        "phir bhi kaam karengi)."
                    )
                    _initialized = True
                    return
                cred_dict = json.loads(raw)
                cred = credentials.Certificate(cred_dict)
                firebase_admin.initialize_app(cred)
                _push_enabled = True
        except Exception:
            logger.exception("Firebase Admin SDK initialize nahi ho paaya — push disabled")
        _initialized = True


def send_push_to_user(user, title, body, data=None):
    """
    User ke saare registered devices ko ek push bhejo. Kisi bhi error
    (invalid token, Firebase down, credentials missing) pe silently
    log karke aage badh jaata hai — push fail hone se koi bhi REST
    request/WebSocket message fail nahi honi chahiye.
    """
    _ensure_firebase_initialized()
    if not _push_enabled:
        return

    from .models import DeviceToken

    tokens = list(
        DeviceToken.objects.filter(user=user).values_list("token", flat=True)
    )
    if not tokens:
        return

    try:
        from firebase_admin import messaging
    except Exception:
        logger.exception("firebase_admin.messaging import fail ho gaya")
        return

    str_data = {str(k): str(v) for k, v in (data or {}).items()}

    message = messaging.MulticastMessage(
        notification=messaging.Notification(title=title, body=body),
        data=str_data,
        tokens=tokens,
        android=messaging.AndroidConfig(
            priority="high",
            notification=messaging.AndroidNotification(
                channel_id="high_importance_channel",
                sound="default",
            ),
        ),
        apns=messaging.APNSConfig(
            payload=messaging.APNSPayload(
                aps=messaging.Aps(sound="default", content_available=True),
            ),
        ),
    )

    try:
        response = messaging.send_each_for_multicast(message)
    except Exception:
        logger.exception("FCM send failed for user=%s", getattr(user, "id", "?"))
        return

    # ✅ Jo tokens invalid/unregistered nikle (app uninstall ho chuki,
    # ya token rotate ho chuka) unhe cleanup kar do — warna har push pe
    # baar baar retry hoke waste hote rahenge.
    if response.failure_count:
        for idx, result in enumerate(response.responses):
            if result.success:
                continue
            err = str(result.exception)
            if any(code in err for code in (
                "NotRegistered", "InvalidRegistration",
                "UNREGISTERED", "InvalidArgument",
            )):
                DeviceToken.objects.filter(token=tokens[idx]).delete()