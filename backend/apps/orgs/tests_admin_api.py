"""Org management API tests — regions/branches/shifts CRUD + bulk upsert.

The bulk-import cycle requires HR to create branch/shift codes *before* the
personnel workbook lands; these tests pin the permission split (read open to
authenticated users, writes HR/ADMIN only) and the upsert semantics.
"""
from __future__ import annotations

import datetime as dt

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.enums import RestMode
from apps.orgs.models import Branch, Region
from apps.people.models import Employee, Role, RoleAssignment, User
from apps.scheduling.models import Shift


def make_branch(code="B100", region=None, **over):
    if region is None:
        region, _ = Region.objects.get_or_create(code="R1", defaults={"name": "منطقه یک"})
    fields = dict(
        code=code, name=f"شعبه {code}", region=region,
        geo_latitude=35.7997, geo_longitude=51.4344,
        geo_radius_m=150, city="تهران",
    )
    fields.update(over)
    return Branch.objects.create(**fields)


def make_employee(branch, code="12345"):
    emp = Employee.objects.create(
        personnel_code=code, first_name="علی", last_name="رضایی",
        home_branch=branch,
    )
    user = User.objects.create_user(
        username=f"u{code}", password="S3cret!Pass", employee=emp
    )
    return emp, user


def grant(user, code, branch=None):
    RoleAssignment.objects.create(
        user=user, role=Role.objects.get(code=code), branch=branch,
        valid_from=timezone.localdate() - dt.timedelta(days=1),
    )


class BranchPermissionTests(TestCase):
    def setUp(self):
        self.branch = make_branch()
        self.emp, self.user = make_employee(self.branch)
        self.hr, _hr_user = None, None
        self.hr_emp, self.hr_user = make_employee(self.branch, code="HR-1")
        grant(self.hr_user, "HR")
        self.client = APIClient()

    def test_read_open_to_any_authenticated_user(self):
        self.client.force_authenticate(self.user)
        res = self.client.get("/api/v1/org/branches/")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.data["count"], 1)
        row = res.data["results"][0]
        self.assertEqual(row["code"], "B100")
        self.assertEqual(row["region_code"], "R1")
        self.assertEqual(row["employee_count"], 2)

    def test_employee_cannot_create_branch(self):
        self.client.force_authenticate(self.user)
        res = self.client.post(
            "/api/v1/org/branches/",
            {"code": "B999", "name": "شعبه نو", "region_code": "R1"},
        )
        self.assertEqual(res.status_code, 403, res.content)
        self.assertFalse(Branch.objects.filter(code="B999").exists())

    def test_hr_creates_branch_with_geo_pair_validation(self):
        self.client.force_authenticate(self.hr_user)
        res = self.client.post(
            "/api/v1/org/branches/",
            {"code": "B200", "name": "شعبه دو", "region_code": "R1", "city": "کرج"},
        )
        self.assertEqual(res.status_code, 201, res.content)
        self.assertTrue(Branch.objects.filter(code="B200", city="کرج").exists())
        # lat without lon → rejected
        res = self.client.post(
            "/api/v1/org/branches/",
            {"code": "B300", "name": "ناقص", "region_code": "R1", "geo_latitude": 35.1},
        )
        self.assertEqual(res.status_code, 400)
        # unknown region → rejected
        res = self.client.post(
            "/api/v1/org/branches/",
            {"code": "B300", "name": "بی‌منطقه", "region_code": "NOPE"},
        )
        self.assertEqual(res.status_code, 400, res.content)

    def test_branch_patch_updates_fields(self):
        self.client.force_authenticate(self.hr_user)
        res = self.client.patch(
            f"/api/v1/org/branches/{self.branch.id}/",
            {"city": "ری", "is_active": False},
            format="json",
        )
        self.assertEqual(res.status_code, 200, res.content)
        self.branch.refresh_from_db()
        self.assertEqual(self.branch.city, "ری")
        self.assertFalse(self.branch.is_active)

    def test_region_create_and_duplicate(self):
        self.client.force_authenticate(self.hr_user)
        res = self.client.post("/api/v1/org/regions/", {"code": "R2", "name": "منطقه دو"})
        self.assertEqual(res.status_code, 201, res.content)
        res = self.client.post("/api/v1/org/regions/", {"code": "R2", "name": "تکراری"})
        self.assertEqual(res.status_code, 400, res.content)
        self.assertEqual(res.data["code"], "DUPLICATE")


