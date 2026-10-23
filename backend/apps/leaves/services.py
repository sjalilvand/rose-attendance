"""Requests domain services — submit, branch-split, independent decisions.

Section 11 + approved decision #5: multi-branch requests are split into
per-(branch × interval) segments; each segment is decided independently and
the overall status is composed — any REJECTED → REJECTED, else all APPROVED
→ APPROVED, else PENDING. Cancellation clears every segment to CANCELLED.

Leave balances (LeaveLedger) are intentionally NOT mutated yet: opening
balances await the HR workbook import (pending employer input, phase-2
checklist). Once seeded, APPROVE should append a DEDUCTION entry here.

The calculation engine already consumes APPROVED segments (reports/services
_load_leave_spans → LeaveSpan), so a decision instantly affects daily rows
and the monthly summary; decide_segment() triggers recompute_month_summary
for the Jalali month the segment belongs to (same pattern as §7.3 overtime).
"""
from __future__ import annotations

import datetime as dt

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.core.enums import (
    ApprovalAction,
    RequestStatus,
    SegmentStatus,
)
from apps.core.jalali import jalali_period_of
from apps.leaves.models import (
    ApprovalAction as ApprovalActionLog,
)
from apps.leaves.models import (
    LeaveRequest,
    LeaveType,
    MissionRequest,
    RequestSegment,
)
from apps.people.models import Employee, User

MAX_REQUEST_DAYS = 180  # sanity cap against accidental year-long requests


class RequestError(Exception):
    """Domain error mapped to a coded API response by leaves/api."""

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.message = message
        self.code = code


def active_branches_for(employee: Employee) -> list:
    """Home branch first, then allowed dated assignments — deduped."""
    today = timezone.localdate()
    branches: list = []
    seen: set[int] = set()
    if employee.home_branch_id and employee.home_branch_id not in seen:
        branches.append(employee.home_branch)
        seen.add(employee.home_branch_id)
    assignments = employee.branch_assignments.filter(
        is_allowed=True, valid_from__lte=today
    ).filter(
        Q(valid_to__isnull=True) | Q(valid_to__gte=today)
    ).select_related("branch").order_by("id")
    for assignment in assignments:
        if assignment.branch_id not in seen:
            branches.append(assignment.branch)
            seen.add(assignment.branch_id)
    return branches


def _validated_window(starts_at, ends_at) -> tuple:
    if starts_at is None or ends_at is None:
        raise RequestError("شروع و پایان الزامی است.", "INVALID")
    if timezone.is_naive(starts_at):
        starts_at = timezone.make_aware(starts_at)
    if timezone.is_naive(ends_at):
        ends_at = timezone.make_aware(ends_at)
    if ends_at <= starts_at:
        raise RequestError("پایان باید بعد از شروع باشد.", "INVALID")
    if (ends_at - starts_at) > dt.timedelta(days=MAX_REQUEST_DAYS):
        raise RequestError(f"حداکثر بازهٔ درخواست {MAX_REQUEST_DAYS} روز است.", "INVALID")
    return starts_at, ends_at


