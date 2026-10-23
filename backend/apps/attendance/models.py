"""Attendance domain — raw events, sessions (cleanup unit), adjustments.

Schema.sql "حوزه تردد" + sections 7/8/9 + approved decisions #3 and #4 of §34:

- Out-of-range punches are KEPT and labelled «خارج محدوده»; they are not
  rejected automatically and require no manager approval.
- Offline punches older than OFFLINE_MAX_DAYS (7) become NEEDS_REVIEW; the
  effective time is confirmed by manager/HR through a TIME_FIX adjustment
  (corrections never rewrite history — section 8).
- CLOCK_SKEW flag when |device_time − server| > ±5 min (default).
"""
from __future__ import annotations

import uuid

from django.db import models

from apps.core.enums import (
    AdjustmentKind,
    Channel,
    ConnectionMode,
    EventStatus,
    EventType,
    LocationStatus,
    SegmentStatus,
    SessionState,
)
from apps.core.models import TimeStampedModel


class AttendanceEvent(TimeStampedModel):
    """Raw check-in/out event; event_uuid is the device idempotency key."""

    id = models.BigAutoField(primary_key=True)
    event_uuid = models.UUIDField(unique=True, default=uuid.uuid4, editable=False)
    employee = models.ForeignKey(
        "people.Employee", on_delete=models.PROTECT, related_name="attendance_events"
    )
    branch = models.ForeignKey(
        "orgs.Branch", on_delete=models.PROTECT, related_name="attendance_events"
    )
    event_type = models.CharField(max_length=10, choices=EventType.choices)
    device_time = models.DateTimeField()
    server_received_at = models.DateTimeField(auto_now_add=True)
    effective_time = models.DateTimeField(
        help_text="زمان مؤثر برای محاسبه و نگهداری (قواعد §۴ سند محاسبه)"
    )
    channel = models.CharField(max_length=10, choices=Channel.choices)
    connection_mode = models.CharField(
        max_length=15, choices=ConnectionMode.choices
    )
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    location_accuracy_m = models.FloatField(null=True, blank=True)
    location_fixed_at = models.DateTimeField(null=True, blank=True)
    location_status = models.CharField(
        max_length=15,
        choices=LocationStatus.choices,
        default=LocationStatus.UNAVAILABLE,
    )
    location_reason = models.CharField(max_length=40, blank=True)
    event_status = models.CharField(
        max_length=20, choices=EventStatus.choices, default=EventStatus.ACCEPTED
    )
    flags = models.JSONField(default=list, blank=True, help_text="CLOCK_SKEW / STALE_OFFLINE / …")
    local_seq = models.BigIntegerField(
        null=True, blank=True, help_text="تحلیلی؛ هرگز مبنای جفت‌سازی نیست"
    )
    app_version = models.CharField(max_length=20, blank=True)
    last_synced_device_at = models.DateTimeField(null=True, blank=True)
    client_request_id = models.CharField(max_length=64, blank=True)

    class Meta:
        db_table = "attendance_events"
        verbose_name = "رویداد تردد"
        verbose_name_plural = "رویدادهای تردد"
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(latitude__isnull=True, longitude__isnull=True)
                    | models.Q(latitude__isnull=False, longitude__isnull=False)
                ),
                name="chk_event_geo",
            ),
        ]
        indexes = [
            models.Index(fields=["employee", "effective_time"], name="idx_events_emp_eff"),
            models.Index(fields=["branch", "effective_time"], name="idx_events_branch_eff"),
            models.Index(
                fields=["branch", "effective_time"],
                condition=models.Q(event_status="NEEDS_REVIEW"),
                name="idx_events_review",
            ),
            models.Index(fields=["effective_time"], name="idx_events_purge"),
            models.Index(fields=["employee", "device_time"]),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.event_type} {self.employee_id}@{self.branch_id} {self.effective_time:%Y-%m-%d %H:%M}"


