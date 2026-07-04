"""
ASGI config for dating_backend project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.1/howto/deployment/asgi/

✅ FIX: Pehle yahan sirf `get_asgi_application()` tha — WebSocket route
(channels) bilkul configure hi nahi thi is file mein, aur agar kahin
AuthMiddlewareStack use bhi ho raha tha, toh woh sirf Django SESSION
COOKIE se authenticate karta hai. Lekin Flutter app WebSocket connect
karte waqt session cookie nahi bhejta — woh JWT access token bhejta hai
query param mein:

    wss://.../ws/chat/<conv_id>/?token=<access_token>

Isliye consumers.py mein `self.scope["user"]` hamesha AnonymousUser ban
jaata tha, aur ChatConsumer.connect() turant close(code=4001) kar deta
tha. Result: WebSocket kabhi connect hi nahi hota tha, app hamesha REST
fallback mode mein chala jaata, aur naye messages dekhne ke liye
baar-baar manually refresh karna padta tha.

Neeche ka JWTAuthMiddleware query string se token nikaal kar SimpleJWT se
verify karta hai aur scope["user"] set karta hai — ab consumer.connect()
sahi se authenticate hoga aur real-time messages/typing/read-receipts
turant Flutter app mein aa jayenge, refresh ki zaroorat nahi padegi.
"""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dating_backend.settings")

import django
django.setup()

from urllib.parse import parse_qs

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.db import database_sync_to_async
from django.core.asgi import get_asgi_application
from django.contrib.auth.models import AnonymousUser

from rest_framework_simplejwt.tokens import AccessToken
from rest_framework_simplejwt.exceptions import TokenError

from api import routing as api_routing


class JWTAuthMiddleware:
    """
    Channels ASGI middleware — WebSocket connect request ke query string
    (?token=...) se JWT access token nikaal kar verify karta hai aur
    scope['user'] set karta hai. Agar token missing/invalid/expired ho,
    toh scope['user'] = AnonymousUser() rehta hai (consumer khud close
    kar dega with code 4001).
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        scope["user"] = await self._get_user_from_scope(scope)
        return await self.app(scope, receive, send)

    async def _get_user_from_scope(self, scope):
        query_string = scope.get("query_string", b"").decode()
        token = parse_qs(query_string).get("token", [None])[0]
        if not token:
            return AnonymousUser()
        return await self._get_user(token)

    @database_sync_to_async
    def _get_user(self, token):
        from api.models import User
        try:
            access = AccessToken(token)          # verifies signature + expiry
            user_id = access["user_id"]
            return User.objects.get(id=user_id)
        except (TokenError, User.DoesNotExist, KeyError):
            return AnonymousUser()


django_asgi_app = get_asgi_application()

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": JWTAuthMiddleware(
        URLRouter(api_routing.websocket_urlpatterns)
    ),
})