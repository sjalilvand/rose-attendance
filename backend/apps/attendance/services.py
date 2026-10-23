"""Attendance services — the transactional core of the punch pipeline.

Implements docs/analysis/02-calculation-rules.md §3 (pairing) and §4
(effective time) verbatim, plus the approved geofence decision #3:

- receive_punch()      — online single event (idempotent by event_uuid)
- sync_batch()         — offline batch (<= SYNC_MAX_BATCH), stale -> NEEDS_REVIEW
- rebuild_pairings()   — deterministic session reconstruction from effective time
- approve_review()     — manager/HR TIME_FIX decision layer
- reject_review()      — manager/HR VOID decision layer (REJECTED_TECHNICAL)
"""
from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field

from django.conf import settings
from django.db import models as db_models
from django.db import transaction
from django.utils import timezone

from apps.core.enums import (
    AdjustmentKind,
    ConnectionMode,
    EventStatus,
    EventType,
    LocationStatus,
    SessionState,
    ShiftSource,
)
from apps.core.geodesy import haversine_m
from apps.scheduling.models import ScheduledShift

from .models import AttendanceAdjustment, AttendanceEvent, AttendanceSession

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Effective time + status resolution (calculation-rules §4)
# ---------------------------------------------------------------------------
@dataclass
class EventDecision:
    effective_time: dt.datetime
    event_status: str
    flags: list[str] = field(default_factory=list)
    location_status: str = LocationStatus.UNAVAILABLE
    location_reason: str = ""


def resolve_location(branch, latitude, longitude, accuracy_m) -> tuple[str, str]:
    """Geofence decision — approved decision #3: OUT_OF_RANGE is a label.

    Order: no coordinates -> UNAVAILABLE; coordinates beyond radius ->
    OUT_OF_RANGE; poor accuracy -> LOW_ACCURACY; otherwise IN_RANGE.
    """
    if latitude is None or longitude is None:
        return LocationStatus.UNAVAILABLE, "NO_COORDINATES"
    if branch.geo_latitude is None or branch.geo_longitude is None:
        # Branch has no configured centre yet — treat like unavailable
        # (recorded, labelled, never rejected).
        return LocationStatus.UNAVAILABLE, "BRANCH_NOT_GEOCODED"
    distance = haversine_m(branch.geo_latitude, branch.geo_longitude, latitude, longitude)
    if distance > branch.geo_radius_m:
        return LocationStatus.OUT_OF_RANGE, f"DISTANCE={distance:.0f}m"
    if accuracy_m is not None and accuracy_m > settings.APP_THRESHOLDS["LOCATION_MAX_ACCURACY_M"]:
        return LocationStatus.LOW_ACCURACY, f"ACCURACY={accuracy_m:.0f}m"
    return LocationStatus.IN_RANGE, ""


def decide_event(*, device_time: dt.datetime, connection_mode: str,
                 latitude, longitude, accuracy_m, branch,
                 clock_offset_minutes: float | None = None) -> EventDecision:
    """Effective-time rule chain (§4, rules 1–3) + geofence label.

    Clock-skew measurement per channel:
    - ONLINE: |device_time − server_now| directly comparable at receipt.
    - OFFLINE_SYNC: the device's own reported offset (clock vs. server,
      measured by the app against its last server time-sync); age alone is
      NOT skew — offline events are legitimately in the past.
    """
    now = timezone.now()
    t = settings.APP_THRESHOLDS

    flags: list[str] = []
    status = EventStatus.ACCEPTED

    if connection_mode == ConnectionMode.ONLINE:
        # Rule 1 — online: effective time is the server-confirmed time.
        effective = now
        skew_minutes = abs((now - device_time).total_seconds()) / 60.0
    else:
        # Rule 2 — ordinary offline (<= 7 days): effective = device time.
        effective = device_time
        age_days = (now - device_time).total_seconds() / 86400.0
        if age_days > t["OFFLINE_MAX_DAYS"]:
            # Rule 4 — stale offline: NEEDS_REVIEW until manager/HR confirms.
            status = EventStatus.NEEDS_REVIEW
            flags.append("STALE_OFFLINE")
        skew_minutes = abs(clock_offset_minutes) if clock_offset_minutes is not None else 0.0

    # Rule 3 — clock skew: flag; beyond the ambiguity threshold, review.
    if skew_minutes > t["CLOCK_SKEW_REVIEW_MINUTES"]:
        flags.append("CLOCK_SKEW")
        status = EventStatus.NEEDS_REVIEW
    elif skew_minutes > t["CLOCK_SKEW_MINUTES"]:
        flags.append("CLOCK_SKEW")

    loc_status, loc_reason = resolve_location(branch, latitude, longitude, accuracy_m)
    return EventDecision(
        effective_time=effective,
        event_status=status,
        flags=flags,
        location_status=loc_status,
        location_reason=loc_reason,
    )


