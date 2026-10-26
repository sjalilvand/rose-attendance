"""WebSocket URL routing (messaging increment)."""
from django.urls import path

from apps.messaging.consumers import NotificationConsumer

websocket_urlpatterns = [
    path("ws/notifications/", NotificationConsumer.as_asgi()),
]
