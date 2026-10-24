"""Messaging REST API — direct conversations, chat messages, notifications.

Contract (§12 messaging increment, v1):
- Partners are constrained by role: employees may chat with their home-branch
  managers plus HR/ADMIN; branch managers with their staff plus HR/ADMIN and
  region managers; HR/ADMIN/REGION_MANAGER (and superuser) with everyone.
- Messages are durable rows (3-month retention); the WebSocket is only the
  opportunistic real-time transport (kind MESSAGE_NEW / MESSAGE_READ).
- Fetching a thread marks the other side's messages delivered AND read — the
  unread badge counts messages not yet seen in the thread view.
- client_message_uuid makes offline re-sends idempotent (schema section 12).
"""
from __future__ import annotations

from django.db.models import Q
from django.utils import timezone
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.enums import EmploymentStatus
from apps.core.rbac import GLOBAL_ROLES
from apps.people.models import Employee, User

from .models import Conversation, ConversationParticipant, Message, Notification

MAX_BODY = 4000
THREAD_PAGE = 200
PREVIEW = 120


def _employee_or_none(user: User) -> Employee | None:
    return user.employee if user.employee_id else None


def _require_employee(user: User) -> tuple[Employee | None, Response | None]:
    employee = _employee_or_none(user)
    if employee is None:
        return None, Response(
            {"detail": "حساب شما به پروندهٔ پرسنلی متصل نیست؛ پیام‌رسانی فقط برای پرسنل است.", "code": "NO_EMPLOYEE"},
            status=status.HTTP_403_FORBIDDEN,
        )
    return employee, None


def allowed_partners(user: User):
    """Employees the current user may open a conversation with."""
    me = user.employee
    roles = set(user.active_role_codes()) | ({"ADMIN"} if user.is_superuser else set())
    base = (
        Employee.objects.filter(
            employment_status=EmploymentStatus.ACTIVE,
            user_account__isnull=False,
        )
        .exclude(pk=me.pk)
        .select_related("home_branch", "user_account")
    )
    if user.is_superuser or roles & set(GLOBAL_ROLES):
        return base.order_by("personnel_code")
    if "BRANCH_MANAGER" in roles:
        branch_ids = list(
            user.role_assignments.filter(role__code="BRANCH_MANAGER").values_list("branch_id", flat=True)
        )
        staff = base.filter(home_branch_id__in=branch_ids)
        # HR / ADMIN / REGION_MANAGER keep global role assignments (branch=NULL)
        bosses = base.filter(
            user_account__is_active=True,
            user_account__role_assignments__role__code__in=("HR", "ADMIN", "REGION_MANAGER"),
        )
        return (staff | bosses).distinct().order_by("personnel_code")
    # plain EMPLOYEE / AUDITOR: own home-branch managers + global roles
    managers = base.filter(
        home_branch_id=me.home_branch_id,
        user_account__is_active=True,
        user_account__role_assignments__role__code="BRANCH_MANAGER",
        user_account__role_assignments__branch_id=me.home_branch_id,
    )
    global_roles = base.filter(
        user_account__is_active=True,
        user_account__role_assignments__role__code__in=("HR", "ADMIN"),
    )
    return (managers | global_roles).distinct().order_by("personnel_code")


def _partner_of(conversation: Conversation, me: Employee) -> Employee | None:
    participant = (
        conversation.participants.exclude(employee_id=me.id)
        .select_related("employee__home_branch")
        .first()
    )
    return participant.employee if participant else None


def _serialize_message(message: Message, me: Employee) -> dict:
    return {
        "id": message.id,
        "body": message.body,
        "sender_id": message.sender_id,
        "mine": message.sender_id == me.id,
        "created_at": message.created_at.isoformat(),
        "read_at": message.read_at.isoformat() if message.read_at else None,
    }


