"""Bulk personnel import — Excel (xlsx) via openpyxl (phase-3 HR item).

One-shot onboarding of the workforce (≈8,500 staff) with home branch and an
optional default shift expressed through the scheduling domain as a
branch-scoped 1-day cycle ShiftPattern (IMP-* codes).

Contract:
- upsert by personnel_code — existing rows are updated, new rows are created
- per-row validation — bad rows are reported and skipped, good rows still land
- dry_run=True validates the whole workbook without touching the database
- dates accept Jalali (شمسی) yyyy-mm-dd or yyyy/mm/dd plus ISO Gregorian and
  native Excel date cells
"""
from __future__ import annotations

import datetime as dt
import io

import jdatetime
from django.db import transaction
from django.utils import timezone
from openpyxl import Workbook, load_workbook
from openpyxl.utils import get_column_letter

from apps.core.enums import EmploymentStatus
from apps.orgs.models import Branch
from apps.people.models import Employee
from apps.scheduling.models import Shift, ShiftPattern, ShiftPatternItem

HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "personnel_code": ("personnel_code", "کد پرسنلی"),
    "first_name": ("first_name", "نام"),
    "last_name": ("last_name", "نام خانوادگی"),
    "national_id": ("national_id", "کد ملی"),
    "mobile": ("mobile", "موبایل"),
    "job_title": ("job_title", "عنوان شغلی"),
    "employment_status": ("employment_status", "وضعیت اشتغال"),
    "hired_on": ("hired_on", "تاریخ استخدام"),
    "branch_code": ("branch_code", "کد شعبه"),
    "shift_code": ("shift_code", "کد شیفت"),
}
REQUIRED_FIELDS = ("personnel_code", "first_name", "last_name", "branch_code")
TEMPLATE_ORDER = list(HEADER_ALIASES)
STATUS_VALUES = {value for value, _label in EmploymentStatus.choices}
MAX_REPORT_ERRORS = 50


class ImportFormatError(Exception):
    """Workbook-level problem (unreadable file, missing required headers)."""


def build_template() -> bytes:
    """Xlsx template — sample row plus a Persian instructions sheet."""
    wb = Workbook()
    ws = wb.active
    ws.title = "پرسنل"
    ws.append(TEMPLATE_ORDER)
    ws.append(
        ["12345", "علی", "رضایی", "0012345678", "09121234567",
         "کارمند جلسه", "ACTIVE", "1404-01-15", "B100", "SHIFT-M"]
    )
    widths = (14, 16, 20, 14, 15, 20, 18, 15, 12, 12)
    for col, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(col)].width = width

    guide = wb.create_sheet("راهنما")
    guide.append(["ستون", "الزام", "توضیح"])
    for row in [
        ("personnel_code", "الزامی", "کد پرسنلی یکتا؛ کلید به‌روزرسانی ردیف‌های تکراری (ستون را متنی نگه دارید)"),
        ("first_name", "الزامی", "نام"),
        ("last_name", "الزامی", "نام خانوادگی"),
        ("national_id", "اختیاری", "کد ملی ۱۰ رقمی"),
        ("mobile", "اختیاری", "موبایل ۱۱ رقمی"),
        ("job_title", "اختیاری", "عنوان شغلی"),
        ("employment_status", "اختیاری", "ACTIVE / SUSPENDED / TERMINATED — پیش‌فرض ACTIVE"),
        ("hired_on", "اختیاری", "تاریخ شمسی 1404-01-15 یا 1404/01/15 یا میلادی ISO"),
        ("branch_code", "الزامی", "کد شعبهٔ موجود در سامانه (سامانه شعبه را نمی‌سازد)"),
        ("shift_code", "اختیاری", "کد شیفت موجود؛ به‌صورت الگوی شمسی سطح شعبه ثبت می‌شود (کد IMP-...)"),
    ]:
        guide.append(list(row))
    for col, width in zip("ABC", (22, 10, 80)):
        guide.column_dimensions[col].width = width

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _cell_text(value) -> str | None:
    """Cell → stripped text; integral floats lose the trailing .0 (Excel quirk)."""
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    text = str(value).strip()
    return text or None


def _parse_date(value) -> dt.date | None:
    if value in (None, ""):
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    text = _cell_text(value) or ""
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
        raise ValueError(f"تاریخ نامعتبر است: {text}") from exc


