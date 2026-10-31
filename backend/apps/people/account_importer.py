"""Bulk import of personnel WITH login accounts from a simple Excel sheet.

کاربرد اصلی: ورود گروهی اسامی (مثل مشاورین) —
نام کاربری = کد ملی، گذرواژه = شمارهٔ موبایل.

ستون‌های شناسایی‌شده (متحمل به تفاوت عنوان‌ها؛ ارقام فارسی/عربی خودکار
به لاتین تبدیل می‌شوند):
- «نام و نام خانوادگی» یکجا، یا «نام» + «نام خانوادگی» جدا
- «کد ملی» — الزامی؛ نام کاربری حساب
- «شماره تماس» / «موبایل» / «تلفن همراه» — الزامی؛ گذرواژهٔ اولیه
- «کد تفضیلی» یا «کد پرسنلی» — اختیاری؛ کد پرسنلی (در نبودش کد ملی)
- «استان» / «شماره شبا» و بقیه — نادیده گرفته می‌شود

هر ردیف در یک تراکنش ساخته می‌شود (Employee + User). اجرای دوباره امن است:
ردیف‌هایی که کد پرسنلی یا نام کاربری‌شان موجود باشد «تکراری» گزارش می‌شوند
و دست نمی‌خورند. dry_run=True کل فایل را اعتبارسنجی می‌کند بدون نوشتن در DB.
"""
from __future__ import annotations

import io
import re

from django.db import transaction
from openpyxl import load_workbook

from apps.core.enums import EmploymentStatus
from apps.orgs.models import Branch, Region

from .models import Employee, User

MAX_REPORT_ROWS = 50

# عنوان‌های پذیرفته برای هر ستون — اولین تطبیق برنده است
_NID_ALIASES = ("کد ملی", "کدملی", "national_id", "national id", "nationalid")
_MOBILE_ALIASES = ("موبایل", "شماره موبایل", "همراه", "شماره تماس", "تماس", "تلفن همراه", "تلفن", "mobile", "phone")
_PERSONNEL_ALIASES = ("کد تفضیلی", "کدتفضیلی", "کد پرسنلی", "کدپرسنلی", "personnel_code")
_PROVINCE_ALIASES = ("استان", "province")
_COMBINED_NAME_EXACT = ("نام و نام خانوادگی", "نام‌ و نام‌ خانوادگی", "نام کامل", "نام و نام خانوادگي", "full name")

_DIGIT_MAP = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_DIGITS_RE = re.compile(r"\d+")


class AccountImportFormatError(Exception):
    """مشکل در سطح فایل (خوانا نیست، ستون الزامی نیست)."""


def _norm_header(text: str) -> str:
    """عنوان ستون را برای مقایسه یکسان‌سازی می‌کند (ی/ک عربی→فارسی، نیم‌فاصله، فاصله‌ها)."""
    t = text.translate(_DIGIT_MAP)
    t = t.replace("\u200c", " ").replace("ي", "ی").replace("ك", "ک")
    return " ".join(t.lower().split()).strip()


def _cell_text(value) -> str | None:
    """Cell → متن تمیز؛ float صحیح بدون .0 انتهایی."""
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    text = str(value).strip()
    return text or None


def _ascii_digits(text: str) -> str:
    """ارقام فارسی/عربی → لاتین."""
    return text.translate(_DIGIT_MAP)


def _only_digits(text: str) -> str:
    return "".join(_DIGITS_RE.findall(_ascii_digits(text)))


def normalize_nid(raw) -> tuple[str | None, str | None]:
    """کد ملی → (مقدار ۱۰ رقمی، خطا). صفرهای ابتدایی جبران می‌شود."""
    text = _cell_text(raw)
    if text is None:
        return None, "کد ملی در فایل خالی است."
    digits = _only_digits(text)
    if not digits:
        return None, f"کد ملی نامعتبر است: «{text}»"
    if len(digits) > 10:
        return None, f"کد ملی باید ۱۰ رقم باشد ({len(digits)} رقم): «{text}»"
    return digits.zfill(10), None