# ---------------------------------------------------------------------------
# Shift-date resolution (§5, simplified core: scheduled record > unscheduled)
# ---------------------------------------------------------------------------
def resolve_shift_context(employee_id: int, branch_id: int, moment: dt.datetime):
    """Return (shift_date, scheduled_shift) for a punch moment.

    Source precedence: OVERRIDE > MANUAL > PATTERN (calculation-rules §5).
    """
    local = timezone.localtime(moment)
    precedence = db_models.Case(
        db_models.When(source=ShiftSource.OVERRIDE, then=db_models.Value(0)),
        db_models.When(source=ShiftSource.MANUAL, then=db_models.Value(1)),
        default=db_models.Value(2),
        output_field=db_models.IntegerField(),
    )
    scheduled = (
        ScheduledShift.objects.filter(
            employee_id=employee_id, branch_id=branch_id, work_date=local.date()
        )
        .select_related("shift")
        .order_by(precedence, "-id")
        .first()
    )
    if scheduled is not None:
        return scheduled.work_date, scheduled.id
    # Unscheduled — interval belongs to the local date of the check-in;
    # the «شیفت برنامه‌ریزی‌نشده» review path is the absence of a record.
    return local.date(), None


# ---------------------------------------------------------------------------
# Pairing (§3 + pseudocode §10) — incremental, idempotent, effective-time based
# ---------------------------------------------------------------------------
def _open_session(employee_id: int, branch_id: int):
    return (
        AttendanceSession.objects.select_for_update()
        .filter(
            employee_id=employee_id,
            branch_id=branch_id,
            session_state=SessionState.OPEN,
            is_purged=False,
        )
        .order_by("created_at")
        .first()
    )


def _shift_date_for(employee_id: int, branch_id: int, event: AttendanceEvent, session=None):
    if session is not None and session.shift_date:
        return session.shift_date, session.scheduled_shift_id
    return resolve_shift_context(employee_id, branch_id, event.effective_time)