def _serialize_conversation(conversation: Conversation, me: Employee) -> dict:
    partner = _partner_of(conversation, me)
    last = conversation.messages.order_by("-created_at").first()
    unread = conversation.messages.filter(read_at__isnull=True).exclude(sender_id=me.id).count()
    return {
        "id": conversation.id,
        "kind": conversation.kind,
        "partner": (
            {
                "id": partner.id,
                "personnel_code": partner.personnel_code,
                "full_name": partner.full_name,
                "branch_name": partner.home_branch.name if partner.home_branch_id else "",
            }
            if partner is not None
            else None
        ),
        "last_message": (
            {
                "body": last.body[:PREVIEW],
                "sender_id": last.sender_id,
                "mine": last.sender_id == me.id,
                "created_at": last.created_at.isoformat(),
            }
            if last is not None
            else None
        ),
        "unread_count": unread,
    }


def _participant_or_none(conversation_id: int, me: Employee) -> Conversation | None:
    return (
        Conversation.objects.filter(
            id=conversation_id, participants__employee_id=me.id
        )
        .distinct()
        .first()
    )


def _mark_seen(conversation: Conversation, me: Employee) -> None:
    """Peer messages become delivered+read when the thread is fetched."""
    updated = (
        Message.objects.filter(conversation=conversation, read_at__isnull=True)
        .exclude(sender_id=me.id)
        .update(read_at=timezone.now(), delivered_at=timezone.now())
    )
    if updated:
        from .services import push_to_employees

        partner = _partner_of(conversation, me)
        push_to_employees(
            employees=[partner] if partner is not None else [],
            kind="MESSAGE_READ",
            payload={"conversation_id": conversation.id},
        )


class MessagePartnerViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """GET /api/v1/messages/partners/ — who I may chat with."""

    permission_classes = [IsAuthenticated]

    def list(self, request, *args, **kwargs):
        me, blocked = _require_employee(request.user)
        if blocked:
            return blocked
        rows = [
            {
                "id": emp.id,
                "personnel_code": emp.personnel_code,
                "full_name": emp.full_name,
                "job_title": emp.job_title,
                "branch_name": emp.home_branch.name if emp.home_branch_id else "",
            }
            for emp in allowed_partners(request.user)[:500]
        ]
        return Response({"count": len(rows), "results": rows})


