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
SHEET_YEAR_TREND = "روند ماهانه"
SHEET_YEAR_PEOPLE = "خلاصه سالانه پرسنل"
SHEET_DISCIPLINARY = "انتظامی تأخیر و غیبت"

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

DISCIPLINARY_HEADERS = [
    "کد پرسنلی", "نام و نام خانوادگی", "شعبه", "دوره",
    "تعداد روز تأخیر", "جمع تأخیر (دقیقه)", "تعداد روز غیبت",
    "جمع غیبت (دقیقه)", "کسری (دقیقه)", "جلسات ناقص",
    "بدون موقعیت مکانی", "خارج از محدوده",
]

YEAR_TREND_HEADERS = [
    "ماه", "پرسنل", "دقیقه لازم", "کار پذیرفته", "تأخیر",
    "روز تأخیر", "غیبت", "روز غیبت", "کسری", "اضافه‌کار", "مرخصی (کل)",
]

YEAR_PEOPLE_HEADERS = [
    "کد پرسنلی", "نام و نام خانوادگی", "شعبه", "ماه‌های دارای رکورد",
    "جمع دقیقه لازم", "جمع کار پذیرفته", "جمع تأخیر", "جمع روز تأخیر",
    "جمع غیبت", "جمع روز غیبت", "جمع کسری", "جمع اضافه‌کار",
]

MAX_ROWS = 5000  # workbook hard cap — 8,500 staff × branches stays editable
JALALI_MONTH_NAMES = [
    "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند",
]


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
                "late_days": s.late_days,
                "early": s.early_leave_minutes,
                "absence": s.absence_minutes,
                "absence_days": s.absence_days,
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
        "late_days": sum(r["late_days"] for r in rows),
        "early_leave_minutes": sum(r["early"] for r in rows),
        "absence_minutes": sum(r["absence"] for r in rows),
        "absence_days": sum(r["absence_days"] for r in rows),
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


# ---------------------------------------------------------------------------
# Year-level + disciplinary workbooks (phase-2 step 8)
# ---------------------------------------------------------------------------
def year_summaries(jy: int, branch=None):
    """Persisted summaries of the whole Jalali year, branch-scoped when given.

    Annual reports read persisted rows by default (re-rolling 12 months ×
    8,500 staff on request is not a click-sized job) — the caller opts in to
    ?refresh=1 when HR really wants the full recompute.
    """
    qs = MonthlySummary.objects.filter(period_year=jy).select_related("employee", "branch")
    if branch is not None:
        qs = qs.filter(branch=branch)
    return qs.order_by("period_month", "branch__code", "employee__personnel_code")


def year_preview(jy: int, branch=None) -> dict:
    """12-month trend for the PWA chart — per-month totals of persisted rows."""
    rows = _summary_rows(year_summaries(jy, branch))
    row_field_of = {
        "required_minutes": "required",
        "accepted_work_minutes": "accepted_work",
        "late_minutes": "late",
        "late_days": "late_days",
        "absence_minutes": "absence",
        "absence_days": "absence_days",
        "shortage_minutes": "shortage",
        "overtime_minutes": "overtime",
        "leave_minutes": "leave_total",
    }
    months: dict[int, dict] = {}
    for r in rows:
        jm = int(r["period"].split("/")[1])
        entry = months.setdefault(
            jm,
            {
                "jm": jm,
                "month_name": JALALI_MONTH_NAMES[jm - 1],
                "employees": 0,
                **{key: 0 for key in row_field_of},
            },
        )
        entry["employees"] += 1
        for key, field in row_field_of.items():
            entry[key] += r[field]
    trend = sorted(months.values(), key=lambda m: m["jm"])
    return {
        "period_year": jy,
        "branch": branch.code if branch is not None else None,
        "rows": len(rows),
        "totals": {
            "employees": len({r["personnel_code"] for r in rows}),
            "required_minutes": sum(r["required"] for r in rows),
            "accepted_work_minutes": sum(r["accepted_work"] for r in rows),
            "late_minutes": sum(r["late"] for r in rows),
            "late_days": sum(r["late_days"] for r in rows),
            "absence_minutes": sum(r["absence"] for r in rows),
            "absence_days": sum(r["absence_days"] for r in rows),
            "shortage_minutes": sum(r["shortage"] for r in rows),
            "overtime_minutes": sum(r["overtime"] for r in rows),
        },
        "months": trend,
    }


