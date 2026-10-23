"""HR monthly Excel export — گزارش ماهانه HR (فاز ۲، گام ۶).

Two deliverables on top of the existing rollup engine (services.py):
- JSON preview for the PWA — per-branch totals without downloading anything
- xlsx workbook: «خلاصه ماهانه» per (person × branch) row, «مانده مرخصی»
  snapshot per (person × tracked leave type) and «راهنما»

Rules honoured:
- rollup unit is (person × branch × Jalali month); the workbook never
  re-computes anything, it only reads MonthlySummary rows (§7.4)
- refresh re-runs the repeatable rollup first (§2) unless the caller opts out
- balances come straight from the append-only LeaveLedger stream (§11) —
  SUM(minutes) per (employee, leave_type), one grouped query
- access is HR/ADMIN/superuser, the same guard as ledger seeding
"""
from __future__ import annotations

import datetime as dt
import io

import jdatetime
from django.db.models import Count, Sum
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

from apps.core.api_utils import hm_minutes
from apps.core.jalali import jalali_month_range
from apps.leaves.models import LeaveLedger, LeaveType

from .models import MonthlySummary
from .services import recompute_month

SHEET_SUMMARY = "خلاصه ماهانه"
SHEET_BALANCES = "مانده مرخصی"
SHEET_GUIDE = "راهنما"

SUMMARY_HEADERS = [
    "کد پرسنلی", "نام و نام خانوادگی", "شعبه", "دوره",
    "دقیقه لازم", "کار پذیرفته", "حضور معتبر", "تأخیر", "تعجیل",
    "غیبت", "کسری", "اضافه‌کار تأییدشده", "مأموریت", "مرخصی (کل)",
    "جلسات ناقص", "بدون موقعیت مکانی", "خارج از محدوده", "وضعیت",
]

BALANCE_HEADERS = [
    "کد پرسنلی", "نام و نام خانوادگی", "نوع مرخصی", "کد نوع",
    "مانده (دقیقه)", "مانده (ساعت)", "تعداد گردش",
]

MAX_ROWS = 5000  # workbook hard cap — 8,500 staff × branches stays editable


def _jalali_text(date: dt.date) -> str:
    j = jdatetime.date.fromgregorian(date=date)
    return f"{j.year}/{j.month:02d}/{j.day:02d}"


def _period_text(jy: int, jm: int) -> str:
    return f"{jy}/{jm:02d}"


def _state_text(state: str) -> str:
    return "نهایی (بسته)" if state == "FINAL" else "پیش‌نویس"


def month_summaries(jy: int, jm: int, branch=None):
    """Persisted summaries of the period, branch-scoped when given."""
    qs = MonthlySummary.objects.filter(period_year=jy, period_month=jm).select_related(
        "employee", "branch"
    )
    if branch is not None:
        qs = qs.filter(branch=branch)
    return qs.order_by("branch__code", "employee__personnel_code")


def ensure_refreshed(jy: int, jm: int, branch=None, refresh: bool = True) -> None:
    """Re-run the repeatable rollup so the report reflects live data."""
    if refresh:
        recompute_month(jy, jm, branch_id=branch.id if branch is not None else None)


def _summary_rows(summaries) -> list[dict]:
    """Flatten MonthlySummary rows → dicts shared by preview and the workbook."""
    rows = []
    for s in summaries[:MAX_ROWS]:
        leave_total = sum(s.leave_minutes_by_type.values()) if s.leave_minutes_by_type else 0
        rows.append(
            {
                "employee_id": s.employee_id,
                "personnel_code": s.employee.personnel_code,
                "full_name": s.employee.full_name,
                "branch_code": s.branch.code,
                "period": _period_text(s.period_year, s.period_month),
                "required": s.required_minutes,
                "accepted_work": s.accepted_work_minutes,
                "valid_presence": s.valid_presence_minutes,
                "late": s.late_minutes,
                "early": s.early_leave_minutes,
                "absence": s.absence_minutes,
                "shortage": s.shortage_minutes,
                "overtime": s.overtime_minutes,
                "mission": s.mission_minutes,
                "leave_total": leave_total,
                "leave_by_type": s.leave_minutes_by_type or {},
                "incomplete": s.incomplete_session_count,
                "no_location": s.no_location_count,
                "out_of_range": s.out_of_range_count,
                "state": s.summary_state,
            }
        )
    return rows


