"""Daily work-time calculation engine — docs/analysis/02-calculation-rules.md §6–§8.

Design contract (calculation-rules §2): the engine is PURE and REPEATABLE —
the same inputs always produce the same outputs; persistence (monthly
summaries, overtime proposals) lives in apps.reports.services / sync helper.

Nothing is hard-coded (approved decision #7 of §34): late/early/rest/
overtime/absence/holiday policies come from versioned `rule_sets` payloads
(BRANCH > REGION > GLOBAL, ACTIVE + covering the date). When no rule resolves,
neutral safe defaults apply (FLAG_ONLY, no deduction) so the system stays
functional until HR uploads the real regulations (§12 of the analysis).

Presence priority — «دوباره‌شماری ممنوع» (§7.1, explicit rule of section 10):
a minute covered by both valid presence and approved leave/mission is counted
ONCE, as presence; the overlapping leave is not credited.

All durations are whole minutes; rounding happens only at the points allowed
by the rule payload (late/early round UP — conservative for the employee,
overtime rounds DOWN — conservative for payment).
"""
from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

from django.utils import timezone as djtz

from apps.core.enums import RestMode, RuleKind, SessionState
from apps.rules.models import RuleSet

TEHRAN = ZoneInfo("Asia/Tehran")

# Neutral defaults used when no versioned rule resolves for a date.
DEFAULT_LATE: dict = {
    "grace_minutes": None,  # None -> fall back to shift.grace_minutes
    "tiers": [{"above_minutes": 0, "deduct_mode": "FLAG_ONLY"}],
    "monthly_forgive_count": 0,
    "rounding_minutes": 1,
}
DEFAULT_EARLY: dict = {
    "grace_minutes": None,
    "tiers": [{"above_minutes": 0, "deduct_mode": "FLAG_ONLY"}],
    "rounding_minutes": 1,
}
DEFAULT_OVERTIME: dict = {
    "min_block_minutes": 30,
    "requires_approval": True,   # always true in v1 per calculation-rules §7.3
    "max_daily_minutes": 240,
    "multiplier": 1.0,
    "rounding_minutes": 1,
}
DEFAULT_ABSENCE: dict = {
    "no_show_minutes": 120,
    "half_day_threshold_minutes": 180,
}
DEFAULT_HOLIDAY: dict = {"work_multiplier": 1.0, "counts_toward_shortage": False}


@dataclass
class LeaveSpan:
    """Approved leave/mission interval (aware UTC) clipped per day in-engine."""

    start: dt.datetime
    end: dt.datetime
    kind: str  # LEAVE / MISSION
    type_code: str | None = None  # LeaveType.code for leave_minutes_by_type


@dataclass
class DayResult:
    """Outcome of one (employee × branch × shift_date) calculation."""

    employee_id: int
    branch_id: int
    shift_date: dt.date
    scheduled_shift_id: int | None = None
    shift_code: str | None = None
    is_workday: bool = False          # شیفت برنامه‌ریزی‌شده دارد
    is_holiday: bool = False
    required_minutes: int = 0         # ساعات موظفی همان روز (بدون استراحت مقرر)
    valid_presence_minutes: int = 0   # Σ کارکرد خام بازه‌های COMPLETE
    accepted_work_minutes: int = 0    # پس از کسر استراحت (اولویت حضور با مرخصی)
    rest_minutes: int = 0             # استراحت کسرشده
    late_minutes: int = 0
    late_deduct_mode: str | None = None
    late_deduction_minutes: int = 0
    early_leave_minutes: int = 0
    overtime_proposed_minutes: int = 0   # پیشنهاد خودکار (نیازمند تأیید مدیر §7.3)
    overtime_approved_minutes: int = 0   # جمع تأییدشده‌ها از OvertimeProposal
    session_overtime: list = field(default_factory=list)  # [(session_id, minutes)]
    absence_minutes: int = 0
    leave_minutes_by_type: dict = field(default_factory=dict)
    mission_minutes: int = 0
    leave_credit_minutes: int = 0     # اعتبار مرخصیِ مؤثر در سقف موظفی همان روز
    mission_credit_minutes: int = 0
    session_count: int = 0
    incomplete_sessions: int = 0      # OPEN / INVALID_SEQUENCE
    flags: list = field(default_factory=list)
    rule_set_ids: list = field(default_factory=list)
    first_in: dt.datetime | None = None
    last_out: dt.datetime | None = None