def build_annual_report(jy: int, branch=None, *, generated_by: str = "") -> bytes:
    """Annual workbook — «روند ماهانه» totals + «خلاصه سالانه پرسنل» + «راهنما».

    Reads persisted MonthlySummary rows (refresh is the caller's explicit
    choice, since a 12-month recompute is not a click-sized job).
    """
    rows = _summary_rows(year_summaries(jy, branch))

    wb = Workbook()

    # --- Sheet 1: روند ماهانه ---------------------------------------------------
    ws = wb.active
    ws.title = SHEET_YEAR_TREND
    ws.sheet_view.rightToLeft = True
    ws.append(YEAR_TREND_HEADERS)
    per_month: dict[int, dict] = {}
    for r in rows:
        jm = int(r["period"].split("/")[1])
        entry = per_month.setdefault(
            jm,
            {
                "employees": set(), "required": 0, "accepted_work": 0, "late": 0,
                "late_days": 0, "absence": 0, "absence_days": 0,
                "shortage": 0, "overtime": 0, "leave_total": 0,
            },
        )
        entry["employees"].add(r["personnel_code"])
        for key in ("required", "accepted_work", "late", "late_days",
                    "absence", "absence_days", "shortage", "overtime", "leave_total"):
            entry[key] += r[key]
    for jm in sorted(per_month):
        e = per_month[jm]
        ws.append(
            [f"{JALALI_MONTH_NAMES[jm - 1]} ({jy}/{jm:02d})", len(e["employees"]),
             e["required"], e["accepted_work"], e["late"], e["late_days"],
             e["absence"], e["absence_days"], e["shortage"], e["overtime"],
             e["leave_total"]]
        )
    _style_header(ws, len(YEAR_TREND_HEADERS))
    _fit_columns(ws, [18, 8, 11, 12, 10, 10, 10, 10, 10, 12, 12])

    # --- Sheet 2: خلاصه سالانه پرسنل --------------------------------------------
    ws2 = wb.create_sheet(SHEET_YEAR_PEOPLE)
    ws2.sheet_view.rightToLeft = True
    ws2.append(YEAR_PEOPLE_HEADERS)
    per_person: dict[tuple[str, str], dict] = {}
    for r in rows:
        key = (r["personnel_code"], r["branch_code"])
        entry = per_person.setdefault(
            key,
            {
                "full_name": r["full_name"], "months": 0, "required": 0,
                "accepted_work": 0, "late": 0, "late_days": 0, "absence": 0,
                "absence_days": 0, "shortage": 0, "overtime": 0,
            },
        )
        entry["months"] += 1
        for key_f in ("required", "accepted_work", "late", "late_days",
                      "absence", "absence_days", "shortage", "overtime"):
            entry[key_f] += r[key_f]
    for (personnel_code, branch_code), e in sorted(per_person.items())[:MAX_ROWS]:
        ws2.append(
            [personnel_code, e["full_name"], branch_code, e["months"],
             e["required"], e["accepted_work"], e["late"], e["late_days"],
             e["absence"], e["absence_days"], e["shortage"], e["overtime"]]
        )
    _style_header(ws2, len(YEAR_PEOPLE_HEADERS))
    _fit_columns(ws2, [12, 22, 12, 10] + [12] * 8)

    # --- Sheet 3: راهنما --------------------------------------------------------
    ws3 = wb.create_sheet(SHEET_GUIDE)
    ws3.sheet_view.rightToLeft = True
    guide_rows = [
        ["گزارش سالانه حضور و غیاب — رز سفید"],
        ["سال شمسی", jy],
        ["شعبه", branch.name if branch is not None else "همهٔ شعب"],
        ["تعداد ردیف خلاصه", len(rows)],
        ["زمان تولید", _jalali_text(dt.date.today()) + (f" — {generated_by}" if generated_by else "")],
        [],
        ["توضیح"],
        ["این گزارش از خلاصه‌های ذخیره‌شدهٔ دوره‌ها می‌خواند (refresh=0)؛ برای محاسبهٔ مجدد کامل سال از پارامتر refresh=1 استفاده شود."],
        ["«روز تأخیر» تعداد روزهای دارای تأخیر پس از بخشش ماهانهٔ قاعدهٔ LATE است."],
        ["«روز غیبت» تعداد روزهای کاری با دقیقهٔ غیبت مثبت است."],
        ["ردیف‌های خلاصهٔ سالانه پرسنل = یک ردیف به‌ازای هر (پرسنل × شعبه) با رکورد در سال."],
    ]
    for row in guide_rows:
        ws3.append(row)
    ws3.column_dimensions["A"].width = 22
    ws3.column_dimensions["B"].width = 95
    ws3["A1"].font = Font(bold=True, size=13)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_disciplinary_report(jy: int, jm: int, branch=None, *, generated_by: str = "") -> bytes:
    """Monthly disciplinary workbook — late/absence occurrences per (person × branch).

    Same data contract as the monthly report (persisted summaries after the
    caller-refreshed rollup), focused on the entezami columns HR needs for
    disciplinary letters: occurrence counts + minutes + shortage.
    """
    rows = _summary_rows(month_summaries(jy, jm, branch))

    wb = Workbook()
    ws = wb.active
    ws.title = SHEET_DISCIPLINARY
    ws.sheet_view.rightToLeft = True
    ws.append(DISCIPLINARY_HEADERS)
    for r in rows:
        ws.append(
            [
                r["personnel_code"], r["full_name"], r["branch_code"], r["period"],
                r["late_days"], r["late"], r["absence_days"], r["absence"],
                r["shortage"], r["incomplete"], r["no_location"], r["out_of_range"],
            ]
        )
    _style_header(ws, len(DISCIPLINARY_HEADERS))
    _fit_columns(ws, [12, 22, 12, 10, 12, 13, 12, 13, 12, 10, 13, 13])

    ws2 = wb.create_sheet(SHEET_GUIDE)
    ws2.sheet_view.rightToLeft = True
    guide_rows = [
        ["گزارش انتظامی تأخیر و غیبت — رز سفید"],
        ["دوره (شمسی)", _period_text(jy, jm)],
        ["شعبه", branch.name if branch is not None else "همهٔ شعب"],
        ["زمان تولید", _jalali_text(dt.date.today()) + (f" — {generated_by}" if generated_by else "")],
        [],
        ["ستون", "توضیح"],
        ["تعداد روز تأخیر", "روزهای با تأخیر مثبت پس از بخشش ماهانه (قاعدهٔ LATE)"],
        ["جمع تأخیر", "مجموع دقیقهٔ تأخیر دوره"],
        ["تعداد روز غیبت", "روزهای کاری بدون تردد پذیرفته"],
        ["جمع غیبت", "مجموع دقیقهٔ غیبت دوره"],
        ["کسری", "max(0، لازم − کار پذیرفته − اعتبار مرخصی − مأموریت − غیبت)"],
        ["جلسات ناقص", "بازه‌های OPEN / INVALID_SEQUENCE (نیازمند رسیدگی)"],
        ["بدون موقعیت / خارج از محدوده", "برچسب‌های مکانی رویدادها (قاعدهٔ مصوب: برچسب، نه رد)"],
        [],
        ["این گزارش با همان رول‌آپ تکرارپذیر گزارش ماهانه ساخته می‌شود و پس از بستن دوره ثابت است."],
    ]
    for row in guide_rows:
        ws2.append(row)
    ws2.column_dimensions["A"].width = 24
    ws2.column_dimensions["B"].width = 90
    ws2["A1"].font = Font(bold=True, size=13)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