class ConversationViewSet(
    mixins.ListModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet
):
    """Conversations + thread fetch + send (idempotent by client uuid)."""

    permission_classes = [IsAuthenticated]

    class PartnerInSerializer(serializers.Serializer):
        partner_id = serializers.IntegerField(min_value=1)

    class SendInSerializer(serializers.Serializer):
        body = serializers.CharField(max_length=MAX_BODY, trim_whitespace=True)
        client_uuid = serializers.UUIDField(required=False, allow_null=True, default=None)

    def list(self, request, *args, **kwargs):
        me, blocked = _require_employee(request.user)
        if blocked:
            return blocked
        conversations = (
            Conversation.objects.filter(participants__employee_id=me.id)
            .prefetch_related("participants__employee__home_branch")
            .distinct()
        )
        items = [_serialize_conversation(conv, me) for conv in conversations]
        # newest activity first; brand-new (empty) conversations last
        items.sort(
            key=lambda item: item["last_message"]["created_at"] if item["last_message"] else "",
            reverse=True,
        )
        return Response({"count": len(items), "results": items[:200]})

    def create(self, request, *args, **kwargs):
        me, blocked = _require_employee(request.user)
        if blocked:
            return blocked
        ser = self.PartnerInSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        partner = Employee.objects.filter(id=ser.validated_data["partner_id"]).first()
        if partner is None or partner not in allowed_partners(request.user):
            return Response(
                {"detail": "گفتگو با این پرسنل برای شما مجاز نیست.", "code": "FORBIDDEN_PARTNER"},
                status=status.HTTP_403_FORBIDDEN,
            )
        mine = ConversationParticipant.objects.filter(employee_id=me.id).values("conversation_id")
        theirs = ConversationParticipant.objects.filter(
            employee_id=partner.id, conversation_id__in=mine
        ).values("conversation_id")
        conversation = Conversation.objects.filter(kind="DIRECT", id__in=theirs).first()
        if conversation is None:
            conversation = Conversation.objects.create(kind="DIRECT")
            ConversationParticipant.objects.create(conversation=conversation, employee=me)
            ConversationParticipant.objects.create(conversation=conversation, employee=partner)
            conversation = Conversation.objects.get(pk=conversation.pk)
        return Response(_serialize_conversation(conversation, me), status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"], url_path="messages")
    def thread(self, request, pk=None):
        me, blocked = _require_employee(request.user)
        if blocked:
            return blocked
        conversation = _participant_or_none(int(pk), me)
        if conversation is None:
            return Response({"detail": "گفتگو یافت نشد.", "code": "NOT_FOUND"}, status=404)
        rows = list(
            conversation.messages.select_related("sender").order_by("-created_at")[:THREAD_PAGE]
        )
        rows.reverse()
        _mark_seen(conversation, me)
        return Response(
            {
                "conversation": _serialize_conversation(conversation, me),
                "results": [_serialize_message(m, me) for m in rows],
            }
        )

    @action(detail=True, methods=["post"], url_path="send")
    def send(self, request, pk=None):
        me, blocked = _require_employee(request.user)
        if blocked:
            return blocked
        conversation = _participant_or_none(int(pk), me)
        if conversation is None:
            return Response({"detail": "گفتگو یافت نشد.", "code": "NOT_FOUND"}, status=404)
        ser = self.SendInSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        body = ser.validated_data["body"].strip()
        if not body:
            return Response({"detail": "متن پیام خالی است.", "code": "INVALID"}, status=400)
        client_uuid = ser.validated_data.get("client_uuid")
        if client_uuid:
            existing = Message.objects.filter(
                conversation=conversation,
                client_message_uuid=client_uuid,
                sender_id=me.id,
            ).first()
            if existing is not None:
                return Response(_serialize_message(existing, me), status=200)
        create_kwargs: dict = {}
        if client_uuid:
            create_kwargs["client_message_uuid"] = client_uuid
        message = Message.objects.create(
            conversation=conversation,
            sender=me,
            body=body,
            **create_kwargs,
        )
        from .services import push_to_employees

        others = [
            p.employee
            for p in conversation.participants.exclude(employee_id=me.id)
            .select_related("employee")
        ]
        push_to_employees(
            employees=others,
            kind="MESSAGE_NEW",
            payload={
                "conversation_id": conversation.id,
                "message_id": message.id,
                "sender_id": me.id,
                "sender_name": me.full_name,
                "body": body[:PREVIEW],
                "created_at": message.created_at.isoformat(),
            },
        )
        return Response(_serialize_message(message, me), status=201)


class NotificationViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """GET /api/v1/messages/notifications/ + read-all + unread badge."""

    permission_classes = [IsAuthenticated]

    def list(self, request, *args, **kwargs):
        me, blocked = _require_employee(request.user)
        if blocked:
            return blocked
        rows = Notification.objects.filter(recipient_id=me.id).order_by("-created_at")[:100]
        unread = Notification.objects.filter(recipient_id=me.id, read_at__isnull=True).count()
        return Response(
            {
                "count": len(rows),
                "unread": unread,
                "results": [
                    {
                        "id": n.id,
                        "kind": n.kind,
                        "title": n.payload.get("title", ""),
                        "payload": n.payload,
                        "read": n.read_at is not None,
                        "created_at": n.created_at.isoformat(),
                    }
                    for n in rows
                ],
            }
        )

    @action(detail=False, methods=["post"], url_path="read-all")
    def read_all(self, request):
        me, blocked = _require_employee(request.user)
        if blocked:
            return blocked
        updated = Notification.objects.filter(
            recipient_id=me.id, read_at__isnull=True
        ).update(read_at=timezone.now())
        return Response({"marked": updated})

    @action(detail=False, methods=["get"], url_path="unread")
    def unread(self, request):
        """Badge totals for the navigation bar: {messages, notifications}."""
        me, blocked = _require_employee(request.user)
        if blocked:
            return blocked
        messages = (
            Message.objects.filter(
                conversation__participants__employee_id=me.id, read_at__isnull=True
            )
            .exclude(sender_id=me.id)
            .count()
        )
        notifications = Notification.objects.filter(
            recipient_id=me.id, read_at__isnull=True
        ).count()
        return Response({"messages": messages, "notifications": notifications})