def _create_segments(request_obj, kind: str, starts_at, ends_at) -> list:
    branches = active_branches_for(request_obj.employee)
    if not branches:
        raise RequestError("شعبهٔ فعالی برای پرسنل یافت نشد.", "NO_BRANCH")
    minutes = int((ends_at - starts_at).total_seconds() // 60)
    segments = [
        RequestSegment(
            request_kind=kind,
            leave_request=request_obj if kind == "LEAVE" else None,
            mission_request=request_obj if kind == "MISSION" else None,
            branch=branch,
            starts_at=starts_at,
            ends_at=ends_at,
            computed_minutes=minutes,
            segment_status=SegmentStatus.PENDING,
        )
        for branch in branches
    ]
    RequestSegment.objects.bulk_create(segments)
    return segments


def submit_leave(
    employee: Employee,
    leave_type: LeaveType,
    starts_at,
    ends_at,
    description: str = "",
) -> LeaveRequest:
    starts_at, ends_at = _validated_window(starts_at, ends_at)
    with transaction.atomic():
        request_obj = LeaveRequest.objects.create(
            employee=employee,
            leave_type=leave_type,
            starts_at=starts_at,
            ends_at=ends_at,
            computed_minutes=int((ends_at - starts_at).total_seconds() // 60),
            description=description[:2000],
            overall_status=RequestStatus.PENDING,
        )
        _create_segments(request_obj, "LEAVE", starts_at, ends_at)
    return request_obj


def submit_mission(
    employee: Employee,
    subject: str,
    starts_at,
    ends_at,
    destination_branch=None,
    destination_text: str = "",
) -> MissionRequest:
    starts_at, ends_at = _validated_window(starts_at, ends_at)
    if not subject:
        raise RequestError("موضوع مأموریت الزامی است.", "INVALID")
    with transaction.atomic():
        request_obj = MissionRequest.objects.create(
            employee=employee,
            destination_branch=destination_branch,
            destination_text=(destination_text or "")[:200],
            subject=subject[:200],
            starts_at=starts_at,
            ends_at=ends_at,
            computed_minutes=int((ends_at - starts_at).total_seconds() // 60),
            overall_status=RequestStatus.PENDING,
        )
        _create_segments(request_obj, "MISSION", starts_at, ends_at)
    return request_obj


def compose_overall(request_obj) -> str:
    """Decision #5 composition — never recomputes times."""
    statuses = list(request_obj.segments.values_list("segment_status", flat=True))
    if not statuses:
        return RequestStatus.PENDING
    if any(s == SegmentStatus.REJECTED for s in statuses):
        overall = RequestStatus.REJECTED
    elif all(s == SegmentStatus.APPROVED for s in statuses):
        overall = RequestStatus.APPROVED
    elif all(s == SegmentStatus.CANCELLED for s in statuses):
        overall = RequestStatus.CANCELLED
    else:
        overall = RequestStatus.PENDING
    if request_obj.overall_status != overall:
        request_obj.overall_status = overall
        request_obj.save(update_fields=["overall_status", "updated_at"])
    return overall


def cancel_request(kind: str, request_id: int, by: User):
    """Employee cancels their own still-pending request (section 11)."""
    model = LeaveRequest if kind == "LEAVE" else MissionRequest
    try:
        request_obj = model.objects.get(id=request_id, employee=by.employee)
    except model.DoesNotExist as exc:
        raise RequestError("درخواست یافت نشد.", "NOT_FOUND") from exc
    if request_obj.overall_status != RequestStatus.PENDING:
        raise RequestError("فقط درخواست در انتظار قابل لغو است.", "ALREADY_DECIDED")
    with transaction.atomic():
        for segment in request_obj.segments.select_for_update():
            if segment.segment_status == SegmentStatus.PENDING:
                segment.segment_status = SegmentStatus.CANCELLED
                segment.save(update_fields=["segment_status", "updated_at"])
                ApprovalActionLog.objects.create(
                    segment=segment,
                    action=ApprovalAction.CANCEL,
                    decided_by=by,
                    comment="لغو توسط پرسنل",
                )
        compose_overall(request_obj)
    return request_obj


def decide_segment(
    segment: RequestSegment,
    decided_by: User,
    action: str,
    comment: str = "",
    on_behalf_of: Employee | None = None,
) -> RequestSegment:
    """Independent (branch × interval) decision — approved decision #5."""
    if action not in (ApprovalAction.APPROVE, ApprovalAction.REJECT):
        raise RequestError("اقدام باید APPROVE یا REJECT باشد.", "INVALID")
    if segment.segment_status != SegmentStatus.PENDING:
        raise RequestError("این بخش قبلاً رسیدگی شده است.", "ALREADY_DECIDED")
    with transaction.atomic():
        ApprovalActionLog.objects.create(
            segment=segment,
            action=action,
            decided_by=decided_by,
            on_behalf_of=on_behalf_of,
            comment=(comment or "")[:2000],
        )
        segment.segment_status = (
            SegmentStatus.APPROVED if action == ApprovalAction.APPROVE else SegmentStatus.REJECTED
        )
        segment.save(update_fields=["segment_status", "updated_at"])
        request_obj = segment.leave_request or segment.mission_request
        compose_overall(request_obj)
    _refresh_summary(segment)

    from apps.messaging.services import notify_employee

    notify_employee(
        employee_id=request_obj.employee_id,
        kind="REQUEST_DECISION",
        title=(
            "درخواست شما تأیید شد" if action == ApprovalAction.APPROVE else "درخواست شما رد شد"
        ),
        payload={
            "request_kind": "LEAVE" if segment.leave_request_id else "MISSION",
            "request_id": request_obj.id,
            "segment_id": segment.id,
            "action": action,
        },
    )
    return segment


def _refresh_summary(segment: RequestSegment) -> None:
    """Roll up the Jalali month the segment belongs to (not decision date)."""
    from apps.reports.services import recompute_month_summary

    jy, jm = jalali_period_of(timezone.localtime(segment.starts_at).date())
    employee_id = (
        segment.leave_request.employee_id
        if segment.leave_request_id
        else segment.mission_request.employee_id
    )
    try:
        recompute_month_summary(employee_id, segment.branch_id, jy, jm)
    except Exception:  # pragma: no cover - summary row may not exist yet
        pass
