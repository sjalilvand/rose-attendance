"""ورود گروهی حساب‌ها از اکسل — پارس، ساخت کاربر، idempotency، دسترسی و دستور مدیریتی."""
from __future__ import annotations

import io

from django.contrib.auth import authenticate
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from openpyxl import Workbook
from rest_framework.test import APIClient

from apps.orgs.models import Branch, Region
from apps.people.models import Employee, User

XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
HEADER = ["استان", "نام و نام خانوادگی", "کد تفضیلی شخص", "کد ملی", "شماره تماس"]


def make_branch(code="B100"):
    region, _ = Region.objects.get_or_create(code="R1", defaults={"name": "منطقه یک"})
    return Branch.objects.create(code=code, name=f"شعبه {code}", region=region)


def make_admin_client() -> tuple[APIClient, User]:
    branch = make_branch("BH")
    emp = Employee.objects.create(
        personnel_code="ADM-1", first_name="مدیر", last_name="سامانه", home_branch=branch,
    )
    user = User.objects.create_user(
        username="admin1", password="Admin!Pass1", employee=emp,
        is_staff=True, is_superuser=True,
    )
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


def consultant_workbook(rows: list[list]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(HEADER)
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def upload(content: bytes, name="asami.xlsx") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, content, content_type=XLSX_TYPE)


GOOD_ROWS = [
    ["اردبیل", "پری ملکی گلندوز", "101135", "1639818146", "09147446047"],
    ["البرز", "الهام حاجی نصیری", "101136", "۰۰۷۷۵۴۵۴۲۷", "۰۹۱۲۰۵۹۲۹۰۶"],  # ارقام فارسی
    ["البرز", "فاطمه حاجی محمدی", "101137", "0311476031", None],  # بدون موبایل
]


class ImportAccountsApiTests(TestCase):
    def setUp(self):
        cache.clear()  # bucket «import» بین تست‌ها می‌ماند
        make_branch()

    def post_file(self, content: bytes, dry_run=False, client=None):
        c = client or make_admin_client()[0]
        data = {"file": upload(content)}
        if dry_run:
            data["dry_run"] = "true"
        return c.post(reverse("mgmt-personnel-import-accounts"), data, format="multipart")

    def test_anonymous_gets_401(self):
        res = APIClient().post(reverse("mgmt-personnel-import-accounts"))
        self.assertEqual(res.status_code, 401)

    def test_plain_employee_gets_403(self):
        branch = Branch.objects.first()
        emp = Employee.objects.create(
            personnel_code="EMP-9", first_name="ساده", last_name="ساده", home_branch=branch,
        )
        user = User.objects.create_user(username="plain", password="Plain!Pass1", employee=emp)
        client = APIClient()
        client.force_authenticate(user=user)
        res = client.post(reverse("mgmt-personnel-import-accounts"))
        self.assertEqual(res.status_code, 403)

    def test_file_required(self):
        client, _ = make_admin_client()
        res = client.post(reverse("mgmt-personnel-import-accounts"), {}, format="multipart")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data["code"], "INVALID")

    def test_missing_required_columns_rejected(self):
        client, _ = make_admin_client()
        wb = Workbook()
        ws = wb.active
        ws.append(["استان", "نام", "کد ملی"])
        ws.append(["تهران", "علی رضایی", "1234567890"])
        buf = io.BytesIO()
        wb.save(buf)
        res = self.post_file(buf.getvalue(), client=client)
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data["code"], "INVALID_FORMAT")
        self.assertIn("شماره تماس", res.data["detail"])

    def test_dry_run_reports_without_creating(self):
        client, _ = make_admin_client()
        res = self.post_file(consultant_workbook(GOOD_ROWS), dry_run=True, client=client)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data["dry_run"])
        self.assertEqual(res.data["total"], 3)
        self.assertEqual(res.data["created"], 2)
        self.assertEqual(res.data["errors"], 1)
        self.assertEqual(res.data["errors_detail"][0]["message"], "شماره موبایل در فایل خالی است.")
        self.assertEqual(User.objects.count(), 1)  # فقط admin1
        self.assertEqual(Employee.objects.count(), 1)  # فقط پروندهٔ admin1

    def test_import_creates_employee_user_and_login_works(self):
        client, _ = make_admin_client()
        res = self.post_file(consultant_workbook(GOOD_ROWS), client=client)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["created"], 2)
        self.assertEqual(res.data["errors"], 1)

        user = User.objects.get(username="1639818146")
        employee = user.employee
        self.assertIsNotNone(employee)
        self.assertEqual(employee.personnel_code, "101135")
        self.assertEqual(employee.first_name, "پری")
        self.assertEqual(employee.last_name, "ملکی گلندوز")
        self.assertEqual(employee.national_id, "1639818146")
        self.assertEqual(employee.mobile, "09147446047")
        self.assertEqual(employee.job_title, "مشاور")
        self.assertTrue(user.check_password("09147446047"))
        self.assertTrue(user.is_active)

        # ارقام فارسی نرمال شده‌اند
        user2 = User.objects.get(username="0077545427")
        self.assertEqual(user2.employee.national_id, "0077545427")
        self.assertTrue(user2.check_password("09120592906"))

        # همان مسیر احرازهویتِ JWT (ورود از اپ موبایل)
        self.assertIsNotNone(authenticate(username="1639818146", password="09147446047"))
        self.assertIsNone(authenticate(username="1639818146", password="wrong-pass"))

    def test_reimport_is_idempotent(self):
        client, _ = make_admin_client()
        first = self.post_file(consultant_workbook(GOOD_ROWS), client=client)
        self.assertEqual(first.data["created"], 2)
        users_before = User.objects.count()

        second = self.post_file(consultant_workbook(GOOD_ROWS), client=client)
        self.assertEqual(second.data["created"], 0)
        self.assertEqual(second.data["duplicates"], 2)
        self.assertEqual(User.objects.count(), users_before)

    def test_duplicate_username_vs_other_employee_skipped(self):
        client, _ = make_admin_client()
        branch = Branch.objects.first()
        Employee.objects.create(
            personnel_code="999", first_name="قبلی", last_name="قبلی", national_id="1639818146",
            home_branch=branch,
        )
        User.objects.create_user(username="1639818146", password="Xy12345678")
        res = self.post_file(consultant_workbook([GOOD_ROWS[0]]), client=client)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["created"], 0)
        self.assertEqual(res.data["duplicates"], 1)


class ImportAccountsCommandTests(TestCase):
    def setUp(self):
        cache.clear()
        make_branch()

    def test_command_dry_run_then_import(self):
        content = consultant_workbook(GOOD_ROWS)
        path = "/tmp/test-asami.xlsx"
        with open(path, "wb") as fh:
            fh.write(content)

        out = io.StringIO()
        call_command("import_accounts_excel", path, "--dry-run", stdout=out)
        self.assertIn("ساخته‌شده: 2", out.getvalue())
        self.assertEqual(User.objects.count(), 0)

        out = io.StringIO()
        call_command("import_accounts_excel", path, stdout=out)
        self.assertIn("ساخته‌شده: 2", out.getvalue())
        self.assertTrue(User.objects.filter(username="1639818146").exists())

        out = io.StringIO()
        call_command("import_accounts_excel", path, stdout=out)
        self.assertIn("تکراری (دست نخورده): 2", out.getvalue())
        self.assertEqual(User.objects.count(), 2)  # کاربر جدیدی ساخته نشد

    def test_command_missing_file(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            call_command("import_accounts_excel", "/tmp/no-such-file.xlsx")
