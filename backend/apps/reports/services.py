"""Monthly rollup + period closure — calculation-rules §7.4 and §9.

Rollup unit: (person × branch × Jalali month) — approved decision #2 of §34
(Jalali boundaries). The person-level total is always the SUM of branch rows,
never a re-computation (§7.4). Everything is repeatable: re-running with the
same inputs produces the same summary (§2), and closed periods are protected.

Shortage (§7.3): max(0, Σ obligation − Σ accepted_work − Σ leave_credit −
Σ mission_credit − Σ absence) — absence minutes are subtracted again so an
absent day is never double-counted as both absence and shortage.
"""
from __future__ import annotations

import datetime as dt

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone as djtz

from apps.attendance.calculation import (
    LeaveSpan,
    RuleResolver,
    compute_day,
)
from apps.attendance.models import AttendanceEvent, AttendanceSession, OvertimeProposal
from apps.core.enums import (
    EventStatus,
    LocationStatus,
    SegmentStatus,
    SessionState,
    SummaryState,
)
from apps.core.jalali import jalali_month_range
from apps.leaves.models import RequestSegment
from apps.scheduling.models import ScheduledShift

from .models import MonthlyClosure, MonthlySummary


def _aware_start(date: dt.date) -> dt.datetime:
    return dt.datetime.combine(date, dt.time.min).replace(tzinfo=djtz.get_current_timezone())


def month_window(jy: int, jm: int) -> tuple[dt.datetime, dt.datetime]:
    """Aware [start, end) window covering the whole Jalali month."""
    first_day, last_day = jalali_month_range(jy, jm)
    return _aware_start(first_day), _aware_start(last_day + dt.timedelta(days=1))


def _load_leave_spans(employee_id: int, window) -> list[LeaveSpan]:
    """Approved segments of the employee overlapping the window (§8)."""
    rows = (
        RequestSegment.objects.filter(segment_status=SegmentStatus.APPROVED)
        .filter(
            _q_employee(employee_id),
            starts_at__lt=window[1],
            ends_at__gt=window[0],
        )
        .select_related("leave_request__leave_type", "leave_request", "mission_request")
    )
    spans: list[LeaveSpan] = []
    for seg in rows:
        kind = "MISSION" if seg.request_kind == "MISSION" else "LEAVE"
        type_code = None
        if seg.leave_request_id and seg.leave_request is not None:
            type_code = seg.leave_request.leave_type.code
        spans.append(
            LeaveSpan(
                start=max(seg.starts_at, window[0]),
                end=min(seg.ends_at, window[1]),
                kind=kind,
                type_code=type_code,
            )
        )
    return spans


def _q_employee(employee_id: int):
    from django.db.models import Q

    return Q(leave_request__employee_id=employee_id) | Q(mission_request__employee_id=employee_id)


def _holiday_dates(branch, start_date: dt.date, end_date: dt.date) -> set[dt.date]:
    calendar = getattr(branch, "work_calendar", None)
    if calendar is None:
        return set()
    return set(
        calendar.holidays.filter(holiday_date__range=(start_date, end_date)).values_list(
            "holiday_date", flat=True
        )
    )


def _approved_overtime_map(employee_id: int, branch_id: int, start_date, end_date):
    """{session_id: approved_minutes} within the period."""
    rows = OvertimeProposal.objects.filter(
        employee_id=employee_id,
        branch_id=branch_id,
        shift_date__range=(start_date, end_date),
        status=SegmentStatus.APPROVED,
    ).values_list("session_id", "approved_minutes")
    return {sid: int(minutes or 0) for sid, minutes in rows}


