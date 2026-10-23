"""Requests domain — leave/mission requests, multi-branch segments, ledger.

Schema.sql "حوزه درخواست‌ها" + section 11 + approved decision #5: multi-branch
requests split into per-(branch, shift) segments decided independently; the
overall status is a composition of segments, never a re-computation of times.
"""
from __future__ import annotations

from django.db import models

from apps.core.enums import (
    ApprovalAction,
    LeaveEntryKind,
    RequestStatus,
    SegmentStatus,
)
from apps.core.models import TimeStampedModel


class LeaveType(models.Model):
    code = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=120)
    is_hourly = models.BooleanField(default=False)
    is_paid = models.BooleanField(default=True)
    requires_attachment = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "leave_types"
        verbose_name = "نوع مرخصی"
        verbose_name_plural = "انواع مرخصی"

    def __str__(self) -> str:  # pragma: no cover
        return self.code


class LeaveRequest(TimeStampedModel):
    employee = models.ForeignKey(
        "people.Employee", on_delete=models.PROTECT, related_name="leave_requests"
    )
    leave_type = models.ForeignKey(LeaveType, on_delete=models.PROTECT, related_name="requests")
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    computed_minutes = models.PositiveIntegerField(default=0)
    description = models.TextField(blank=True)
    attachment_file_id = models.BigIntegerField(null=True, blank=True)
    overall_status = models.CharField(
        max_length=12, choices=RequestStatus.choices, default=RequestStatus.DRAFT
    )

    class Meta:
        db_table = "leave_requests"
        verbose_name = "درخواست مرخصی"
        verbose_name_plural = "درخواست‌های مرخصی"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(ends_at__gt=models.F("starts_at")), name="chk_leave_period"
            ),
            models.CheckConstraint(
                condition=models.Q(computed_minutes__gte=0), name="chk_leave_minutes"
            ),
        ]
        indexes = [
            models.Index(fields=["overall_status", "starts_at"], name="idx_leave_requests_status_date"),
            models.Index(fields=["employee", "starts_at"], name="idx_leave_requests_employee"),
        ]


class MissionRequest(TimeStampedModel):
    employee = models.ForeignKey(
        "people.Employee", on_delete=models.PROTECT, related_name="mission_requests"
    )
    destination_branch = models.ForeignKey(
        "orgs.Branch", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    destination_text = models.CharField(max_length=200, blank=True)
    subject = models.CharField(max_length=200)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    computed_minutes = models.PositiveIntegerField(default=0)
    overall_status = models.CharField(
        max_length=12, choices=RequestStatus.choices, default=RequestStatus.DRAFT
    )
    end_report = models.TextField(blank=True)

    class Meta:
        db_table = "mission_requests"
        verbose_name = "مأموریت"
        verbose_name_plural = "مأموریت‌ها"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(ends_at__gt=models.F("starts_at")), name="chk_mission_period"
            ),
        ]


class RequestSegment(TimeStampedModel):
    """Independent (branch × interval) decision unit — approved decision #5."""

    request_kind = models.CharField(max_length=10)  # LEAVE / MISSION
    leave_request = models.ForeignKey(
        LeaveRequest, null=True, blank=True, on_delete=models.CASCADE, related_name="segments"
    )
    mission_request = models.ForeignKey(
        MissionRequest, null=True, blank=True, on_delete=models.CASCADE, related_name="segments"
    )
    branch = models.ForeignKey("orgs.Branch", on_delete=models.PROTECT, related_name="+")
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    scheduled_shift = models.ForeignKey(
        "scheduling.ScheduledShift", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    computed_minutes = models.PositiveIntegerField(default=0)
    segment_status = models.CharField(
        max_length=12, choices=SegmentStatus.choices, default=SegmentStatus.PENDING
    )

    class Meta:
        db_table = "request_segments"
        verbose_name = "بخش درخواست"
        verbose_name_plural = "بخش‌های درخواست"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(ends_at__gt=models.F("starts_at")), name="chk_segment_period"
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(request_kind="LEAVE", leave_request__isnull=False, mission_request__isnull=True)
                    | models.Q(request_kind="MISSION", mission_request__isnull=False, leave_request__isnull=True)
                ),
                name="chk_segment_source",
            ),
            # Partial uniques — NULL-distinct semantics of plain UNIQUE avoided
            models.UniqueConstraint(
                fields=["leave_request", "branch", "starts_at"],
                condition=models.Q(request_kind="LEAVE"),
                name="uq_segment_leave",
            ),
            models.UniqueConstraint(
                fields=["mission_request", "branch", "starts_at"],
                condition=models.Q(request_kind="MISSION"),
                name="uq_segment_mission",
            ),
        ]
        indexes = [
            models.Index(
                fields=["branch", "segment_status"],
                condition=models.Q(segment_status="PENDING"),
                name="idx_segments_pending",
            ),
        ]


class ApprovalAction(models.Model):
    segment = models.ForeignKey(RequestSegment, on_delete=models.CASCADE, related_name="actions")
    action = models.CharField(max_length=10, choices=ApprovalAction.choices)
    decided_by = models.ForeignKey(
        "people.User", on_delete=models.PROTECT, related_name="segment_decisions",
        db_column="decided_by_user_id",
    )
    on_behalf_of = models.ForeignKey(
        "people.Employee", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+", db_column="on_behalf_of_employee_id",
        help_text="ثبت جانشین‌گری",
    )
    comment = models.TextField(blank=True)
    decided_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "approval_actions"
        verbose_name = "تصمیم درخواست"
        verbose_name_plural = "تصمیمات درخواست‌ها"
        indexes = [models.Index(fields=["segment", "decided_at"], name="idx_approval_segment")]


class LeaveLedger(models.Model):
    """Immutable balance stream — no soft deletes, transactional (section 11)."""

    employee = models.ForeignKey("people.Employee", on_delete=models.PROTECT, related_name="ledger")
    leave_type = models.ForeignKey(LeaveType, on_delete=models.PROTECT, related_name="ledger")
    entry_kind = models.CharField(max_length=12, choices=LeaveEntryKind.choices)
    minutes = models.IntegerField()
    balance_after_minutes = models.IntegerField()
    basis_date = models.DateField()
    source_type = models.CharField(max_length=30, blank=True)
    source_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "leave_ledger"
        verbose_name = "گردش مانده مرخصی"
        verbose_name_plural = "گردش‌های مانده مرخصی"
        indexes = [models.Index(fields=["employee", "leave_type", "basis_date"], name="idx_ledger_emp_type")]