def import_employees(data: bytes, *, dry_run: bool = False) -> dict:
    """Upsert employees from an xlsx workbook; returns a row-level report."""
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # openpyxl raises a zoo of exception types
        raise ImportFormatError("فایل قابل خواندن نیست؛ قالب xlsx الزامی است.") from exc

    errors: list[dict] = []
    total_rows = 0
    try:
        ws = wb.worksheets[0]
        rows = ws.iter_rows(values_only=True)
        try:
            header = list(next(rows))
        except StopIteration as exc:
            raise ImportFormatError("کاربرگ خالی است.") from exc

        canonical: dict[str, int] = {}
        for idx, raw in enumerate(header):
            text = _cell_text(raw)
            if text is None:
                continue
            key = text.lower()
            for canon, aliases in HEADER_ALIASES.items():
                if key in aliases and canon not in canonical:
                    canonical[canon] = idx
        missing = [name for name in REQUIRED_FIELDS if name not in canonical]
        if missing:
            raise ImportFormatError("ستون‌های الزامی یافت نشد: " + "، ".join(missing))

        branch_map = {b.code: b for b in Branch.objects.all()}
        shift_map = {s.code: s for s in Shift.objects.all()}
        existing = {e.personnel_code: e for e in Employee.objects.all()}

        seen_codes: set[str] = set()
        to_create: list[Employee] = []
        to_update: list[Employee] = []
        created_would = 0  # reported in both modes ("would create" in dry run)
        updated_would = 0
        pattern_cache: dict[tuple[str, str], bool] = {}

        for n, raw_row in enumerate(rows, start=2):  # header is row 1
            row = {name: raw_row[idx] if idx < len(raw_row) else None for name, idx in canonical.items()}
            if all(value in (None, "") for value in row.values()):
                continue  # fully empty line
            total_rows += 1

            code = _cell_text(row.get("personnel_code"))
            if code is None:
                errors.append({"row": n, "personnel_code": "", "message": "کد پرسنلی الزامی است."})
                continue
            if code in seen_codes:
                errors.append({"row": n, "personnel_code": code, "message": "کد پرسنلی در فایل تکراری است."})
                continue
            seen_codes.add(code)

            first = _cell_text(row.get("first_name"))
            last = _cell_text(row.get("last_name"))
            if not first or not last:
                errors.append({"row": n, "personnel_code": code, "message": "نام و نام خانوادگی الزامی است."})
                continue

            branch_code = _cell_text(row.get("branch_code"))
            branch = branch_map.get(branch_code or "")
            if branch is None:
                errors.append({"row": n, "personnel_code": code, "message": f"شعبهٔ «{branch_code}» یافت نشد."})
                continue

            status_raw = _cell_text(row.get("employment_status")) or EmploymentStatus.ACTIVE
            if status_raw not in STATUS_VALUES:
                errors.append({"row": n, "personnel_code": code, "message": f"وضعیت اشتغال نامعتبر است: {status_raw}"})
                continue

            try:
                hired = _parse_date(row.get("hired_on"))
            except ValueError as exc:
                errors.append({"row": n, "personnel_code": code, "message": str(exc)})
                continue

            shift_code = _cell_text(row.get("shift_code"))
            if shift_code and shift_code not in shift_map:
                errors.append({"row": n, "personnel_code": code, "message": f"شیفت «{shift_code}» یافت نشد."})
                continue

            fields = {
                "first_name": first,
                "last_name": last,
                "national_id": _cell_text(row.get("national_id")) or "",
                "mobile": _cell_text(row.get("mobile")) or "",
                "job_title": _cell_text(row.get("job_title")) or "",
                "employment_status": status_raw,
            }
            current = existing.get(code)
            if current is None:
                created_would += 1
                if not dry_run:
                    to_create.append(
                        Employee(personnel_code=code, home_branch=branch, hired_on=hired, **fields)
                    )
            else:
                updated_would += 1
                if not dry_run:
                    for key, value in fields.items():
                        setattr(current, key, value)
                    current.home_branch = branch
                    if hired is not None:
                        current.hired_on = hired
                    to_update.append(current)

            if shift_code and not dry_run:
                key = (branch.code, shift_code)
                if not pattern_cache.get(key):
                    pattern, _ = ShiftPattern.objects.get_or_create(
                        code=f"IMP-{branch.code}-{shift_code}",
                        defaults={
                            "name": f"الگوی واردشده {branch.code} / {shift_code}",
                            "cycle_length_days": 1,
                            "start_on_date": timezone.localdate(),
                            "branch": branch,
                        },
                    )
                    ShiftPatternItem.objects.get_or_create(
                        pattern=pattern, day_index=1,
                        defaults={"shift": shift_map[shift_code]},
                    )
                    pattern_cache[key] = True

        if not dry_run:
            with transaction.atomic():
                if to_create:
                    Employee.objects.bulk_create(to_create, batch_size=500)
                if to_update:
                    Employee.objects.bulk_update(
                        to_update,
                        fields=["first_name", "last_name", "national_id", "mobile",
                                "job_title", "employment_status", "home_branch", "hired_on"],
                        batch_size=500,
                    )
    finally:
        wb.close()

    return {
        "total": total_rows,
        "created": created_would,
        "updated": updated_would,
        "skipped": len(errors),
        "errors": errors[:MAX_REPORT_ERRORS],
        "dry_run": dry_run,
    }
