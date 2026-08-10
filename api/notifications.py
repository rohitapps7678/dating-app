"""
Notification triggers — REST view aur WebSocket consumer, dono jagah se
call hote hain (ek hi jagah logic, taaki REST-sent message aur
WebSocket-sent message dono ke liye notification/push identical rahe).

Har function do kaam karta hai:
  1. Ek `Notification` row banata hai (Notification screen isi se
     populate hoti hai — app khol ke bhi purani notifications dikhengi).
  2. `send_push_to_user()` call karke real FCM push bhejta hai (phone
     ki notification tray mein — chahe app band ho).
"""

import logging

from .models import Notification
from .push import send_push_to_user

logger = logging.getLogger(__name__)


def _display_name(user):
    try:
        return user.profile.name or "Someone"
    except Exception:
        return "Someone"


def _display_photo(user):
    try:
        return user.profile.photo_url
    except Exception:
        return None


def notify_new_message(message):
    """
    Ek naya Message DB mein save hone ke turant baad call karo — REST
    (`MessageListView.post`) aur WebSocket (`ChatConsumer.handle_message`)
    dono se. Sirf RECEIVER ko notify karta hai, sender ko nahi.
    """
    try:
        conversation = message.conversation
        match        = conversation.match
        recipient    = match.user2 if match.user1_id == message.sender_id else match.user1
        sender_name  = _display_name(message.sender)

        body = message.text
        if len(body) > 100:
            body = body[:97] + "..."

        Notification.objects.create(
            recipient=recipient,
            actor=message.sender,
            type="message",
            title=sender_name,
            body=body,
            conversation=conversation,
        )
        send_push_to_user(
            recipient,
            title=sender_name,
            body=body,
            data={
                "type":            "message",
                "conversation_id": conversation.id,
            },
        )
    except Exception:
        # ✅ Notification/push fail hone se asli message-send flow kabhi
        # fail nahi hona chahiye — sirf log karke aage badho.
        logger.exception("notify_new_message failed for message_id=%s", getattr(message, "id", "?"))


def notify_new_match(match):
    """Naya mutual match banne ke turant baad call karo — dono users ko
    notify karta hai (ek dusre ke liye "actor")."""
    try:
        conv_id = match.conversation.id if hasattr(match, "conversation") else None
        pairs   = [(match.user1, match.user2), (match.user2, match.user1)]
        for recipient, other in pairs:
            other_name = _display_name(other)
            title = "New Match! 🎉"
            body  = f"You and {other_name} liked each other"

            Notification.objects.create(
                recipient=recipient,
                actor=other,
                type="match",
                title=title,
                body=body,
                match=match,
            )
            send_push_to_user(
                recipient,
                title=title,
                body=body,
                data={
                    "type":            "match",
                    "conversation_id": conv_id or "",
                },
            )
    except Exception:
        logger.exception("notify_new_match failed for match_id=%s", getattr(match, "id", "?"))