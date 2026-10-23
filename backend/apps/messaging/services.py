"""Notification services — persistence + best-effort live push.

Delivery contract: a Notification row is always persisted (3-month retention,
section 12 of the document); the WebSocket push is opportunistic — recipients
without a live socket simply read decisions from the requests/approvals pages.
"""
from __future__ import annotations

from django.utils import timezone


def notify_employee(*, employee_id: int, kind: str, title: str, payload: dict | None = None) -> None:
    """Persist a Notification for the employee and push to their live socket."""
    from apps.messaging.models import Notification

    created_at = timezone.now()
    Notification.objects.create(
        recipient_id=employee_id,
        kind=kind,
        payload={"title": title, **(payload or {})},
    )

    from asgiref.sync import async_to_sync
    from channels.layers import get_channel_layer

    from apps.people.models import Employee

    # The socket group is keyed by the login account (users.id); the
    # notification belongs to the personnel file (employees.id).
    user_id = (
        Employee.objects.filter(id=employee_id)
        .values_list("user_account__id", flat=True)
        .first()
    )
    if user_id is None:
        return
    layer = get_channel_layer()
    if layer is None:
        return
    try:
        async_to_sync(layer.group_send)(
            f"user-{user_id}",
            {
                "type": "notify",
                "kind": kind,
                "title": title,
                "payload": payload or {},
                "created_at": created_at.isoformat(),
            },
        )
    except RuntimeError:
        # No running event loop in this thread (rare sync contexts) — the
        # persisted notification is enough; never break the business flow.
        pass
