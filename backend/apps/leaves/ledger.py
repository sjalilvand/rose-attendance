"""LeaveLedger activation — the append-only balance stream goes live (§11).

Until this module the ledger table existed but stayed silent (see the old
services.py note: opening balances awaited HR input). It is now wired
end-to-end:

- HR seeds OPENING / ACCRUAL / ADJUST entries — bulk JSON with dry-run
  (leaves/api.LeaveLedgerViewSet.seed); the stream stays append-only, so
  corrections are *new* entries (ADJUST), never edits or deletes
- approving a LEAVE segment appends a DEDUCTION (−computed_minutes) atomically
  with the decision (hooked in services.decide_segment)
- a leave type becomes "tracked" for an employee once its first entry exists;
  untracked (employee, type) pairs never block submission — sick leave etc.
  can stay unmanaged
- the authoritative balance is SUM(minutes) of the stream (race-safe under
  concurrent decisions); the stored balance_after_minutes is a running
  display convenience, recomputed from the current sum at each append

Restores (REJECT after approve) don't exist yet: segments are decided once
and cancellation only works on PENDING, so there is no approval-reversal
path. If HR voids a wrong approval, a positive ADJUST entry is the answer.
"""
from __future__ import annotations

import datetime as dt

import jdatetime
from django.db import transaction
from django.db.models import Max, Sum
from django.utils import timezone

from apps.core.api_utils import hm_minutes
from apps.core.enums import ApprovalAction, LeaveEntryKind

from .models import LeaveLedger, LeaveType

SEED_KINDS = (LeaveEntryKind.OPENING, LeaveEntryKind.ACCRUAL, LeaveEntryKind.ADJUST)
MAX_SEED_ROWS = 10000


class LedgerError(Exception):
    """Domain error surfaced as a coded API response (mirrors RequestError)."""

    def __init__(self, message: str, code: str = "INVALID"):
        super().__init__(message)
        self.message = message
        self.code = code


def parse_basis_date(value) -> dt.date | None:
    """Jalali `1404-01-01` / `1404/01/01` first, then ISO — HR speaks Jalali."""
    if value in (None, ""):
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    text = str(value).strip()
    normalized = text.replace("/", "-")
    parts = normalized.split("-")
    if len(parts) == 3:
        try:
            jy, jm, jd = (int(p) for p in parts)
            if 1300 <= jy <= 1500:  # شمسی
                return jdatetime.date(jy, jm, jd).togregorian()
        except ValueError:
            pass
    try:
        return dt.date.fromisoformat(normalized)
    except ValueError as exc:
        raise LedgerError(f"تاریخ نامعتبر است: {text}") from exc


def current_balance_minutes(employee, leave_type) -> int:
    row = LeaveLedger.objects.filter(employee=employee, leave_type=leave_type).aggregate(
        total=Sum("minutes")
    )
    return int(row["total"] or 0)


def is_tracked(employee, leave_type) -> bool:
    return LeaveLedger.objects.filter(employee=employee, leave_type=leave_type).exists()


def append_entry(
    *,
    employee,
    leave_type,
    entry_kind: str,
    minutes: int,
    basis_date: dt.date,
    source_type: str = "",
    source_id: int | None = None,
) -> LeaveLedger:
    """Single append with running balance — used by decisions and adjust."""
    with transaction.atomic():
        base = current_balance_minutes(employee, leave_type)
        return LeaveLedger.objects.create(
            employee=employee,
            leave_type=leave_type,
            entry_kind=entry_kind,
            minutes=minutes,
            balance_after_minutes=base + minutes,
            basis_date=basis_date,
            source_type=source_type or "",
            source_id=source_id,
        )


def enforce_sufficient_balance(employee, leave_type, minutes: int) -> None:
    """Submission-time guard — raises LedgerError(INSUFFICIENT_BALANCE).

    Silent pass for untracked (employee, type) pairs: seeding is opt-in per
    type, so HR chooses which types carry numeric balances (ANNUAL typically)
    and which don't (SICK, UNPAID…).
    """
    if not is_tracked(employee, leave_type):
        return
    balance = current_balance_minutes(employee, leave_type)
    if balance < minutes:
        raise LedgerError(
            f"ماندهٔ {leave_type.name} کافی نیست (ماندهٔ فعلی: {hm_minutes(balance)}).",
            "INSUFFICIENT_BALANCE",
        )


def apply_segment_decision(segment, action: str) -> None:
    """Ledger side-effect of a segment decision — call inside the same tx.

    Only LEAVE × APPROVE touches the stream: −computed_minutes, anchored to
    the segment's start date and traced back to RequestSegment.<id>.
    """
    if action != ApprovalAction.APPROVE or segment.request_kind != "LEAVE":
        return
    leave_request = segment.leave_request
    append_entry(
        employee=leave_request.employee,
        leave_type=leave_request.leave_type,
        entry_kind=LeaveEntryKind.DEDUCTION,
        minutes=-int(segment.computed_minutes),
        basis_date=timezone.localtime(segment.starts_at).date(),
        source_type="RequestSegment",
        source_id=segment.id,
    )


def balances_for(employee) -> list[dict]:
    """Per-active-type balances for one employee (tracked ones carry sums)."""
    from django.db.models import Count

    rows = (
        LeaveLedger.objects.filter(employee=employee)
        .values("leave_type_id")
        .annotate(total=Sum("minutes"), entries=Count("id"), last_basis=Max("basis_date"))
    )
    by_type = {row["leave_type_id"]: row for row in rows}

    out: list[dict] = []
    for leave_type in LeaveType.objects.filter(is_active=True).order_by("id"):
        row = by_type.get(leave_type.id)
        out.append(
            {
                "leave_type": leave_type.code,
                "leave_type_name": leave_type.name,
                "is_hourly": leave_type.is_hourly,
                "tracked": row is not None,
                "balance_minutes": int(row["total"] or 0) if row else None,
                "entries": row["entries"] if row else 0,
                "last_basis_date": row["last_basis"] if row else None,
            }
        )
    return out