class BranchBulkTests(TestCase):
    def setUp(self):
        region, _ = Region.objects.get_or_create(code="R1", defaults={"name": "منطقه یک"})
        self.region = region
        make_branch(code="B100", region=region)
        self.emp, self.user = make_employee(make_branch(code="B000", region=region), code="99999")
        self.hr_emp, self.hr_user = make_employee(
            make_branch(code="BHR", region=region), code="HR-9"
        )
        grant(self.hr_user, "HR")
        self.client = APIClient()

    def _bulk(self, items, dry=False):
        self.client.force_authenticate(self.hr_user)
        return self.client.post(
            "/api/v1/org/branches/bulk/",
            {"items": items, "dry_run": dry},
            format="json",
        )

    def test_bulk_creates_updates_and_reports_errors(self):
        res = self._bulk([
            {"code": "B200", "name": "جدید یک", "region_code": "R1"},
            {"code": "B300", "name": "جدید دو", "region_code": "R1"},
            {"code": "B100", "name": "شعبه یک — به‌روزشده", "region_code": "R1", "city": "تهران"},
            {"code": "B400", "name": "بی‌منطقه", "region_code": "XX"},
            {"code": "B100", "name": "تکراری در فایل", "region_code": "R1"},
            {"name": "بی‌کد", "region_code": "R1"},
        ])
        self.assertEqual(res.status_code, 200, res.content)
        report = res.data
        self.assertEqual(report["total"], 6)
        self.assertEqual(report["created"], 2)
        self.assertEqual(report["updated"], 1)
        self.assertEqual(report["skipped"], 3)
        self.assertFalse(report["dry_run"])
        self.assertTrue(Branch.objects.filter(code="B200").exists())
        self.assertEqual(
            Branch.objects.get(code="B100").name, "شعبه یک — به‌روزشده"
        )
        # first error is the unknown region row (B400)
        self.assertIn("منطقه", report["errors"][0]["message"])

    def test_bulk_dry_run_touches_nothing(self):
        res = self._bulk(
            [{"code": "B900", "name": "نوشته‌نشدنی", "region_code": "R1"}], dry=True
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["created"], 1)
        self.assertTrue(res.data["dry_run"])
        self.assertFalse(Branch.objects.filter(code="B900").exists())

    def test_bulk_requires_hr(self):
        self.client.force_authenticate(self.user)
        res = self.client.post(
            "/api/v1/org/branches/bulk/",
            {"items": [{"code": "B700", "name": "x", "region_code": "R1"}]},
            format="json",
        )
        self.assertEqual(res.status_code, 403, res.content)
        self.assertFalse(Branch.objects.filter(code="B700").exists())

    def test_bulk_rejects_oversized_payload(self):
        res = self._bulk([
            {"code": f"BX{i}", "name": "x", "region_code": "R1"} for i in range(5001)
        ])
        self.assertEqual(res.status_code, 400, res.content)


class ShiftApiTests(TestCase):
    def setUp(self):
        region, _ = Region.objects.get_or_create(code="R1", defaults={"name": "منطقه یک"})
        self.branch = make_branch(code="B100", region=region)
        self.emp, self.user = make_employee(self.branch, code="12345")
        self.hr_emp, self.hr_user = make_employee(self.branch, code="HR-9")
        grant(self.hr_user, "HR")
        self.client = APIClient()

    def test_hr_creates_shift_and_night_shift_auto_crosses_midnight(self):
        self.client.force_authenticate(self.hr_user)
        res = self.client.post(
            "/api/v1/scheduling/shifts/",
            {"code": "SHIFT-M", "name": "صبح", "starts_at": "08:00", "ends_at": "14:00"},
        )
        self.assertEqual(res.status_code, 201, res.content)
        self.assertFalse(res.data["crosses_midnight"])
        res = self.client.post(
            "/api/v1/scheduling/shifts/",
            {"code": "SHIFT-N", "name": "شب", "starts_at": "22:00", "ends_at": "06:00"},
        )
        self.assertEqual(res.status_code, 201, res.content)
        self.assertTrue(res.data["crosses_midnight"])
        self.assertFalse(res.data["scope_branch"])  # global scope

    def test_shift_scoped_to_branch_and_filters(self):
        self.client.force_authenticate(self.hr_user)
        self.client.post(
            "/api/v1/scheduling/shifts/",
            {"code": "SHIFT-B", "name": "شعبه‌ای", "starts_at": "09:00",
             "ends_at": "17:00", "scope_branch_code": "B100"},
        )
        res = self.client.get("/api/v1/scheduling/shifts/?branch=B100")
        self.assertEqual(res.data["count"], 1)
        res = self.client.get("/api/v1/scheduling/shifts/?scope=GLOBAL")
        self.assertEqual(res.data["count"], 0)

    def test_shift_bulk_upsert(self):
        Shift.objects.create(
            code="SHIFT-M", name="صبح قدیم", starts_at="08:00", ends_at="14:00",
            rest_mode=RestMode.FIXED,
        )
        self.client.force_authenticate(self.hr_user)
        res = self.client.post(
            "/api/v1/scheduling/shifts/bulk/",
            {"items": [
                {"code": "SHIFT-M", "name": "صبح", "starts_at": "07:30", "ends_at": "13:30"},
                {"code": "SHIFT-E", "name": "عصر", "starts_at": "15:00", "ends_at": "21:00",
                 "rest_minutes": 30, "grace_minutes": 5},
                {"code": "SHIFT-X", "name": "بدون پایان", "starts_at": "09:00"},
            ]},
            format="json",
        )
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.data["created"], 1)
        self.assertEqual(res.data["updated"], 1)
        self.assertEqual(res.data["skipped"], 1)
        self.assertEqual(Shift.objects.get(code="SHIFT-M").starts_at.strftime("%H:%M"), "07:30")
        self.assertEqual(Shift.objects.get(code="SHIFT-E").rest_minutes, 30)

    def test_employee_cannot_create_shift(self):
        self.client.force_authenticate(self.user)
        res = self.client.post(
            "/api/v1/scheduling/shifts/",
            {"code": "SHIFT-Z", "name": "ممنوع", "starts_at": "08:00", "ends_at": "14:00"},
        )
        self.assertEqual(res.status_code, 403, res.content)
