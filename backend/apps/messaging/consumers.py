"""WebSocket consumers — live notifications (messaging increment, section 21).

One connection per open tab; per-user group `user-<id>` so multi-device
sessions all receive the same decision events.
"""
from __future__ import annotations

import logging

from channels.generic.websocket import AsyncJsonWebsocketConsumer

log = logging.getLogger(__name__)


class NotificationConsumer(AsyncJsonWebsocketConsumer):
    """ws/notifications/?token=<access JWT> — authenticated push channel."""

    async def connect(self):
        user = self.scope.get("user")
        if user is None or not getattr(user, "is_authenticated", False):
            await self.close(code=4401)
            return
        self.group_name = f"user-{user.id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        group_name = getattr(self, "group_name", None)
        if group_name:
            await self.channel_layer.group_discard(group_name, self.channel_name)

    async def receive_json(self, content, **kwargs):
        # Client → server traffic is not used in this increment; keep a
        # lightweight ping/pong so the PWA can probe liveness.
        if isinstance(content, dict) and content.get("type") == "ping":
            await self.send_json({"type": "pong"})

    async def notify(self, event):
        """Handler for group sends of type "notify" (messaging.services)."""
        await self.send_json(
            {
                "type": "notification",
                "kind": event.get("kind", ""),
                "title": event.get("title", ""),
                "payload": event.get("payload", {}),
                "created_at": event.get("created_at", ""),
            }
        )
