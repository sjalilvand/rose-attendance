"""مدیریت پرسنل و کاربران خارج از پنل ادمین (صفحهٔ /management در PWA).

دسترسی: فقط superuser یا نقش HR / ADMIN — هم‌ارز گارد PersonnelImportView.
هیچ مدلی عوض نمی‌شود؛ فقط Employee و User موجود را مدیریت می‌کند.
"""
from __future__ import annotations

import datetime as dt

from django.db.models import Q
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.enums import EmploymentStatus
from apps.orgs.models import Branch, Region

from .models import Employee, User

DEMO_PASSWORD_DEFAULT = "Rose#1404"
PASSWORD_MIN_LEN = 8

# ۳۰ نام کامل واقعی برای دادهٔ نمونه (pair i → firsts[i] + lasts[i])
DEMO_FIRST_NAMES = (
    "رضا", "علی", "محمد", "حسین", "مهدی", "امیر", "سعید", "کاوه", "بابک", "فرهاد",
    "نادر", "سامان", "آرش", "بهنام", "پیمان", "زهرا", "فاطمه", "مریم", "سارا", "نگار",
    "الناز", "شیما", "پردیس", "هانیه", "لیلا", "مرضیه", "سمانه", "آیدا", "فرزانه", "مینا",
)
DEMO_LAST_NAMES = (
    "سعیدی", "محمدی", "حسینی", "رضایی", "کریمی", "موسوی", "نوری", "احمدی", "شریفی", "قاسمی",
    "صادقی", "جعفری", "عبدی", "رحیمی", "حسین‌زاده", "فرهادی", "امینی", "توکلی", "نیک‌پور", "سلطانی",
    "مرادی", "عباسی", "خسروی", "رستمی", "همتی", "اکبری", "عزیزی", "زارع", "بهرامی", "کاظمی",
)
DEMO_JOB_TITLES = (
    "کارمند اداری", "اپراتور", "حسابدار", "پشتیبانی", "انباردار",
    "کارشناس فروش", "تکنسین", "مسئول دفتر",
)


class IsPeopleManager(IsAuthenticated):
    """superuser یا نقش HR / ADMIN."""

    def has_permission(self, request, view) -> bool:
        if not super().has_permission(request, view):
            return False
        u = request.user
        return bool(u.is_superuser or u.has_role("HR") or u.has_role("ADMIN"))


def _bad(detail: str, code: str = "INVALID", http: int = 400) -> Response:
    return Response({"detail": detail, "code": code}, status=http)


def _ensure_default_branch() -> Branch:
    """اولین شعبهٔ فعال؛ اگر سازمان خالی باشد منطقه و شعبهٔ پیش‌فرض می‌سازد."""
    branch = Branch.objects.filter(is_active=True).order_by("id").first()
    if branch is not None:
        return branch
    region = Region.objects.filter(is_active=True).order_by("id").first()
    if region is None:
        region = Region.objects.create(code="HQ", name="ستاد مرکزی")
    return Branch.objects.create(code="HQ", name="دفتر مرکزی", region=region)


def _parse_date(value) -> dt.date | None:
    if value in (None, "", "null"):
        return None
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        raise ValueError("bad-date")


def _serialize_user_ref(u: User) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "is_active": u.is_active,
        "is_staff": u.is_staff,
        "last_login": u.last_login.isoformat() if u.last_login else None,
    }


def _serialize_employee(e: Employee) -> dict:
    u = getattr(e, "user_account", None)
    return {
        "id": e.id,
        "personnel_code": e.personnel_code,
        "first_name": e.first_name,
        "last_name": e.last_name,
        "full_name": e.full_name,
        "mobile": e.mobile,
        "national_id": e.national_id,
        "job_title": e.job_title,
        "employment_status": e.employment_status,
        "hired_on": e.hired_on.isoformat() if e.hired_on else None,
        "home_branch_id": e.home_branch_id,
        "home_branch_code": e.home_branch.code,
        "home_branch_name": e.home_branch.name,
        "user": _serialize_user_ref(u) if u is not None else None,
    }


def _serialize_user(u: User) -> dict:
    e = u.employee
    return {
        "id": u.id,
        "username": u.username,
        "is_active": u.is_active,
        "is_staff": u.is_staff,
        "is_superuser": u.is_superuser,
        "last_login": u.last_login.isoformat() if u.last_login else None,
        "failed_attempts": u.failed_attempts,
        "is_locked": u.is_locked(),
        "employee": (
            {"id": e.id, "personnel_code": e.personnel_code, "full_name": e.full_name}
            if e is not None
            else None
        ),
    }