# ---------------------------------------------------------------------------
# Rule resolution (§6) — BRANCH > REGION > GLOBAL, with neutral fallback
# ---------------------------------------------------------------------------
class RuleResolver:
    """Resolves versioned rule payloads per (kind, date) with a per-run cache."""

    _DEFAULTS = {
        RuleKind.LATE: DEFAULT_LATE,
        RuleKind.EARLY_LEAVE: DEFAULT_EARLY,
        RuleKind.OVERTIME: DEFAULT_OVERTIME,
        RuleKind.ABSENCE: DEFAULT_ABSENCE,
        RuleKind.HOLIDAY: DEFAULT_HOLIDAY,
    }

    def __init__(self, branch):
        self.branch = branch
        self._cache: dict[tuple[str, dt.date], tuple[dict, RuleSet | None]] = {}
        self.used_ids: set[int] = set()

    def get(self, rule_kind: str, date: dt.date) -> tuple[dict, RuleSet | None]:
        key = (rule_kind, date)
        if key not in self._cache:
            rule = RuleSet.resolve_for(rule_kind, self.branch, date)
            if rule is not None:
                self.used_ids.add(rule.id)
                payload = dict(rule.payload or {})
            else:
                payload = dict(self._DEFAULTS.get(rule_kind, {}))
            self._cache[key] = (payload, rule)
        return self._cache[key]

    def used_rule_ids(self) -> list[int]:
        return sorted(self.used_ids)


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def _local_midnight(date: dt.date) -> dt.datetime:
    return dt.datetime.combine(date, dt.time.min).replace(tzinfo=TEHRAN)


def day_window(scheduled_shift) -> tuple[dt.datetime, dt.datetime]:
    """Absolute (planned) window of a shift_date.

    With a scheduled shift: [planned_start, planned_end) — night shifts cross
    midnight but stay anchored to the shift START date (§3.1 rule 3). Without
    one: the Tehran calendar day.
    """
    if scheduled_shift is not None and scheduled_shift.planned_start and scheduled_shift.planned_end:
        return scheduled_shift.planned_start, scheduled_shift.planned_end
    start = _local_midnight(scheduled_shift.work_date if scheduled_shift else dt.date.today())
    return start, start + dt.timedelta(days=1)


