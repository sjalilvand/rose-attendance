"""Bulk personnel import tests — parsing, upsert semantics, dry run, access."""
from __future__ import annotations

import io

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from openpyxl import Workbook
from rest_framework.test import APIClient

from apps.orgs.models import Branch, Region
from apps.people.models import Employee, User
from apps.scheduling.models import Shift, ShiftPattern, ShiftPatternItem

XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
HEADER = ["personnel_code", "first_name", "last_name", "branch_code",
          "shift_code", "hired_on", "employment_status"]


def make_branch(code="B100"):
    region, _ = Region.objects.get_or_create(code="R1", defaults={"name": "منطقه یک"})
    return Branch.objects.create(code=code, name=f"شعبه {code}", region=region)


def make_hr_client() -> tuple[APIClient, User]:
    region, _ = Region.objects.get_or_create(code="RH", defaults={"name": "ه"})
    branch = Branch.objects.create(code="BH", name="ه", region=region)
    emp = Employee.objects.create(
        personnel_code="HR-1", first_name="منشی", last_name="منابع", home_branch=branch,
    )
    user = User.objects.create_user(username="hr1", password="Hr!Pass123", employee=emp)
    from apps.people.models import Role, RoleAssignment

    RoleAssignment.objects.create(
        user=user, role=Role.objects.get(code="HR"), valid_from="2020-01-01",
    )
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


def workbook_bytes(rows: list[list], header: list[str] | None = None) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(header or HEADER)
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def upload_file(content: bytes, name="people.xlsx") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, content, content_type=XLSX_TYPE)


class ImportPermissionTests(TestCase):
    def setUp(self):
        make_branch()

    def test_anonymous_gets_401(self):
        res = APIClient().post(reverse("people-import"))
        self.assertEqual(res.status_code, 401)

    def test_plain_employee_gets_403(self):
        branch = Branch.objects.first()
        emp = Employee.objects.create(
            personnel_code="P1", first_name="a", last_name="b", home_branch=branch,
        )
        user = User.objects.create_user(username="plain", password="Xy!Pass123", employee=emp)
        client = APIClient()
        client.force_authenticate(user=user)
        res = client.post(reverse("people-import"))
        self.assertEqual(res.status_code, 403)

    def test_hr_role_allowed(self):
        client, _user = make_hr_client()
        content = workbook_bytes([["1001", "علی", "رضایی", "B100", "", "", ""]])
        res = client.post(
            reverse("people-import"),
            {"file": upload_file(content), "dry_run": "true"},
            format="multipart",
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["created"], 1)  # dry run reports would-be creates
        self.assertEqual(res.data["dry_run"], True)

    def test_superuser_allowed(self):
        from django.core.management import call_command

        call_command("createsuperuser", "--noinput", "--username", "root")
        user = User.objects.get(username="root")
        client = APIClient()
        client.force_authenticate(user=user)
        res = client.get(reverse("people-import-template"))
        self.assertEqual(res.status_code, 200)


class ImportFlowTests(TestCase):
    def setUp(self):
        self.branch = make_branch()
        self.shift = Shift.objects.create(
            code="SHIFT-M", name="صبح", starts_at="08:00", ends_at="14:00",
        )
        self.client_hr, _user = make_hr_client()

    def _post(self, rows: list[list], dry_run: bool = False, header=None):
        content = workbook_bytes(rows, header)
        return self.client_hr.post(
            reverse("people-import"),
            {"file": upload_file(content), "dry_run": "true" if dry_run else "false"},
            format="multipart",
        )

    def test_create_then_update_upsert(self):
        rows = [["1001", "علی", "رضایی", "B100", "", "", ""],
                ["1002", "مریم", "کریمی", "B100", "", "", ""]]
        res = self._post(rows)
        self.assertEqual(res.status_code, 200)
        self.assertEqual((res.data["created"], res.data["updated"]), (2, 0))
        self.assertEqual(Employee.objects.count(), 3)  # + HR fixture employee

        rows[0][1] = "علیرضا"
        res2 = self._post(rows)
        self.assertEqual((res2.data["created"], res2.data["updated"]), (0, 2))
        self.assertEqual(Employee.objects.get(personnel_code="1001").first_name, "علیرضا")

    def test_bad_branch_is_skipped_good_rows_land(self):
        res = self._post([["2001", "a", "b", "NOPE", "", "", ""],
                          ["2002", "c", "d", "B100", "", "", ""]])
        self.assertEqual(res.data["created"], 1)
        self.assertEqual(res.data["skipped"], 1)
        self.assertIn("شعبه", res.data["errors"][0]["message"])
        self.assertFalse(Employee.objects.filter(personnel_code="2001").exists())

    def test_missing_required_headers_rejected(self):
        res = self._post([["3001", "a", "b"]], header=["personnel_code", "first_name", "last_name"])
        self.assertEqual(res.status_code, 400)
        self.assertIn("branch_code", res.data["detail"])

    def test_jalali_date_parsed(self):
        res = self._post([["4001", "a", "b", "B100", "", "1403-05-02", ""]])
        self.assertEqual(res.status_code, 200)
        emp = Employee.objects.get(personnel_code="4001")
        self.assertEqual((emp.hired_on.year, emp.hired_on.month, emp.hired_on.day), (2024, 7, 23))

    def test_shift_creates_branch_pattern(self):
        res = self._post([["5001", "a", "b", "B100", "SHIFT-M", "", ""]])
        self.assertEqual(res.status_code, 200)
        pattern = ShiftPattern.objects.get(code="IMP-B100-SHIFT-M")
        item = ShiftPatternItem.objects.get(pattern=pattern, day_index=1)
        self.assertEqual(item.shift_id, self.shift.id)

    def test_dry_run_writes_nothing(self):
        res = self._post([["6001", "a", "b", "B100", "SHIFT-M", "", ""]], dry_run=True)
        self.assertEqual(res.data["created"], 1)
        self.assertEqual(res.data["dry_run"], True)
        self.assertFalse(Employee.objects.filter(personnel_code="6001").exists())
        self.assertEqual(ShiftPattern.objects.count(), 0)

    def test_template_download(self):
        res = self.client_hr.get(reverse("people-import-template"))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res["Content-Type"], XLSX_TYPE)
        self.assertGreater(len(res.content), 1000)
