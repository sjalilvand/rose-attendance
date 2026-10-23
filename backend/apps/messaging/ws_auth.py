"""JWT query-string auth for the WebSocket protocol layer.

The browser WebSocket API cannot send an Authorization header, so the PWA
passes its access token as ?token=... The middleware validates signature,
expiry and token type, then resolves scope["user"]. A missing/invalid token
yields AnonymousUser; the consumer closes such connections with code 4401.
"""
from __future__ import annotations

from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.settings import api_settings as jwt_settings
from rest_framework_simplejwt.tokens import UntypedToken


@database_sync_to_async
def _user_from_payload(user_id):
    from apps.people.models import User

    try:
        return User.objects.get(pk=user_id, is_active=True)
    except (User.DoesNotExist, ValueError, TypeError):
        return AnonymousUser()


class JWTQueryAuthMiddleware(BaseMiddleware):
    """scope["user"] from ?token=<access JWT>; anything else → AnonymousUser."""

    async def __call__(self, scope, receive, send):
        scope = dict(scope)
        scope["user"] = AnonymousUser()
        raw_query = scope.get("query_string") or b""
        query = parse_qs(raw_query.decode("utf-8", errors="ignore"))
        tokens = query.get("token") or []
        if tokens:
            try:
                validated = UntypedToken(tokens[0])
                # Only access tokens may open a socket (not refresh tokens).
                if validated.payload.get("token_type") != "access":
                    raise TokenError("wrong token type")
                user_id = validated.payload.get(jwt_settings.USER_ID_CLAIM)
                if user_id is not None:
                    scope["user"] = await _user_from_payload(user_id)
            except (TokenError, Exception):  # noqa: BLE001 — malformed strings etc.
                pass
        return await super().__call__(scope, receive, send)