def normalize_mobile(raw) -> tuple[str | None, str | None]:
    """موبایل → (۰۹xxxxxxxxx، خطا). پیش‌شماره ۹۸ و صفرِ افتاده جبران می‌شود."""
    text = _cell_text(raw)
    if text is None:
        return None, "شماره موبایل در فایل خالی است."
    digits = _only_digits(text)
    if not digits:
        return None, f"شماره موبایل نامعتبر است: «{text}»"
    if len(digits) == 12 and digits.startswith("98"):
        digits = "0" + digits[2:]
    if len(digits) == 10 and digits.startswith("9"):
        digits = "0" + digits
    if not re.fullmatch(r"09\d{9}", digits):
        return None, f"شماره موبایل باید ۱۱ رقم و با ۰۹ شروع شود: «{text}»"
    return digits, None


def split_full_name(full: str) -> tuple[str, str]:
    """«نام و نام خانوادگی» → (نام، نام خانوادگی): واژهٔ اول نام، بقیه نام خانوادگی."""
    parts = full.split()
    if len(parts) == 1:
        return "", parts[0]
    return parts[0], " ".join(parts[1:])


def _pick_columns(header: list[str | None]) -> dict[str, int]:
    """نگاشت ستون‌های منطقی از روی عنوان‌ها؛ در نبود ستون الزامی خطا می‌دهد."""
    norm = [_norm_header(h) if h else "" for h in header]

    def find(aliases: tuple[str, ...]) -> int:
        for alias in aliases:
            a = _norm_header(alias)
            for idx, h in enumerate(norm):
                if h and a in h:
                    return idx
        return -1

    cols: dict[str, int] = {}
    cols["nid"] = find(_NID_ALIASES)
    cols["mobile"] = find(_MOBILE_ALIASES)
    cols["personnel_code"] = find(_PERSONNEL_ALIASES)
    cols["province"] = find(_PROVINCE_ALIASES)

    # نام: اول ستون‌های جدا (نام / نام خانوادگی)، وگرنه ستون یکجا
    first_idx = -1
    last_idx = -1
    combined_idx = -1
    for idx, h in enumerate(norm):
        if not h:
            continue
        if h == "نام" and first_idx < 0:
            first_idx = idx
        elif (h == "نام خانوادگی" or h.startswith("نام خانوادگی ")) and last_idx < 0:
            last_idx = idx
        elif any(h == _norm_header(a) for a in _COMBINED_NAME_EXACT) and combined_idx < 0:
            combined_idx = idx
    if combined_idx < 0 and "نام" in " ".join(norm):
        # عنوانِ یکجا با عبارت دقیق نبود؛ هر ستونی که «نام» دارد و نام/نام خانوادگی نیست
        for idx, h in enumerate(norm):
            if h and "نام" in h and idx not in (first_idx, last_idx) and "ملی" not in h:
                combined_idx = idx
                break
    cols["first_name"] = first_idx
    cols["last_name"] = last_idx
    cols["full_name"] = combined_idx

    if cols["nid"] < 0:
        raise AccountImportFormatError("ستون «کد ملی» یافت نشد؛ عنوان‌های دیده‌شده: " + "، ".join(h for h in norm if h))
    if cols["mobile"] < 0:
        raise AccountImportFormatError("ستون «شماره تماس/موبایل» یافت نشد؛ عنوان‌های دیده‌شده: " + "، ".join(h for h in norm if h))
    has_separate = first_idx >= 0 and last_idx >= 0
    if not has_separate and combined_idx < 0:
        raise AccountImportFormatError("ستون «نام و نام خانوادگی» یافت نشد؛ عنوان‌های دیده‌شده: " + "، ".join(h for h in norm if h))
    return cols


def _ensure_default_branch() -> Branch:
    """اولین شعبهٔ فعال؛ اگر سازمان خالی باشد منطقه و شعبهٔ پیش‌فرض می‌سازد."""
    branch = Branch.objects.filter(is_active=True).order_by("id").first()
    if branch is not None:
        return branch
    region = Region.objects.filter(is_active=True).order_by("id").first()
    if region is None:
        region = Region.objects.create(code="HQ", name="ستاد مرکزی")
    return Branch.objects.create(code="HQ", name="دفتر مرکزی", region=region)