def _check_password(password: str) -> Response | None:
    if not password or len(password) < PASSWORD_MIN_LEN:
        return _bad(f"گذرواژه باید حداقل {PASSWORD_MIN_LEN} نویسه باشد.", "WEAK_PASSWORD")
    return None


class ManagementPersonnelListCreate(APIView):
    """GET/POST /api/v1/management/personnel/ — فهرست و ایجاد پروندهٔ پرسنلی."""

    permission_classes = [IsAuthenticated, IsPeopleManager]

    def get(self, request):
        qs = (
            Employee.objects.select_related("home_branch", "user_account")
            .order_by("personnel_code")
        )
        q = (request.query_params.get("q") or "").strip()
        if q:
            qs = qs.filter(
                Q(personnel_code__icontains=q)
                | Q(first_name__icontains=q)
                | Q(last_name__icontains=q)
                | Q(mobile__icontains=q)
                | Q(user_account__username__icontains=q)
            )
        rows = [_serialize_employee(e) for e in qs[:500]]
        return Response({"count": len(rows), "results": rows})

    def post(self, request):
        d = request.data if isinstance(request.data, dict) else {}
        code = str(d.get("personnel_code") or "").strip()
        first = str(d.get("first_name") or "").strip()
        last = str(d.get("last_name") or "").strip()
        if not code or not first or not last:
            return _bad("کد پرسنلی، نام و نام خانوادگی الزامی است.", "REQUIRED")
        if Employee.objects.filter(personnel_code=code).exists():
            return _bad("این کد پرسنلی قبلاً ثبت شده است.", "DUPLICATE_CODE")
        username = str(d.get("username") or "").strip()
        password = str(d.get("password") or "")
        if username and User.objects.filter(username=username).exists():
            return _bad("این نام کاربری قبلاً گرفته شده است.", "DUPLICATE_USERNAME")
        if username:
            weak = _check_password(password)
            if weak is not None:
                return weak
        employment = str(d.get("employment_status") or EmploymentStatus.ACTIVE)
        if employment not in EmploymentStatus.values:
            return _bad("وضعیت اشتغال نامعتبر است.", "INVALID_STATUS")
        try:
            hired_on = _parse_date(d.get("hired_on"))
        except ValueError:
            return _bad("تاریخ استخدام نامعتبر است (فرمت YYYY-MM-DD).", "INVALID_DATE")

        branch_id = d.get("home_branch_id")
        if branch_id in (None, "", "null"):
            branch = _ensure_default_branch()
        else:
            try:
                branch = Branch.objects.get(pk=int(branch_id))
            except (Branch.DoesNotExist, TypeError, ValueError):
                return _bad("شعبهٔ انتخابی یافت نشد.", "NOT_FOUND", 404)

        try:
            with transaction.atomic():
                employee = Employee.objects.create(
                    personnel_code=code,
                    first_name=first,
                    last_name=last,
                    mobile=str(d.get("mobile") or "").strip()[:15],
                    national_id=str(d.get("national_id") or "").strip()[:10],
                    job_title=str(d.get("job_title") or "").strip()[:120],
                    employment_status=employment,
                    hired_on=hired_on,
                    home_branch=branch,
                )
                user = None
                if username:
                    user = User.objects.create_user(
                        username=username, password=password, employee=employee
                    )
                    if str(d.get("is_staff", "")).lower() in ("1", "true", "yes"):
                        user.is_staff = True
                        user.save(update_fields=["is_staff"])
        except Exception:
            return _bad("ایجاد پرونده ناموفق بود — ورودی‌ها را بررسی کنید.", "CREATE_FAILED")
        return Response(_serialize_employee(employee), status=status.HTTP_201_CREATED)