def compute_days_for_month(employee_id: int, branch_id: int, jy: int, jm: int):
    """Pure day list of the period — shared by rollup and the daily API."""
    from apps.orgs.models import Branch
    from apps.people.models import Employee

    branch = Branch.objects.get(id=branch_id)
    employee = Employee.objects.get(id=employee_id)
    first_day, last_day = jalali_month_range(jy, jm)
    window = month_window(jy, jm)

    sessions_by_date: dict[dt.date, list] = {}
    qs = AttendanceSession.objects.filter(
        employee_id=employee_id, branch_id=branch_id, is_purged=False,
        shift_date__range=(first_day, last_day),
    ).select_related(
        "check_in_event", "check_out_event", "scheduled_shift", "scheduled_shift__shift"
    )
    for s in qs:
        sessions_by_date.setdefault(s.shift_date, []).append(s)

    scheduled = {
        row.work_date: row
        for row in ScheduledShift.objects.filter(
            employee_id=employee_id, branch_id=branch_id, work_date__range=(first_day, last_day)
        ).select_related("shift")
    }
    leave_spans = _load_leave_spans(employee_id, window)
    holidays = _holiday_dates(branch, first_day, last_day)
    ot_map = _approved_overtime_map(employee_id, branch_id, first_day, last_day)

    resolver = RuleResolver(branch)
    results = []
    day = first_day
    while day <= last_day:
        results.append(
            compute_day(
                employee_id=employee_id,
                branch_id=branch_id,
                shift_date=day,
                sessions=sessions_by_date.get(day, []),
                scheduled_shift=scheduled.get(day),
                leave_spans=leave_spans,
                resolver=resolver,
                is_holiday=day in holidays,
                overtime_approved_by_session=ot_map,
            )
        )
        day += dt.timedelta(days=1)
    return results, resolver


def _forgive_late(days, forgive_count: int) -> None:
    """Monthly late forgiveness (LATE payload) — first N occurrences,
    chronologically; a neutral, predictable default until HR specifies."""
    if forgive_count <= 0:
        return
    forgiven = 0
    for day in days:
        if forgiven >= forgive_count:
            break
        if day.late_minutes > 0:
            day.late_minutes = 0
            day.late_deduction_minutes = 0
            day.late_deduct_mode = None
            day.flags.append("LATE_FORGIVEN")
            forgiven += 1