def month_preview(jy: int, jm: int, branch=None) -> dict:
    """Per-branch totals for the PWA dashboard (no file generated)."""
    rows = _summary_rows(month_summaries(jy, jm, branch))

    totals = {
        "employees": len({r["personnel_code"] for r in rows}),
        "required_minutes": sum(r["required"] for r in rows),
        "accepted_work_minutes": sum(r["accepted_work"] for r in rows),
        "late_minutes": sum(r["late"] for r in rows),
        "early_leave_minutes": sum(r["early"] for r in rows),
        "absence_minutes": sum(r["absence"] for r in rows),
        "shortage_minutes": sum(r["shortage"] for r in rows),
        "overtime_minutes": sum(r["overtime"] for r in rows),
        "mission_minutes": sum(r["mission"] for r in rows),
        "leave_minutes": sum(r["leave_total"] for r in rows),
        "final_count": sum(1 for r in rows if r["state"] == "FINAL"),
    }

    by_branch: dict[str, dict] = {}
    field_of = {
        "required_minutes": "required",
        "accepted_work_minutes": "accepted_work",
        "late_minutes": "late",
        "absence_minutes": "absence",
        "shortage_minutes": "shortage",
        "overtime_minutes": "overtime",
        "leave_minutes": "leave_total",
    }
    for r in rows:
        entry = by_branch.setdefault(
            r["branch_code"],
            {
                "branch": r["branch_code"],
                "employees": 0,
                **{key: 0 for key in field_of},
            },
        )
        entry["employees"] += 1
        for key, field in field_of.items():
            entry[key] += r[field]

    return {
        "period": {"jy": jy, "jm": jm},
        "branch": branch.code if branch is not None else None,
        "rows": len(rows),
        "totals": totals,
        "by_branch": sorted(by_branch.values(), key=lambda item: item["branch"]),
    }


def _style_header(ws, ncols: int) -> None:
    for col in range(1, ncols + 1):
        cell = ws.cell(row=1, column=col)
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="right")
    ws.freeze_panes = "A2"


def _fit_columns(ws, widths: list[int]) -> None:
    for idx, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = width