class ManagementPersonnelDetail(APIView):
    """PATCH /api/v1/management/personnel/{id}/ — ویرایش و اتصال/جداسازی کاربر."""

    permission_classes = [IsAuthenticated, IsPeopleManager]

    def patch(self, request, employee_id: int):
        try:
            employee = Employee.objects.select_related("home_branch").get(pk=employee_id)
        except Employee.DoesNotExist:
            return _bad("پروندهٔ پرسنلی یافت نشد.", "NOT_FOUND", 404)
        d = request.data if isinstance(request.data, dict) else {}

        if "first_name" in d:
            employee.first_name = str(d.get("first_name") or "").strip() or employee.first_name
        if "last_name" in d:
            employee.last_name = str(d.get("last_name") or "").strip() or employee.last_name
        for key in ("mobile", "national_id", "job_title"):
            if key in d:
                setattr(employee, key, str(d.get(key) or "").strip())
        if "employment_status" in d and str(d.get("employment_status") or ""):
            employment = str(d.get("employment_status"))
            if employment not in EmploymentStatus.values:
                return _bad("وضعیت اشتغال نامعتبر است.", "INVALID_STATUS")
            employee.employment_status = employment
        if "hired_on" in d:
            try:
                employee.hired_on = _parse_date(d.get("hired_on"))
            except ValueError:
                return _bad("تاریخ استخدام نامعتبر است.", "INVALID_DATE")
        if "home_branch_id" in d and d.get("home_branch_id") not in (None, "", "null"):
            try:
                employee.home_branch = Branch.objects.get(pk=int(d.get("home_branch_id")))
            except (Branch.DoesNotExist, TypeError, ValueError):
                return _bad("شعبهٔ انتخابی یافت نشد.", "NOT_FOUND", 404)

        if "user_id" in d:
            target = d.get("user_id")
            if target in (None, "", "null"):
                User.objects.filter(employee=employee).update(employee=None)
            else:
                try:
                    user = User.objects.get(pk=int(target))
                except (User.DoesNotExist, TypeError, ValueError):
                    return _bad("کاربر موردنظر یافت نشد.", "NOT_FOUND", 404)
                if user.employee_id not in (None, employee.id):
                    return _bad("این کاربر به پروندهٔ پرسنلی دیگری متصل است.", "USER_LINKED")
                user.employee = employee
                user.save(update_fields=["employee"])

        employee.save()
        return Response(_serialize_employee(employee))


class ManagementPersonnelCreateUserView(APIView):
    """POST /api/v1/management/personnel/{id}/create-user/ — ساخت حساب کاربری برای پرسنل."""

    permission_classes = [IsAuthenticated, IsPeopleManager]

    def post(self, request, employee_id: int):
        try:
            employee = Employee.objects.get(pk=employee_id)
        except Employee.DoesNotExist:
            return _bad("پروندهٔ پرسنلی یافت نشد.", "NOT_FOUND", 404)
        if User.objects.filter(employee=employee).exists():
            return _bad("این پرسنل قبلاً حساب کاربری دارد.", "USER_EXISTS")
        d = request.data if isinstance(request.data, dict) else {}
        username = str(d.get("username") or "").strip()
        password = str(d.get("password") or "")
        if not username:
            return _bad("نام کاربری الزامی است.", "REQUIRED")
        if User.objects.filter(username=username).exists():
            return _bad("این نام کاربری قبلاً گرفته شده است.", "DUPLICATE_USERNAME")
        weak = _check_password(password)
        if weak is not None:
            return weak
        with transaction.atomic():
            user = User.objects.create_user(username=username, password=password, employee=employee)
            if str(d.get("is_staff", "")).lower() in ("1", "true", "yes"):
                user.is_staff = True
                user.save(update_fields=["is_staff"])
        return Response(_serialize_user_ref(user), status=status.HTTP_201_CREATED)


class ManagementUsersList(APIView):
    """GET /api/v1/management/users/ — فهرست همهٔ حساب‌های کاربری."""

    permission_classes = [IsAuthenticated, IsPeopleManager]

    def get(self, request):
        qs = User.objects.select_related("employee").order_by("username")
        q = (request.query_params.get("q") or "").strip()
        if q:
            qs = qs.filter(
                Q(username__icontains=q)
                | Q(employee__first_name__icontains=q)
                | Q(employee__last_name__icontains=q)
                | Q(employee__personnel_code__icontains=q)
            )
        rows = [_serialize_user(u) for u in qs[:500]]
        return Response({"count": len(rows), "results": rows})