def overlap_minutes(a_start, a_end, b_start, b_end) -> int:
    """Whole minutes of intersection between two aware intervals."""
    latest_start = max(a_start, b_start)
    earliest_end = min(a_end, b_end)
    if earliest_end <= latest_start:
        return 0
    return int((earliest_end - latest_start).total_seconds() // 60)


def _round_up(minutes: int, step: int) -> int:
    step = max(1, int(step))
    return int(math.ceil(minutes / step) * step) if minutes > 0 else 0


def _round_down(minutes: int, step: int) -> int:
    step = max(1, int(step))
    return (minutes // step) * step if minutes > 0 else 0


# ---------------------------------------------------------------------------
# Tiered late/early application (§7.2)
# ---------------------------------------------------------------------------
def _pick_tier(tiers: list, minutes: int) -> dict:
    for tier in tiers or []:
        if "up_to_minutes" in tier and minutes <= tier["up_to_minutes"]:
            return tier
        if "above_minutes" in tier and minutes > tier["above_minutes"]:
            return tier
    return {"deduct_mode": "FLAG_ONLY"}


def _apply_late_like(payload: dict, minutes_raw: int, flags: list, flag_prefix: str):
    """Returns (rounded_minutes, deduct_mode, deduction_minutes)."""
    if minutes_raw <= 0:
        return 0, None, 0
    step = payload.get("rounding_minutes", 1)
    minutes = _round_up(minutes_raw, step)
    tier = _pick_tier(payload.get("tiers") or [], minutes)
    mode = tier.get("deduct_mode", "FLAG_ONLY")
    deduction = 0
    if mode == "DEDUCT":
        deduction = int(round(minutes * float(tier.get("multiplier", 1.0))))
        flags.append(f"{flag_prefix}_DEDUCTED")
    elif mode == "TREAT_AS_ABSENCE_HALF":
        flags.append(f"{flag_prefix}_AS_ABSENCE_HALF")
    else:
        flags.append(f"{flag_prefix}_FLAGGED")
    return minutes, mode, deduction


# ---------------------------------------------------------------------------
# Rest rule (§7.1) — rule payload overrides shift defaults when it resolves
# ---------------------------------------------------------------------------
def apply_rest_rule(payload: dict | None, shift, raw_presence: int) -> int:
    if raw_presence <= 0:
        return 0
    if payload is not None and payload.get("mode"):
        mode = payload.get("mode")
        minutes = int(payload.get("default_minutes") or 0)
        min_presence = int(payload.get("min_presence_for_deduct") or 0)
    else:
        mode = getattr(shift, "rest_mode", None) or RestMode.FIXED
        minutes = int(getattr(shift, "rest_minutes", 0) or 0)
        min_presence = int((payload or {}).get("min_presence_for_deduct") or 0)
    if mode == RestMode.NONE:
        return 0
    if mode == RestMode.DEDUCT_IF_SHORT:
        return minutes if raw_presence < max(1, min_presence) else 0
    # RestMode.FIXED — full default deduction, capped at actual presence
    return min(minutes, raw_presence)


# ---------------------------------------------------------------------------
# Leave/mission spans (§8) — presence priority, no double counting
# ---------------------------------------------------------------------------
def split_leave_credit(spans: list[LeaveSpan], window, presence_intervals: list):
    """Split approved spans against the day window and valid presence.

    Returns (leave_by_type, mission_minutes, leave_total, mission_total)
    where totals EXCLUDE minutes covered by valid presence (presence wins).
    """
    w_start, w_end = window
    leave_by_type: dict[str, int] = {}
    mission_total = 0
    leave_total = 0

    def _credit(start, end, kind, type_code):
        minutes = overlap_minutes(start, end, w_start, w_end)
        if minutes <= 0:
            return 0
        covered = 0
        for p_start, p_end in presence_intervals:
            covered += overlap_minutes(start, end, p_start, p_end)
        net = max(0, minutes - covered)
        if net <= 0:
            return 0
        if kind == "MISSION":
            nonlocal mission_total
            mission_total += net
        else:
            nonlocal leave_total
            leave_total += net
            code = type_code or "UNKNOWN"
            leave_by_type[code] = leave_by_type.get(code, 0) + net
        return net

    for span in spans:
        s = max(span.start, w_start)
        e = min(span.end, w_end)
        if e > s:
            _credit(s, e, span.kind, span.type_code)
    return leave_by_type, mission_total, leave_total, mission_total


# ---------------------------------------------------------------------------
# The day calculation (§7)
# ---------------------------------------------------------------------------
def compute_day(
    *,
    employee_id: int,
    branch_id: int,
    shift_date: dt.date,
    sessions,
    scheduled_shift,
    leave_spans: list[LeaveSpan],
    resolver: RuleResolver,
    is_holiday: bool = False,
    overtime_approved_by_session: dict[int, int] | None = None,
) -> DayResult:
    """Pure daily calculation for one (employee × branch × shift_date).

    `sessions` must carry check_in_event/check_out_event (select_related).
    `scheduled_shift` may be None (برنامه‌ریزی‌نشده). Overtime approval state
    is injected so this function stays side-effect free.
    """
    overtime_approved_by_session = overtime_approved_by_session or {}
    shift = scheduled_shift.shift if scheduled_shift is not None else None
    window = day_window(scheduled_shift) if scheduled_shift is not None else (
        _local_midnight(shift_date), _local_midnight(shift_date) + dt.timedelta(days=1)
    )
    result = DayResult(
        employee_id=employee_id,
        branch_id=branch_id,
        shift_date=shift_date,
        scheduled_shift_id=scheduled_shift.id if scheduled_shift is not None else None,
        shift_code=shift.code if shift is not None else None,
        is_workday=shift is not None,
        is_holiday=is_holiday,
    )

    # --- presence intervals from COMPLETE sessions -------------------------
    presence: list[tuple[dt.datetime, dt.datetime]] = []
    for s in sessions:
        result.session_count += 1
        if s.session_state != SessionState.COMPLETE:
            result.incomplete_sessions += 1
            result.flags.append(f"SESSION_{s.session_state}")
            continue
        if s.check_in_event is None or s.check_out_event is None:
            result.incomplete_sessions += 1
            continue
        presence.append((s.check_in_event.effective_time, s.check_out_event.effective_time))
        result.session_overtime.append((s.id, s.check_out_event.effective_time))
    presence.sort()
    raw_presence = sum(
        int((e - s).total_seconds() // 60) for s, e in presence
    )
    result.valid_presence_minutes = max(0, raw_presence)
    if presence:
        result.first_in = presence[0][0]
        result.last_out = max(e for _, e in presence)

    # --- rules of this date -------------------------------------------------
    late_payload, late_rule = resolver.get(RuleKind.LATE, shift_date)
    early_payload, early_rule = resolver.get(RuleKind.EARLY_LEAVE, shift_date)
    rest_payload, rest_rule = resolver.get(RuleKind.REST, shift_date)
    ot_payload, ot_rule = resolver.get(RuleKind.OVERTIME, shift_date)
    absence_payload, absence_rule = resolver.get(RuleKind.ABSENCE, shift_date)
    resolver.get(RuleKind.HOLIDAY, shift_date)  # track usage/ids even for holidays
    result.rule_set_ids = resolver.used_rule_ids()

    # --- required minutes (ساعات موظفی) -------------------------------------
    if shift is not None and not is_holiday:
        span = int((window[1] - window[0]).total_seconds() // 60)
        rest_default = int(getattr(shift, "rest_minutes", 0) or 0)
        if rest_payload is not None and rest_payload.get("mode"):
            rest_default = int(rest_payload.get("default_minutes") or rest_default)
        result.required_minutes = max(0, span - rest_default)

    # --- work + rest deduction (§7.1) ---------------------------------------
    result.rest_minutes = apply_rest_rule(rest_payload, shift, result.valid_presence_minutes)
    result.accepted_work_minutes = max(0, result.valid_presence_minutes - result.rest_minutes)

    # --- late / early vs ABSOLUTE planned boundaries (§7.2) ------------------
    if shift is not None and presence:
        grace = late_payload.get("grace_minutes")
        if grace is None:
            grace = int(getattr(shift, "grace_minutes", 0) or 0)
        late_raw = int((presence[0][0] - window[0]).total_seconds() // 60) - int(grace)
        result.late_minutes, result.late_deduct_mode, result.late_deduction_minutes = (
            _apply_late_like(late_payload, max(0, late_raw), result.flags, "LATE")
        )

        early_grace = early_payload.get("grace_minutes")
        if early_grace is None:
            early_grace = int(getattr(shift, "grace_minutes", 0) or 0)
        last_out = max(e for _, e in presence)
        early_raw = int((window[1] - last_out).total_seconds() // 60) - int(early_grace)
        result.early_leave_minutes, _, _ = _apply_late_like(
            early_payload, max(0, early_raw), result.flags, "EARLY"
        )

    # --- overtime proposal basis (§7.3) — only beyond planned_end -----------
    if shift is not None:
        raw_ot = 0
        for session_id, out_time in result.session_overtime:
            beyond = int((out_time - window[1]).total_seconds() // 60)
            if beyond > 0:
                raw_ot += beyond
        if raw_ot > 0:
            raw_ot = _round_down(raw_ot, ot_payload.get("rounding_minutes", 1))
            max_daily = int(ot_payload.get("max_daily_minutes", 240) or 0)
            if max_daily > 0:
                raw_ot = min(raw_ot, max_daily)
            if raw_ot >= int(ot_payload.get("min_block_minutes", 30) or 0):
                result.overtime_proposed_minutes = raw_ot
                for sid, _ in result.session_overtime:
                    result.overtime_approved_minutes += int(
                        overtime_approved_by_session.get(sid, 0)
                    )
                if not ot_payload.get("requires_approval", True):
                    # HR explicitly disabled the approval gate for this period.
                    result.overtime_approved_minutes = result.overtime_proposed_minutes
                    result.flags.append("OVERTIME_AUTO_APPROVED")

    # --- leave / mission overlap (§7.1 + §8) ---------------------------------
    leave_by_type, mission_total, leave_total, _ = split_leave_credit(
        leave_spans, window, presence
    )
    result.leave_minutes_by_type = leave_by_type
    result.mission_minutes = mission_total

    # credits capped at the day obligation for shortage (§7.3)
    remaining = result.required_minutes - result.accepted_work_minutes
    result.leave_credit_minutes = max(0, min(leave_total, max(0, remaining)))
    remaining -= result.leave_credit_minutes
    result.mission_credit_minutes = max(0, min(mission_total, max(0, remaining)))

    # --- absence (§7.3) -------------------------------------------------------
    if result.required_minutes > 0 and not is_holiday:
        if not presence:
            if leave_total == 0 and mission_total == 0:
                result.absence_minutes = result.required_minutes
                result.flags.append("ABSENT")
        else:
            threshold = int(absence_payload.get("half_day_threshold_minutes", 180) or 0)
            if threshold > 0 and result.accepted_work_minutes < threshold:
                result.absence_minutes = result.required_minutes // 2
                result.flags.append("ABSENCE_HALF_DAY")
            no_show = int(absence_payload.get("no_show_minutes", 120) or 0)
            if no_show > 0 and presence and shift is not None:
                arrived_late = int((presence[0][0] - window[0]).total_seconds() // 60)
                if arrived_late > no_show:
                    # Conservative: flag for review — policy data pending (§12).
                    result.flags.append("NO_SHOW_RISK")

    if is_holiday:
        result.flags.append("HOLIDAY")
    return result