def build_monthly_report(jy: int, jm: int, branch=None, *, generated_by: str = "") -> bytes:
    """The xlsx workbook — three sheets, right-to-left, Persian headers."""
    first_day, last_day = jalali_month_range(jy, jm)
    rows = _summary_rows(month_summaries(jy, jm, branch))

    leave_types = list(LeaveType.objects.filter(is_active=True).order_by("id"))
    used_codes = [t.code for t in leave_types if any(t.code in r["leave_by_type"] for r in rows)]

    emp_map = {
        row["employee_id"]: row
        for row in MonthlySummary.objects.filter(
            period_year=jy, period_month=jm,
            **({"branch": branch} if branch is not None else {}),
        ).select_related("employee").values(
            "employee_id", "employee__personnel_code",
            "employee__first_name", "employee__last_name",
        )
    }

    wb = Workbook()

    # --- Sheet 1: خلاصه ماهانه -------------------------------------------------
    ws = wb.active
    ws.title = SHEET_SUMMARY
    ws.sheet_view.rightToLeft = True
    headers = SUMMARY_HEADERS[:-1] + [f"مرخصی {code}" for code in used_codes] + [SUMMARY_HEADERS[-1]]
    ws.append(headers)
    for r in rows:
        ws.append(
            [
                r["personnel_code"], r["full_name"], r["branch_code"], r["period"],
                r["required"], r["accepted_work"], r["valid_presence"],
                r["late"], r["early"], r["absence"], r["shortage"],
                r["overtime"], r["mission"], r["leave_total"],
                *[r["leave_by_type"].get(code, 0) for code in used_codes],
                r["incomplete"], r["no_location"], r["out_of_range"],
                _state_text(r["state"]),
            ]
        )
    _style_header(ws, len(headers))
    _fit_columns(ws, [12, 22, 12, 10] + [11] * 10 + [11] * len(used_codes) + [10, 12, 12, 13])

    # --- Sheet 2: مانده مرخصی --------------------------------------------------
    ws2 = wb.create_sheet(SHEET_BALANCES)
    ws2.sheet_view.rightToLeft = True
    ws2.append(BALANCE_HEADERS)
    employee_ids = list(emp_map)
    if employee_ids:
        sums = (
            LeaveLedger.objects.filter(employee_id__in=employee_ids)
            .values("employee_id", "leave_type__code", "leave_type__name")
            .annotate(total=Sum("minutes"), entries=Count("id"))
            .order_by("employee_id", "leave_type__code")
        )
        for s in sums:
            info = emp_map.get(s["employee_id"], {})
            total = int(s["total"] or 0)
            ws2.append(
                [
                    info.get("employee__personnel_code", ""),
                    f"{info.get('employee__first_name', '')} {info.get('employee__last_name', '')}".strip(),
                    s["leave_type__name"],
                    s["leave_type__code"],
                    total,
                    hm_minutes(total),
                    s["entries"],
                ]
            )
    _style_header(ws2, len(BALANCE_HEADERS))
    _fit_columns(ws2, [12, 22, 18, 14, 14, 12, 10])

    # --- Sheet 3: راهنما -------------------------------------------------------
    ws3 = wb.create_sheet(SHEET_GUIDE)
    ws3.sheet_view.rightToLeft = True
    guide_rows = [
        ["گزارش ماهانه حضور و غیاب — رز سفید"],
        ["دوره (شمسی)", _period_text(jy, jm)],
        ["بازه میلادی", f"{first_day.isoformat()} تا {last_day.isoformat()}"],
        ["شعبه", branch.name if branch is not None else "همهٔ شعب"],
        ["زمان تولید", _jalali_text(dt.date.today()) + (f" — {generated_by}" if generated_by else "")],
        [],
        ["ستون", "توضیح"],
        ["دقیقه لازم", "جمع تکلیف شیفت‌های زمان‌بندی‌شده در دوره (شعبه × پرسنل)"],
        ["کار پذیرفته", "کارکرد تأییدشده پس از کسر استراحت"],
        ["تأخیر / تعجیل", "جمع دقیقهٔ تأخیر ورود و تعجیل خروج"],
        ["غیبت", "دقیقهٔ غیبت (روز کاری بدون تردد)"],
        ["کسری", "max(0، لازم − کار پذیرفته − اعتبار مرخصی − مأموریت − غیبت)"],
        ["اضافه‌کار", "فقط پیشنهادهای تأییدشده (§7.3)"],
        ["مرخصی {کد}", "به تفکیک نوع مرخصی از segments تأییدشده"],
        ["وضعیت", "پیش‌نویس تا بستن دوره؛ پس از close_month نهایی می‌شود"],
        ["مانده (دقیقه)", "SUM گردش‌های دفتر مانده؛ اصلاح فقط با گردش ADJUST جدید"],
        [],
        ["برگهٔ «مانده مرخصی» عکس لحظه‌ای دفتر است و گردش‌های آینده را پیش‌بینی نمی‌کند."],
    ]
    for row in guide_rows:
        ws3.append(row)
    ws3.column_dimensions["A"].width = 20
    ws3.column_dimensions["B"].width = 90
    ws3["A1"].font = Font(bold=True, size=13)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
