"""Attendance API — online punch, offline sync, history, review queue.

Throttle scopes: punch (60/min), sync (20/min) per user (base settings).
"""
from __future__ import annotations

import datetime as dt

from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.enums import ConnectionMode, EventStatus
from apps.core.jalali import subtract_jalali_months
from apps.orgs.models import Branch
from apps.people.models import User

from .models import AttendanceEvent, AttendanceSession
from .services import approve_review, receive_punch


class PunchBaseSerializer(serializers.Serializer):
    event_uuid = serializers.UUIDField()
    event_type = serializers.ChoiceField(choices=AttendanceEvent._meta.get_field("event_type").choices)
    branch_code = serializers.SlugField(max_length=20)
    channel = serializers.ChoiceField(choices=AttendanceEvent._meta.get_field("channel").choices)
    device_time = serializers.DateTimeField(required=False, default=None)
    clock_offset_minutes = serializers.FloatField(required=False, allow_null=True, min_value=-10000, max_value=10000,
        help_text="افست ساعت دستگاه نسبت به سرور که اپ در لحظه ثبت اندازه‌گیری می‌کند")
    latitude = serializers.FloatField(required=False, allow_null=True, min_value=-90, max_value=90)
    longitude = serializers.FloatField(required=False, allow_null=True, min_value=-180, max_value=180)
    location_accuracy_m = serializers.FloatField(required=False, allow_null=True, min_value=0)
    location_fixed_at = serializers.DateTimeField(required=False, allow_null=True, default=None)
    local_seq = serializers.IntegerField(required=False, allow_null=True)
    app_version = serializers.CharField(required=False, allow_blank=True, max_length=20)
    client_request_id = serializers.CharField(required=False, allow_blank=True, max_length=64)

    def validate_branch_code(self, value: str) -> str:
        if not Branch.objects.filter(code=value, is_active=True).exists():
            raise serializers.ValidationError("شعبه فعال با این کد یافت نشد.")
        return value

    def _validated_punch(self) -> dict:
        data = dict(
            event_uuid=self.validated_data["event_uuid"],
            event_type=self.validated_data["event_type"],
            channel=self.validated_data["channel"],
            device_time=self.validated_data.get("device_time"),
            clock_offset_minutes=self.validated_data.get("clock_offset_minutes"),
            latitude=self.validated_data.get("latitude"),
            longitude=self.validated_data.get("longitude"),
            accuracy_m=self.validated_data.get("location_accuracy_m"),
            location_fixed_at=self.validated_data.get("location_fixed_at"),
            local_seq=self.validated_data.get("local_seq"),
            app_version=self.validated_data.get("app_version", ""),
            client_request_id=self.validated_data.get("client_request_id", ""),
        )
        data["branch"] = Branch.objects.get(code=self.validated_data["branch_code"], is_active=True)
        data["connection_mode"] = ConnectionMode.ONLINE
        return data


class OnlinePunchSerializer(PunchBaseSerializer):
    """Online punch: device_time defaults to server time when omitted."""


class SyncItemSerializer(PunchBaseSerializer):
    """Offline sync item: device_time and local_seq are required."""

    device_time = serializers.DateTimeField()
    local_seq = serializers.IntegerField(required=False, allow_null=True)


class SyncBatchSerializer(serializers.Serializer):
    events = SyncItemSerializer(many=True)

    def validate_events(self, items):
        max_batch = settings.APP_THRESHOLDS["SYNC_MAX_BATCH"]
        if not (1 <= len(items) <= max_batch):
            raise serializers.ValidationError(
                f"تعداد رویدادهای دسته باید بین ۱ و {max_batch} باشد (SYNC_MAX_BATCH)."
            )
        uuids = [i["event_uuid"] for i in items]
        if len(set(uuids)) != len(uuids):
            raise serializers.ValidationError("event_uuid تکراری در دسته مجاز نیست.")
        return items


def punch_response(event: AttendanceEvent, created: bool) -> dict:
    return {
        "event_uuid": str(event.event_uuid),
        "created": created,
        "event_status": event.event_status,
        "location_status": event.location_status,
        "location_reason": event.location_reason,
        "flags": event.flags,
        "effective_time": event.effective_time,
        "device_time": event.device_time,
        "server_received_at": event.server_received_at,
    }


class AttendanceEventViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """Employee history + online punch + offline sync + manager review."""

    permission_classes = [IsAuthenticated]
    serializer_class = OnlinePunchSerializer

    def get_throttles(self):
        if self.action in ("create_punch", "sync_batch"):
            self.throttle_scope = "punch" if self.action == "create_punch" else "sync"
        return super().get_throttles()

    def _detail_window_start(self):
        months = 3  # approved decision #2 — Jalali-based detail window
        return subtract_jalali_months(timezone.now(), months)

    @action(detail=False, methods=["post"], url_name="punch", url_path="punch")
    def create_punch(self, request):
        ser = OnlinePunchSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        event, created = receive_punch(employee=request.user.employee, **ser._validated_punch())
        return Response(punch_response(event, created))

    @action(detail=False, methods=["post"], url_name="sync", url_path="sync")
    def sync_batch(self, request):
        ser = SyncBatchSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        results = []
        for item in ser.validated_data["events"]:
            item_ser = SyncItemSerializer(data={**item})
            item_ser.is_valid(raise_exception=True)
            payload = item_ser._validated_punch()
            payload["connection_mode"] = ConnectionMode.OFFLINE_SYNC
            event, created = receive_punch(employee=request.user.employee, **payload)
            results.append(punch_response(event, created))
        return Response(
            {
                "processed": len(results),
                "needs_review": sum(1 for r in results if r["event_status"] == EventStatus.NEEDS_REVIEW),
                "results": results,
            }
        )

    def get_queryset(self):
        user: User = self.request.user
        qs = AttendanceEvent.objects.select_related("branch")
        if self.action in ("list", "retrieve"):
            return qs.filter(employee=user.employee)
        return qs

    def list(self, request, *args, **kwargs):
        qs = self.get_queryset().filter(effective_time__gte=self._detail_window_start())
        page = self.paginate_queryset(qs.order_by("-effective_time"))
        data = [
            {
                "event_uuid": str(e.event_uuid),
                "event_type": e.event_type,
                "branch": e.branch.code,
                "device_time": e.device_time,
                "effective_time": e.effective_time,
                "connection_mode": e.connection_mode,
                "location_status": e.location_status,
                "location_reason": e.location_reason,
                "event_status": e.event_status,
                "flags": e.flags,
            }
            for e in page
        ]
        return self.get_paginated_response(data)


class AttendanceSessionViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return (
            AttendanceSession.objects.filter(employee=self.request.user.employee)
            .select_related("check_in_event", "check_out_event", "branch")
        )

    def list(self, request, *args, **kwargs):
        start = subtract_jalali_months(timezone.now(), 3)
        qs = (
            self.get_queryset()
            .filter(
                Q(check_in_event__effective_time__gte=start)
                | Q(check_out_event__effective_time__gte=start)
            )
            .order_by("-shift_date")
        )
        page = self.paginate_queryset(qs)
        data = [
            {
                "id": s.id,
                "branch": s.branch.code,
                "shift_date": s.shift_date,
                "session_state": s.session_state,
                "work_minutes": s.work_minutes,
                "check_in_at": s.check_in_event.effective_time if s.check_in_event else None,
                "check_out_at": s.check_out_event.effective_time if s.check_out_event else None,
                "scheduled_shift_id": s.scheduled_shift_id,
            }
            for s in page
        ]
        return self.get_paginated_response(data)


class ReviewQueueViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """NEEDS_REVIEW queue for branch managers / HR (approved decision #4)."""

    permission_classes = [IsAuthenticated]
    throttle_scope = "punch"

    REVIEWER_ROLES = ("BRANCH_MANAGER", "REGION_MANAGER", "HR", "ADMIN")

    def get_queryset(self):
        user: User = self.request.user
        if user.is_superuser or user.has_role("HR") or user.has_role("ADMIN") or user.has_role("REGION_MANAGER"):
            return AttendanceEvent.objects.filter(event_status=EventStatus.NEEDS_REVIEW)
        branch_ids = list(
            user.role_assignments.filter(role__code="BRANCH_MANAGER").values_list("branch_id", flat=True)
        )
        return AttendanceEvent.objects.filter(
            event_status=EventStatus.NEEDS_REVIEW, branch_id__in=branch_ids
        )

    def list(self, request, *args, **kwargs):
        qs = self.get_queryset().select_related("branch", "employee").order_by("effective_time")
        page = self.paginate_queryset(qs)
        data = [
            {
                "event_uuid": str(e.event_uuid),
                "employee": {
                    "id": e.employee_id,
                    "personnel_code": e.employee.personnel_code,
                    "full_name": e.employee.full_name,
                },
                "branch": e.branch.code,
                "event_type": e.event_type,
                "device_time": e.device_time,
                "effective_time": e.effective_time,
                "flags": e.flags,
                "location_status": e.location_status,
                "connection_mode": e.connection_mode,
            }
            for e in page
        ]
        return self.get_paginated_response(data)

    @action(detail=False, methods=["post"], url_path="approve")
    def approve(self, request):
        """POST {event_uuid, corrected_time, reason} — TIME_FIX decision layer."""
        user: User = request.user
        if not (
            user.is_superuser
            or any(user.has_role(r) for r in self.REVIEWER_ROLES)
        ):
            return Response({"detail": "دسترسی رسیدگی ندارید.", "code": "FORBIDDEN"},
                            status=403)
        event_uuid = request.data.get("event_uuid")
        corrected = request.data.get("corrected_time")
        reason = request.data.get("reason", "")
        if not event_uuid or not corrected:
            return Response(
                {"detail": "event_uuid و corrected_time الزامی است.", "code": "INVALID"},
                status=400,
            )
        try:
            event = self.get_queryset().get(event_uuid=event_uuid)
        except AttendanceEvent.DoesNotExist:
            return Response({"detail": "رویداد یافت نشد.", "code": "NOT_FOUND"}, status=404)
        try:
            corrected_dt = dt.datetime.fromisoformat(corrected)
        except ValueError:
            return Response({"detail": "corrected_time نامعتبر است.", "code": "INVALID"}, status=400)
        if timezone.is_naive(corrected_dt):
            corrected_dt = timezone.make_aware(corrected_dt)
        event = approve_review(event=event, decided_by=user, corrected_time=corrected_dt, reason=reason)
        return Response(punch_response(event, created=False))
