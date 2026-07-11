import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone

from .models import Conversation, Message, User, Block


# ─────────────────────────────────────────
# CHAT CONSUMER
# ─────────────────────────────────────────

class ChatConsumer(AsyncWebsocketConsumer):
    """
    WebSocket endpoint: ws://domain/ws/chat/<conv_id>/
    Flutter app se connect karne ke liye JWT token header mein bhejo.

    Flow:
        1. connect()   — auth check, room group join
        2. receive()   — message receive, DB save, broadcast
        3. disconnect()— room group leave
    """

    async def connect(self):
        self.conv_id   = self.scope["url_route"]["kwargs"]["conv_id"]
        self.room_name = f"chat_{self.conv_id}"
        self.user      = self.scope.get("user")

        # Auth check
        if not self.user or not self.user.is_authenticated:
            await self.close(code=4001)
            return

        # Conversation exist + permission check
        self.conversation = await self.get_conversation(self.conv_id)
        if not self.conversation:
            await self.close(code=4004)
            return

        allowed = await self.is_participant(self.user, self.conversation)
        if not allowed:
            await self.close(code=4003)
            return

        # Channel layer room mein join karo
        await self.channel_layer.group_add(self.room_name, self.channel_name)
        await self.accept()

        # Online status broadcast karo
        await self.channel_layer.group_send(
            self.room_name,
            {
                "type":    "user_status",
                "user_id": str(self.user.id),
                "status":  "online",
            }
        )

    async def disconnect(self, close_code):
        if hasattr(self, "room_name"):
            # Offline status broadcast karo
            await self.channel_layer.group_send(
                self.room_name,
                {
                    "type":    "user_status",
                    "user_id": str(self.user.id),
                    "status":  "offline",
                }
            )
            await self.channel_layer.group_discard(self.room_name, self.channel_name)

    async def receive(self, text_data):
        """Flutter se message aata hai yahan"""
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            await self.send_error("Invalid JSON")
            return

        msg_type = data.get("type", "message")

        if msg_type == "message":
            await self.handle_message(data)

        elif msg_type == "typing":
            await self.handle_typing(data)

        elif msg_type == "read":
            await self.handle_read(data)

        else:
            await self.send_error(f"Unknown type: {msg_type}")

    # ─────────────────────────────────────
    # HANDLERS
    # ─────────────────────────────────────

    async def handle_message(self, data):
        text = data.get("text", "").strip()
        # ✅ client_id: Flutter side jo optimistic (turant dikhaya gaya)
        # message banata hai uska local ID — hum bas echo karte hain taaki
        # client apne "sending..." message ko is confirmed message se
        # replace kar sake (WhatsApp jaisa: turant dikhta hai, phir tick).
        client_id = data.get("client_id")
        if not text:
            await self.send_error("Empty message")
            return

        # Block check
        other = await self.get_other_user(self.user, self.conversation)
        if await self.is_blocked(self.user, other):
            await self.send_error("Cannot send message")
            return

        # DB mein save karo
        message = await self.save_message(self.conversation, self.user, text)

        # Dono users ko broadcast karo
        await self.channel_layer.group_send(
            self.room_name,
            {
                "type":       "chat_message",
                "id":         message.id,
                "sender_id":  str(self.user.id),
                "text":       text,
                "created_at": message.created_at.isoformat(),
                "client_id":  client_id,
            }
        )

    async def handle_typing(self, data):
        """Typing indicator — DB mein save nahi hota"""
        await self.channel_layer.group_send(
            self.room_name,
            {
                "type":      "typing_indicator",
                "user_id":   str(self.user.id),
                "is_typing": data.get("is_typing", False),
            }
        )

    async def handle_read(self, data):
        """Messages read acknowledge karo"""
        await self.mark_messages_read(self.conversation, self.user)
        await self.channel_layer.group_send(
            self.room_name,
            {
                "type":    "messages_read",
                "user_id": str(self.user.id),
            }
        )

    # ─────────────────────────────────────
    # GROUP EVENT HANDLERS
    # (channel layer se aane wale events)
    # ─────────────────────────────────────

    async def chat_message(self, event):
        """Message Flutter ko bhejo"""
        await self.send(text_data=json.dumps({
            "type":       "message",
            "id":         event["id"],
            "sender_id":  event["sender_id"],
            "text":       event["text"],
            "created_at": event["created_at"],
            "client_id":  event.get("client_id"),
        }))

    async def typing_indicator(self, event):
        """Typing status Flutter ko bhejo"""
        if str(self.user.id) != event["user_id"]:  # apne aap ko mat bhejo
            await self.send(text_data=json.dumps({
                "type":      "typing",
                "user_id":   event["user_id"],
                "is_typing": event["is_typing"],
            }))

    async def messages_read(self, event):
        """Read receipt Flutter ko bhejo"""
        if str(self.user.id) != event["user_id"]:
            await self.send(text_data=json.dumps({
                "type":    "read",
                "user_id": event["user_id"],
            }))

    async def user_status(self, event):
        """Online/offline status Flutter ko bhejo"""
        if str(self.user.id) != event["user_id"]:
            await self.send(text_data=json.dumps({
                "type":    "status",
                "user_id": event["user_id"],
                "status":  event["status"],
            }))

    # ─────────────────────────────────────
    # HELPERS
    # ─────────────────────────────────────

    async def send_error(self, message):
        await self.send(text_data=json.dumps({
            "type":  "error",
            "error": message,
        }))

    # ─────────────────────────────────────
    # DB OPERATIONS (sync → async)
    # ─────────────────────────────────────

    @database_sync_to_async
    def get_conversation(self, conv_id):
        try:
            return Conversation.objects.select_related(
                "match__user1", "match__user2"
            ).get(id=conv_id)
        except Conversation.DoesNotExist:
            return None

    @database_sync_to_async
    def is_participant(self, user, conversation):
        match = conversation.match
        return user in [match.user1, match.user2]

    @database_sync_to_async
    def get_other_user(self, user, conversation):
        match = conversation.match
        return match.user2 if match.user1 == user else match.user1

    @database_sync_to_async
    def is_blocked(self, sender, receiver):
        return Block.objects.filter(
            blocker=sender, blocked=receiver
        ).exists()

    @database_sync_to_async
    def save_message(self, conversation, sender, text):
        return Message.objects.create(
            conversation=conversation,
            sender=sender,
            text=text,
        )

    @database_sync_to_async
    def mark_messages_read(self, conversation, user):
        Message.objects.filter(
            conversation=conversation,
            is_read=False,
        ).exclude(sender=user).update(is_read=True)