def import_accounts(
    data: bytes,
    *,
    dry_run: bool = False,
    job_title: str = "مشاور",
) -> dict:
    """ورود گروهی پرسنل + حساب کاربری از فایل اکسل؛ گزارش ردیف‌به‌ردیف برمی‌گرداند."""
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # openpyxl انواع زیادی خطا می‌دهد
        raise AccountImportFormatError("فایل قابل خواندن نیست؛ قالب xlsx الزامی است.") from exc

    try:
        ws = wb.worksheets[0]
        rows = ws.iter_rows(values_only=True)
        try:
            header = list(next(rows))
        except StopIteration as exc:
            raise AccountImportFormatError("کاربرگ خالی است.") from exc
        cols = _pick_columns(header)

        def cell(row: tuple, key: str):
            idx = cols.get(key, -1)
            return row[idx] if idx >= 0 and idx < len(row) else None

        branch = _ensure_default_branch()
        existing_codes = set(Employee.objects.values_list("personnel_code", flat=True))
        existing_usernames = set(User.objects.values_list("username", flat=True))
        taken_usernames = set(existing_usernames)

        total = 0
        created = 0
        duplicates: list[dict] = []
        errors: list[dict] = []
        created_sample: list[dict] = []
        seen_nids: set[str] = set()
        seen_codes: set[str] = set()

        for n, raw_row in enumerate(rows, start=2):  # سطر ۱ = عنوان
            if all(v in (None, "") for v in raw_row):
                continue
            total += 1

            raw_name = _cell_text(cell(raw_row, "full_name"))
            first = _cell_text(cell(raw_row, "first_name"))
            last = _cell_text(cell(raw_row, "last_name"))
            if raw_name and (not first or not last):
                first, last = split_full_name(raw_name)
            first = (first or "").strip()
            last = (last or "").strip()
            display = f"{first} {last}".strip() or "—"
            if not first or not last:
                errors.append({"row": n, "name": display, "national_id": "", "message": "نام و نام خانوادگی کامل نیست."})
                continue

            nid, err = normalize_nid(cell(raw_row, "nid"))
            if err:
                errors.append({"row": n, "name": display, "national_id": "", "message": err})
                continue

            mobile, err = normalize_mobile(cell(raw_row, "mobile"))
            if err:
                errors.append({"row": n, "name": display, "national_id": nid, "message": err})
                continue

            raw_code = _cell_text(cell(raw_row, "personnel_code"))
            code = _only_digits(raw_code) if raw_code else ""
            if not code:
                code = nid
            if len(code) > 20:
                errors.append({"row": n, "name": display, "national_id": nid, "message": f"کد پرسنلی بیش از حد طولانی است: «{raw_code}»"})
                continue

            if nid in seen_nids or code in seen_codes:
                errors.append({"row": n, "name": display, "national_id": nid, "message": "این ردیف در خود فایل تکراری است."})
                continue
            seen_nids.add(nid)
            seen_codes.add(code)

            if code in existing_codes:
                duplicates.append({"row": n, "name": display, "national_id": nid, "message": "کد پرسنلی/تفضیلی قبلاً در سامانه ثبت شده است."})
                continue
            if nid in taken_usernames:
                duplicates.append({"row": n, "name": display, "national_id": nid, "message": "نام کاربری (کد ملی) قبلاً در سامانه ثبت شده است."})
                continue

            created += 1
            taken_usernames.add(nid)
            if len(created_sample) < MAX_REPORT_ROWS:
                created_sample.append({"row": n, "username": nid, "full_name": display, "mobile": mobile})
            if not dry_run:
                with transaction.atomic():
                    employee = Employee.objects.create(
                        personnel_code=code,
                        first_name=first,
                        last_name=last,
                        mobile=mobile,
                        national_id=nid,
                        job_title=job_title,
                        employment_status=EmploymentStatus.ACTIVE,
                        home_branch=branch,
                    )
                    User.objects.create_user(username=nid, password=mobile, employee=employee)
    finally:
        wb.close()

    return {
        "total": total,
        "created": created,
        "duplicates": len(duplicates),
        "errors": len(errors),
        "dry_run": dry_run,
        "branch": {"code": branch.code, "name": branch.name},
        "rule": {"username": "کد ملی", "password": "شماره موبایل"},
        "job_title": job_title,
        "errors_detail": errors[:MAX_REPORT_ROWS],
        "duplicates_detail": duplicates[:MAX_REPORT_ROWS],
        "created_sample": created_sample[:MAX_REPORT_ROWS],
    }