def _sync_overtime_proposals(employee, branch, days) -> None:
    """Persist auto-proposals (§7.3) — one per session extending beyond
    planned_end on days where the day-level minimum block is met."""
    for day in days:
        if day.overtime_proposed_minutes <= 0:
            continue
        for session_id, _out in day.session_overtime:
            session = AttendanceSession.objects.filter(id=session_id).first()
            if session is None:
                continue
            out = session.check_out_event.effective_time if session.check_out_event else None
            sched = session.scheduled_shift
            if out is None or sched is None or sched.planned_end is None:
                continue
            beyond = int((out - sched.planned_end).total_seconds() // 60)
            if beyond <= 0:
                continue
            OvertimeProposal.objects.get_or_create(
                session=session,
                defaults=dict(
                    employee=employee,
                    branch=branch,
                    shift_date=day.shift_date,
                    proposed_minutes=beyond,
                    reason=(
                        f"خروج {beyond} دقیقه پس از پایان شیفت "
                        f"({sched.planned_end:%Y-%m-%d %H:%M})"
                    ),
                ),
            )


def recompute_month_summary(employee_id: int, branch_id: int, jy: int, jm: int,
                            force: bool = False) -> MonthlySummary | None:
    """Build/upsert one (person × branch × Jalali month) summary. Repeatable."""
    from apps.orgs.models import Branch
    from apps.people.models import Employee

    existing = MonthlySummary.objects.filter(
        employee_id=employee_id, branch_id=branch_id, period_year=jy, period_month=jm
    ).first()
    if (
        not force
        and existing is not None
        and existing.summary_state == SummaryState.FINAL
        and existing.closure_id is not None
    ):
        return existing  # closed period — protected (§9)

    employee = Employee.objects.get(id=employee_id)
    branch = Branch.objects.get(id=branch_id)
    days, resolver = compute_days_for_month(employee_id, branch_id, jy, jm)
    _sync_overtime_proposals(employee, branch, days)

    # Re-read approved overtime after the sync above so freshly proposed
    # (already-approved-auto) sessions are reflected consistently.
    days, resolver = compute_days_for_month(employee_id, branch_id, jy, jm)

    late_payload_last_day = resolver.get("LATE", days[-1].shift_date)[0]
    _forgive_late(days, int(late_payload_last_day.get("monthly_forgive_count", 0) or 0))

    first_day = days[0].shift_date
    last_day = days[-1].shift_date
    window = month_window(jy, jm)

    leave_by_type: dict[str, int] = {}
    for day in days:
        for code, minutes in day.leave_minutes_by_type.items():
            leave_by_type[code] = leave_by_type.get(code, 0) + minutes

    required = sum(d.required_minutes for d in days)
    valid_presence = sum(d.valid_presence_minutes for d in days)
    accepted_work = sum(d.accepted_work_minutes for d in days)
    late_minutes = sum(d.late_minutes for d in days)
    early_minutes = sum(d.early_leave_minutes for d in days)
    absence = sum(d.absence_minutes for d in days)
    overtime = sum(d.overtime_approved_minutes for d in days)
    mission = sum(d.mission_credit_minutes for d in days)
    leave_credit = sum(d.leave_credit_minutes for d in days)
    shortage = max(
        0,
        required - accepted_work - leave_credit - mission - absence,
    )
    incomplete = sum(d.incomplete_sessions for d in days)

    no_location = AttendanceEvent.objects.filter(
        employee_id=employee_id, branch_id=branch_id,
        effective_time__range=window,
        location_status=LocationStatus.UNAVAILABLE,
    ).count()
    out_of_range = AttendanceEvent.objects.filter(
        employee_id=employee_id, branch_id=branch_id,
        effective_time__range=window,
        location_status=LocationStatus.OUT_OF_RANGE,
    ).count()

    state = existing.summary_state if existing else SummaryState.PROVISIONAL
    if state == SummaryState.PROVISIONAL or state == "":
        state = SummaryState.PROVISIONAL
    summary, _created = MonthlySummary.objects.update_or_create(
        employee_id=employee_id,
        branch_id=branch_id,
        period_year=jy,
        period_month=jm,
        defaults=dict(
            required_minutes=required,
            valid_presence_minutes=valid_presence,
            accepted_work_minutes=accepted_work,
            late_minutes=late_minutes,
            early_leave_minutes=early_minutes,
            absence_minutes=absence,
            shortage_minutes=shortage,
            overtime_minutes=overtime,
            leave_minutes_by_type=leave_by_type,
            mission_minutes=mission,
            incomplete_session_count=incomplete,
            no_location_count=no_location,
            out_of_range_count=out_of_range,
            rule_set_ids=resolver.used_rule_ids(),
        ),
    )
    return summary


def month_scope_pairs(jy: int, jm: int, branch_id: int | None = None) -> set[tuple[int, int]]:
    """(employee_id, branch_id) pairs having data in the period."""
    first_day, last_day = jalali_month_range(jy, jm)
    window = month_window(jy, jm)
    pairs: set[tuple[int, int]] = set()
    pairs.update(
        AttendanceSession.objects.filter(
            is_purged=False, shift_date__range=(first_day, last_day)
        ).values_list("employee_id", "branch_id")
    )
    pairs.update(
        ScheduledShift.objects.filter(
            work_date__range=(first_day, last_day)
        ).values_list("employee_id", "branch_id")
    )
    pairs.update(
        AttendanceEvent.objects.filter(
            effective_time__range=window
        ).values_list("employee_id", "branch_id")
    )
    if branch_id is not None:
        pairs = {(e, b) for e, b in pairs if b == branch_id}
    return pairs


def recompute_month(jy: int, jm: int, branch_id: int | None = None,
                    force: bool = False) -> list[MonthlySummary]:
    """Step 1 of the closure flow — refresh every pair of the period."""
    summaries = []
    for employee_id, branch in sorted(month_scope_pairs(jy, jm, branch_id)):
        summary = recompute_month_summary(employee_id, branch, jy, jm, force=force)
        if summary is not None:
            summaries.append(summary)
    return summaries


# ---------------------------------------------------------------------------
# Period closure — the six-step flow of §9 (بخش ۱۳ سند)
# ---------------------------------------------------------------------------
@transaction.atomic
def close_month(*, jy: int, jm: int, closed_by, branch=None,
                notes: str = "") -> MonthlyClosure:
    """Close a Jalali period: recompute → guard → lock → finalize (§9)."""
    first_day, last_day = jalali_month_range(jy, jm)
    window = month_window(jy, jm)
    scope_branch = branch

    today = djtz.localdate()
    if first_day > today:
        raise ValidationError("بستن دوره آینده مجاز نیست.")

    closure = MonthlyClosure.objects.create(
        period_year=jy, period_month=jm,
        scope="BRANCH" if scope_branch is not None else "GLOBAL",
        scope_branch=scope_branch,
        state="IN_PROGRESS",
        closed_by=closed_by,
        notes=notes,
    )  # unique constraints reject concurrent duplicates (§9)

    _guard_open_sessions(jy, jm, scope_branch)
    _guard_pending_segments(window, scope_branch)
    _guard_needs_review_events(window, scope_branch)

    recompute_month(jy, jm, branch_id=scope_branch.id if scope_branch else None)

    qs = MonthlySummary.objects.filter(period_year=jy, period_month=jm)
    if scope_branch is not None:
        qs = qs.filter(branch=scope_branch)
    now = djtz.now()
    for summary in qs.select_related("closure"):
        if summary.closure_id is not None and summary.summary_state == SummaryState.FINAL:
            continue
        summary.summary_state = SummaryState.FINAL
        summary.closure = closure
        summary.finalized_at = now
        summary.save(update_fields=[
            "summary_state", "closure", "finalized_at", "updated_at"
        ])

    closure.state = "CLOSED"
    closure.closed_at = now
    closure.save(update_fields=["state", "closed_at"])
    return closure


def _guard_open_sessions(jy: int, jm: int, scope_branch) -> None:
    bad = AttendanceSession.objects.filter(
        shift_date__range=jalali_month_range(jy, jm), is_purged=False
    ).exclude(session_state=SessionState.COMPLETE)
    if scope_branch is not None:
        bad = bad.filter(branch=scope_branch)
    count = bad.count()
    if count:
        raise ValidationError(
            f"{count} بازه حضور ناقص/نامعتبر در دوره باقی است؛ ابتدا رسیدگی شود (مرحله ۲)."
        )


def _guard_pending_segments(window, scope_branch) -> None:
    pending = RequestSegment.objects.filter(
        segment_status=SegmentStatus.PENDING,
        starts_at__lt=window[1],
        ends_at__gt=window[0],
    )
    if scope_branch is not None:
        pending = pending.filter(branch=scope_branch)
    count = pending.count()
    if count:
        raise ValidationError(
            f"{count} بخش درخواست در انتظار تصمیم است؛ ابتدا رسیدگی شود (مرحله ۳)."
        )


def _guard_needs_review_events(window, scope_branch) -> None:
    review = AttendanceEvent.objects.filter(
        event_status=EventStatus.NEEDS_REVIEW,
        effective_time__range=window,
    )
    if scope_branch is not None:
        review = review.filter(branch=scope_branch)
    count = review.count()
    if count:
        raise ValidationError(
            f"{count} رویداد در انتظار رسیدگی در دوره وجود دارد؛ ابتدا زمان مؤثر تثبیت شود."
        )