class AttendanceSession(TimeStampedModel):
    """Presence interval — the retention/purge unit (section 15)."""

    employee = models.ForeignKey(
        "people.Employee", on_delete=models.PROTECT, related_name="attendance_sessions"
    )
    branch = models.ForeignKey(
        "orgs.Branch", on_delete=models.PROTECT, related_name="attendance_sessions"
    )
    check_in_event = models.OneToOneField(
        AttendanceEvent, null=True, blank=True, on_delete=models.PROTECT,
        related_name="session_as_check_in",
    )
    check_out_event = models.OneToOneField(
        AttendanceEvent, null=True, blank=True, on_delete=models.PROTECT,
        related_name="session_as_check_out",
    )
    shift_date = models.DateField(help_text="تاریخ شروع شیفت مرجع")
    scheduled_shift = models.ForeignKey(
        "scheduling.ScheduledShift", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="sessions",
    )
    session_state = models.CharField(
        max_length=20, choices=SessionState.choices, default=SessionState.OPEN
    )
    work_minutes = models.PositiveIntegerField(null=True, blank=True)
    is_purged = models.BooleanField(default=False, help_text="بدون حذف نرم رویداد؛ فقط بازه")

    class Meta:
        db_table = "attendance_sessions"
        verbose_name = "بازه حضور"
        verbose_name_plural = "بازه‌های حضور"
        indexes = [
            models.Index(fields=["employee", "shift_date"], name="idx_sessions_emp_date"),
            models.Index(fields=["branch", "shift_date"], name="idx_sessions_branch_date"),
            models.Index(
                fields=["branch", "session_state"],
                condition=~models.Q(session_state="COMPLETE"),
                name="idx_sessions_open",
            ),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"session#{self.id} emp={self.employee_id} {self.session_state}"


class AttendanceAdjustment(TimeStampedModel):
    """Decision layer — the original event is never rewritten (section 8)."""

    session = models.ForeignKey(
        AttendanceSession, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="adjustments",
    )
    target_event = models.ForeignKey(
        AttendanceEvent, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="adjustments",
    )
    adjustment_kind = models.CharField(max_length=20, choices=AdjustmentKind.choices)
    original_value = models.JSONField()
    corrected_value = models.JSONField()
    reason = models.TextField()
    decided_by = models.ForeignKey(
        "people.User", on_delete=models.PROTECT, related_name="attendance_adjustments"
    )
    decided_at = models.DateTimeField(auto_now_add=True)
    applies_to_summary = models.ForeignKey(
        "reports.MonthlySummary", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="adjustments",
    )

    class Meta:
        db_table = "attendance_adjustments"
        verbose_name = "اصلاح تردد"
        verbose_name_plural = "اصلاحات تردد"
        indexes = [models.Index(fields=["session", "decided_at"], name="idx_adjustments_session")]

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.adjustment_kind} by {self.decided_by_id} @ {self.decided_at:%Y-%m-%d}"


class OvertimeProposal(TimeStampedModel):
    """Overtime approval unit — calculation-rules §7.3.

    Mere difference between checkout and planned_end is NOT counted
    (explicit rule of the requirements document): the engine proposes
    overtime from sessions extending beyond `planned_end`, the branch
    manager decides, and only approved minutes enter monthly summaries.
    """

    session = models.OneToOneField(
        AttendanceSession, on_delete=models.PROTECT, related_name="overtime_proposal"
    )
    employee = models.ForeignKey(
        "people.Employee", on_delete=models.PROTECT, related_name="overtime_proposals"
    )
    branch = models.ForeignKey(
        "orgs.Branch", on_delete=models.PROTECT, related_name="overtime_proposals"
    )
    shift_date = models.DateField(db_index=True)
    proposed_minutes = models.PositiveIntegerField()
    approved_minutes = models.PositiveIntegerField(null=True, blank=True)
    status = models.CharField(
        max_length=12, choices=SegmentStatus.choices, default=SegmentStatus.PENDING
    )
    basis = models.CharField(max_length=30, default="AUTO_BEYOND_PLANNED_END")
    reason = models.CharField(max_length=200, blank=True)
    decided_by = models.ForeignKey(
        "people.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="overtime_decisions"
    )
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "overtime_proposals"
        verbose_name = "پیشنهاد اضافه‌کاری"
        verbose_name_plural = "پیشنهادهای اضافه‌کاری"
        indexes = [
            models.Index(
                fields=["branch", "status"],
                condition=models.Q(status="PENDING"),
                name="idx_ot_pending",
            ),
            models.Index(fields=["employee", "shift_date"], name="idx_ot_emp_date"),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"OT#{self.id} emp={self.employee_id} {self.shift_date} {self.status}"