class ManagementUserDetail(APIView):
    """PATCH /api/v1/management/users/{id}/ — فعال/غیرفعال، دسترسی ادمین، تغییر نام کاربری."""

    permission_classes = [IsAuthenticated, IsPeopleManager]

    def patch(self, request, user_id: int):
        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return _bad("کاربر یافت نشد.", "NOT_FOUND", 404)
        d = request.data if isinstance(request.data, dict) else {}
        if user.id == request.user.id and ("is_active" in d or "is_staff" in d):
            return _bad("نمی‌توانید حساب خودتان را فعال/غیرفعال کنید.", "SELF_LOCKOUT")
        if "username" in d:
            username = str(d.get("username") or "").strip()
            if not username:
                return _bad("نام کاربری خالی است.", "REQUIRED")
            if User.objects.filter(username=username).exclude(pk=user.id).exists():
                return _bad("این نام کاربری قبلاً گرفته شده است.", "DUPLICATE_USERNAME")
            user.username = username
        if "is_active" in d:
            user.is_active = bool(d.get("is_active"))
        if "is_staff" in d:
            user.is_staff = bool(d.get("is_staff"))
        user.save()
        return Response(_serialize_user(user))


class ManagementUserSetPassword(APIView):
    """POST /api/v1/management/users/{id}/set-password/ — ریست گذرواژه + رفع قفل."""

    permission_classes = [IsAuthenticated, IsPeopleManager]

    def post(self, request, user_id: int):
        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return _bad("کاربر یافت نشد.", "NOT_FOUND", 404)
        d = request.data if isinstance(request.data, dict) else {}
        password = str(d.get("password") or "")
        weak = _check_password(password)
        if weak is not None:
            return weak
        user.set_password(password)
        user.failed_attempts = 0
        user.locked_until = None
        user.is_active = True
        user.save()
        return Response({"detail": f"گذرواژهٔ «{user.username}» عوض شد.", "username": user.username})


class ManagementSeedDemoView(APIView):
    """POST /api/v1/management/seed-demo/ — ساخت دادهٔ نمونه برای تست ورود پرسنل.

    پارامترها: count (پیش‌فرض ۳۰) و password (پیش‌فرض Rose#1404).
    Idempotent: کد/نام‌کاربری تکراری را رد می‌کند و ادامه می‌دهد.
    """

    permission_classes = [IsAuthenticated, IsPeopleManager]

    def post(self, request):
        d = request.data if isinstance(request.data, dict) else {}
        try:
            count = max(1, min(int(d.get("count") or 30), 200))
        except (TypeError, ValueError):
            return _bad("count باید عدد باشد.", "INVALID")
        password = str(d.get("password") or DEMO_PASSWORD_DEFAULT)
        weak = _check_password(password)
        if weak is not None:
            return weak

        branch = _ensure_default_branch()
        today = timezone.localdate()

        taken_codes = set(
            Employee.objects.filter(personnel_code__regex=r"^\d+$").values_list("personnel_code", flat=True)
        )
        taken_usernames = set(User.objects.values_list("username", flat=True))
        try:
            start = max(int(c) for c in taken_codes) + 1 if taken_codes else 1001
        except ValueError:
            start = 1001

        created_rows = []
        skipped = 0
        code = start
        index = 0
        while len(created_rows) < count and index < count * 4:
            index += 1
            person_code = str(code)
            username = f"user{person_code}"
            code += 1
            if person_code in taken_codes or username in taken_usernames:
                skipped += 1
                continue
            i = len(created_rows)
            first = DEMO_FIRST_NAMES[i % len(DEMO_FIRST_NAMES)]
            last = DEMO_LAST_NAMES[(i * 7 + i // len(DEMO_FIRST_NAMES)) % len(DEMO_LAST_NAMES)]
            hired = today - dt.timedelta(days=(i * 13) % 180)
            with transaction.atomic():
                employee = Employee.objects.create(
                    personnel_code=person_code,
                    first_name=first,
                    last_name=last,
                    job_title=DEMO_JOB_TITLES[i % len(DEMO_JOB_TITLES)],
                    employment_status=EmploymentStatus.ACTIVE,
                    hired_on=hired,
                    home_branch=branch,
                )
                User.objects.create_user(username=username, password=password, employee=employee)
            taken_codes.add(person_code)
            taken_usernames.add(username)
            created_rows.append({"personnel_code": person_code, "username": username, "full_name": f"{first} {last}"})

        if created_rows:
            User.objects.filter(username__in=[r["username"] for r in created_rows]).update(is_active=True)

        return Response(
            {
                "created": len(created_rows),
                "skipped": skipped,
                "password": password,
                "branch": {"code": branch.code, "name": branch.name},
                "first_username": created_rows[0]["username"] if created_rows else None,
                "last_username": created_rows[-1]["username"] if created_rows else None,
                "sample": created_rows[:5],
                "note": "برای تست، با هر نام کاربری و گذرواژهٔ بالا در صفحهٔ ورود وارد شوید.",
            }
        )
