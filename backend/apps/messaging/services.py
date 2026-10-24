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


def _push_to_user_groups(targets: list[int], *, kind: str, title: str,
                         payload: dict | None, created_at) -> None:
    """Best-effort group_send to user-<id> groups; never raises."""
    from asgiref.sync import async_to_sync
    from channels.layers import get_channel_layer

    layer = get_channel_layer()
    if layer is None:
        return
    for user_id in targets:
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
            # No running event loop in this thread — persistence is enough.
            pass


def push_to_employees(*, employees, kind: str, payload: dict) -> None:
    """Best-effort live push to a set of Employee files (chat transport).

    Chat messages have their own durable table; the socket is only the
    real-time transport, so unlike notify_employee no Notification row is
    written here. The push is deferred to transaction.on_commit so recipients
    never receive an event whose row could still roll back.
    """
    from django.db import transaction

    from apps.people.models import User

    employee_ids = [e.id for e in employees if e is not None]
    if not employee_ids:
        return
    user_ids = list(
        User.objects.filter(is_active=True, employee_id__in=employee_ids).values_list("id", flat=True)
    )
    if not user_ids:
        return
    created_at = timezone.now()
    transaction.on_commit(
        lambda: _push_to_user_groups(user_ids, kind=kind, title="", payload=payload, created_at=created_at)
    )


def notify_branch_managers(*, branch_id: int, kind: str, title: str,
                           payload: dict | None = None) -> None:
    """Alert the BRANCH_MANAGERs of one branch (review-flow completion).

    A Notification row is persisted per manager (messaging contract, §12) and
    the live WebSocket push is deferred to transaction.on_commit so recipients
    never see an event whose row could still roll back.
    """
    from django.db import transaction

    from apps.messaging.models import Notification
    from apps.people.models import User

    managers = list(
        User.objects.filter(
            is_active=True,
            role_assignments__branch_id=branch_id,
            role_assignments__role__code="BRANCH_MANAGER",
        )
        .exclude(employee_id=None)
        .distinct()
        .values_list("id", "employee_id")
    )
    if not managers:
        return

    created_at = timezone.now()
    for _user_id, employee_id in managers:
        Notification.objects.create(
            recipient_id=employee_id,
            kind=kind,
            payload={"title": title, **(payload or {})},
        )
    user_ids = [user_id for user_id, _employee_id in managers]
    transaction.on_commit(
        lambda: _push_to_user_groups(
            user_ids, kind=kind, title=title, payload=payload, created_at=created_at
        )
    )