def _work_minutes(check_in: AttendanceEvent, check_out: AttendanceEvent) -> int:
    seconds = (check_out.effective_time - check_in.effective_time).total_seconds()
    return max(0, int(seconds // 60))


@transaction.atomic
def apply_event_to_pairing(event: AttendanceEvent) -> None:
    """Fold one ACCEPTED event into the session stream (pairing rules 1–7).

    Pairing is based on effective time; arrival order and local_seq are
    analytic metadata only (section 9 rule).
    """
    if event.event_status != EventStatus.ACCEPTED:
        return  # NEEDS_REVIEW events pair after manager/HR approval.

    if event.event_type == EventType.CHECK_IN:
        opened = _open_session(event.employee_id, event.branch_id)
        if opened is None:
            shift_date, scheduled_id = resolve_shift_context(
                event.employee_id, event.branch_id, event.effective_time
            )
            AttendanceSession.objects.create(
                employee_id=event.employee_id,
                branch_id=event.branch_id,
                check_in_event=event,
                shift_date=shift_date,
                scheduled_shift_id=scheduled_id,
                session_state=SessionState.OPEN,
            )
        else:
            # Pairing rule 6 — duplicate check-in: keep event, flag it.
            if "DUPLICATE_CHECK_IN" not in event.flags:
                event.flags = [*event.flags, "DUPLICATE_CHECK_IN"]
                event.save(update_fields=["flags"])
        return

    # CHECK_OUT
    opened = _open_session(event.employee_id, event.branch_id)
    if opened is None:
        # Pairing rule 5 — checkout without open entry -> INVALID_SEQUENCE.
        shift_date, scheduled_id = resolve_shift_context(
            event.employee_id, event.branch_id, event.effective_time
        )
        AttendanceSession.objects.create(
            employee_id=event.employee_id,
            branch_id=event.branch_id,
            check_out_event=event,
            shift_date=shift_date,
            scheduled_shift_id=scheduled_id,
            session_state=SessionState.INVALID_SEQUENCE,
        )
        return

    if event.effective_time <= opened.check_in_event.effective_time:
        # §3.2 — effective checkout <= entry: INVALID_SEQUENCE, events kept.
        opened.check_out_event = event
        opened.session_state = SessionState.INVALID_SEQUENCE
        opened.save(update_fields=["check_out_event", "session_state", "updated_at"])
        return

    opened.check_out_event = event
    opened.session_state = SessionState.COMPLETE
    opened.work_minutes = _work_minutes(opened.check_in_event, event)
    opened.save(update_fields=["check_out_event", "session_state", "work_minutes", "updated_at"])


@transaction.atomic
def rebuild_pairings(employee_id: int, branch_id: int) -> None:
    """Deterministic re-pairing of the whole (person, branch) stream.

    Repeatability principle (§2): same inputs -> same outputs. Retention
    keeps roughly three months of details per person, so a full rebuild is
    O(few hundred events) and always correct, including open sessions that
    began before any review window. Purged sessions are never touched.
    """
    AttendanceSession.objects.filter(
        employee_id=employee_id, branch_id=branch_id, is_purged=False
    ).delete()

    events = (
        AttendanceEvent.objects.filter(
            employee_id=employee_id,
            branch_id=branch_id,
            event_status=EventStatus.ACCEPTED,
        )
        .order_by("effective_time", "id")
    )
    open_session: AttendanceSession | None = None
    for ev in events:
        if ev.event_type == EventType.CHECK_IN:
            if open_session is None or open_session.session_state != SessionState.OPEN:
                shift_date, scheduled_id = resolve_shift_context(
                    employee_id, branch_id, ev.effective_time
                )
                open_session = AttendanceSession.objects.create(
                    employee_id=employee_id,
                    branch_id=branch_id,
                    check_in_event=ev,
                    shift_date=shift_date,
                    scheduled_shift_id=scheduled_id,
                    session_state=SessionState.OPEN,
                )
            else:
                if "DUPLICATE_CHECK_IN" not in ev.flags:
                    ev.flags = [*ev.flags, "DUPLICATE_CHECK_IN"]
                    ev.save(update_fields=["flags"])
        else:
            if open_session is None:
                shift_date, scheduled_id = resolve_shift_context(
                    employee_id, branch_id, ev.effective_time
                )
                AttendanceSession.objects.create(
                    employee_id=employee_id,
                    branch_id=branch_id,
                    check_out_event=ev,
                    shift_date=shift_date,
                    scheduled_shift_id=scheduled_id,
                    session_state=SessionState.INVALID_SEQUENCE,
                )
            elif ev.effective_time <= open_session.check_in_event.effective_time:
                open_session.check_out_event = ev
                open_session.session_state = SessionState.INVALID_SEQUENCE
                open_session.save(update_fields=["check_out_event", "session_state"])
                open_session = None
            else:
                open_session.check_out_event = ev
                open_session.session_state = SessionState.COMPLETE
                open_session.work_minutes = _work_minutes(open_session.check_in_event, ev)
                open_session.save(update_fields=["check_out_event", "session_state", "work_minutes"])
                open_session = None
    # A stream ending with an open session stays OPEN — the incomplete-attendance queue.


# ---------------------------------------------------------------------------
# Ingestion API used by views
# ---------------------------------------------------------------------------
def refresh_summary_after_punch(employee, branch, effective_time) -> None:
    """Pipeline activation point 1 (calculation §2): refresh the Jalali-month
    summary of the (person, branch) stream right after a punch/sync.

    Kept inline for freshness on the single-host deployment; under heavy
    punch storms this can be switched to the nightly Celery safety net.
    Never breaks the punch itself.
    """
    try:
        from apps.core.jalali import jalali_period_of
        from apps.reports.services import recompute_month_summary

        jy, jm = jalali_period_of(effective_time)
        recompute_month_summary(employee.id, branch.id, jy, jm)
    except Exception:  # pragma: no cover — punch must never fail on rollup
        log.exception("summary refresh failed for emp=%s branch=%s", employee.id, branch.id)


@transaction.atomic
def receive_punch(*, employee, branch, event_type: str, event_uuid,
                  device_time: dt.datetime | None, connection_mode: str,
                  channel: str, latitude=None, longitude=None, accuracy_m=None,
                  location_fixed_at=None, local_seq=None, app_version: str = "",
                  client_request_id: str = "",
                  clock_offset_minutes: float | None = None) -> tuple[AttendanceEvent, bool]:
    """Create (or return the existing) event; returns (event, created).

    Idempotency: re-submission of the same event_uuid has no additional
    effect and returns the previous result (edge cases §11).
    """
    existing = AttendanceEvent.objects.filter(event_uuid=event_uuid).first()
    if existing is not None:
        return existing, False

    now = timezone.now()
    device_time = device_time or now
    decision = decide_event(
        device_time=device_time,
        connection_mode=connection_mode,
        latitude=latitude,
        longitude=longitude,
        accuracy_m=accuracy_m,
        branch=branch,
        clock_offset_minutes=clock_offset_minutes,
    )
    event = AttendanceEvent.objects.create(
        event_uuid=event_uuid,
        employee=employee,
        branch=branch,
        event_type=event_type,
        device_time=device_time,
        effective_time=decision.effective_time,
        channel=channel,
        connection_mode=connection_mode,
        latitude=latitude,
        longitude=longitude,
        location_accuracy_m=accuracy_m,
        location_fixed_at=location_fixed_at,
        location_status=decision.location_status,
        location_reason=decision.location_reason,
        event_status=decision.event_status,
        flags=decision.flags,
        local_seq=local_seq,
        app_version=app_version,
        client_request_id=client_request_id,
    )
    apply_event_to_pairing(event)
    refresh_summary_after_punch(employee, branch, event.effective_time)
    if decision.event_status == EventStatus.NEEDS_REVIEW:
        # Review-flow completion: branch managers learn about the event
        # immediately (row persisted in-tx, live push after commit).
        from apps.messaging.services import notify_branch_managers

        notify_branch_managers(
            branch_id=branch.id,
            kind="REVIEW_REQUIRED",
            title="تردد نیازمند رسیدگی جدید ثبت شد",
            payload={
                "event_uuid": str(event.event_uuid),
                "personnel_code": employee.personnel_code,
                "employee_name": employee.full_name,
                "flags": decision.flags,
                "connection_mode": connection_mode,
            },
        )
    return event, True


@transaction.atomic
def approve_review(*, event: AttendanceEvent, decided_by, corrected_time: dt.datetime,
                   reason: str) -> AttendanceEvent:
    """Manager/HR confirmation of an effective time (approved decision #4).

    Adds a TIME_FIX decision layer; the raw event is never rewritten, and
    pairings for the window are rebuilt deterministically.
    """
    previous = {
        "effective_time": event.effective_time.isoformat(),
        "event_status": event.event_status,
    }
    event.effective_time = corrected_time
    event.event_status = EventStatus.ACCEPTED
    event.flags = sorted({*event.flags, "REVIEW_RESOLVED"})
    event.save(update_fields=["effective_time", "event_status", "flags", "updated_at"])

    AttendanceAdjustment.objects.create(
        target_event=event,
        adjustment_kind=AdjustmentKind.TIME_FIX,
        original_value=previous,
        corrected_value={"effective_time": corrected_time.isoformat(),
                         "event_status": EventStatus.ACCEPTED},
        reason=reason,
        decided_by=decided_by,
    )
    rebuild_pairings(event.employee_id, event.branch_id)

    from apps.messaging.services import notify_employee

    notify_employee(
        employee_id=event.employee_id,
        kind="REVIEW_RESOLVED",
        title="تردد نیازمند رسیدگی شما تأیید شد",
        payload={"event_id": event.id, "effective_time": corrected_time.isoformat()},
    )
    return event


@transaction.atomic
def reject_review(*, event: AttendanceEvent, decided_by, reason: str) -> AttendanceEvent:
    """Manager/HR refusal of a NEEDS_REVIEW event (decision layer, section 8).

    The raw event is kept forever but flagged REJECTED_TECHNICAL and excluded
    from pairing (apply/rebuild fold ACCEPTED events only). A VOID adjustment
    records the decision; the employee is notified like on approval.
    """
    previous = {
        "effective_time": event.effective_time.isoformat(),
        "event_status": event.event_status,
    }
    event.event_status = EventStatus.REJECTED_TECHNICAL
    event.flags = sorted({*event.flags, "REVIEW_RESOLVED", "REVIEW_REJECTED"})
    event.save(update_fields=["event_status", "flags", "updated_at"])

    AttendanceAdjustment.objects.create(
        target_event=event,
        adjustment_kind=AdjustmentKind.VOID,
        original_value=previous,
        corrected_value={"event_status": EventStatus.REJECTED_TECHNICAL},
        reason=reason,
        decided_by=decided_by,
    )
    # Rebuild is a no-op for this event (not ACCEPTED) but re-runs for the
    # whole (person, branch) stream so prior state stays deterministic.
    rebuild_pairings(event.employee_id, event.branch_id)

    from apps.messaging.services import notify_employee

    notify_employee(
        employee_id=event.employee_id,
        kind="REVIEW_REJECTED",
        title="تردد نیازمند رسیدگی شما رد شد",
        payload={"event_id": event.id, "reason": reason},
    )
    return event
