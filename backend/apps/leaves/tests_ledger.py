"""LeaveLedger activation tests — seeding, guard, decision deduction, API.

Pins the new §11 behaviour: HR seeds balances, tracked types block
insufficient submissions, APPROVE appends DEDUCTION atomically, and the
decision queue carries each employee's remaining balance.
"""
from __future__ import annotations

import datetime as dt

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.enums import ApprovalAction, LeaveEntryKind, RequestStatus
from apps.leaves.models import LeaveLedger, LeaveType
from apps.orgs.models import Branch, Region
from apps.people.models import Employee, Role, RoleAssignment, User


def make_branch(code="B100"):
    region, _ = Region.objects.get_or_create(code="R1", defaults={"name": "منطقه یک"})
    return Branch.objects.create(
        code=code, name=f"شعبه {code}", region=region,
        geo_latitude=35.7997, geo_longitude=51.4344,
        geo_radius_m=150, city="تهران",
    )


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


def leave_type(code="ANNUAL", **over):
    fields = dict(name="استحقاقی", is_hourly=True)
    fields.update(over)
    lt, _ = LeaveType.objects.get_or_create(code=code, defaults=fields)
    return lt


def window(days_ahead=1, hours=4):
    start = timezone.make_aware(
        dt.datetime.combine(timezone.localdate() + dt.timedelta(days=days_ahead), dt.time(9, 0))
    )
    return start, start + dt.timedelta(hours=hours)


class SeedAndBalanceTests(TestCase):
    def setUp(self):
        cache.clear()  # bucket throttle «seed» per-IP است و بین تست‌ها می‌ماند
        self.branch = make_branch()
        self.emp, self.user = make_employee(self.branch)
        self.hr_emp, self.hr_user = make_employee(self.branch, code="HR-9")
        grant(self.hr_user, "HR")
        leave_type("ANNUAL")
        leave_type("SICK", name="استعلاجی")
        self.client = APIClient()

    def test_seed_creates_opening_entries_with_running_balance(self):
        self.client.force_authenticate(self.hr_user)
        res = self.client.post(
            "/api/v1/leaves/ledger/seed/",
            {"items": [
                {"personnel_code": "12345", "leave_type": "ANNUAL", "minutes": 12480,
                 "basis_date": "1404/01/01"},
                {"personnel_code": "12345", "leave_type": "ANNUAL", "minutes": 480,
                 "basis_date": "1404/02/01"},
            ]},
            format="json",
        )
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.data["created"], 2)
        self.assertEqual(res.data["skipped"], 0)
        rows = LeaveLedger.objects.filter(employee=self.emp).order_by("id")
        self.assertEqual(rows.count(), 2)
        self.assertEqual(rows.last().balance_after_minutes, 12960)
        self.assertEqual(rows.last().source_type, "HR_SEED")
        # Jalali basis date 1404/02/01 → 2025-04-21
        self.assertEqual(rows.last().basis_date.isoformat(), "2025-04-21")

    def test_seed_dry_run_writes_nothing_and_reports_bad_rows(self):
        self.client.force_authenticate(self.hr_user)
        res = self.client.post(
            "/api/v1/leaves/ledger/seed/",
            {"dry_run": True, "items": [
                {"personnel_code": "12345", "leave_type": "ANNUAL", "minutes": 12480},
                {"personnel_code": "NOPE", "leave_type": "ANNUAL", "minutes": 100},
                {"personnel_code": "12345", "leave_type": "GHOST", "minutes": 100},
                {"personnel_code": "12345", "leave_type": "ANNUAL", "minutes": 0},
                {"personnel_code": "12345", "leave_type": "ANNUAL", "minutes": -50,
                 "entry_kind": "OPENING"},
            ]},
            format="json",
        )
        self.assertEqual(res.status_code, 200, res.content)
        # dry run reports *would-create* rows, same as the personnel importer
        self.assertEqual(res.data["created"], 1)
        self.assertEqual(res.data["skipped"], 4)
        self.assertTrue(res.data["dry_run"])
        self.assertEqual(LeaveLedger.objects.count(), 0)

    def test_seed_forbidden_for_plain_employee(self):
        self.client.force_authenticate(self.user)
        res = self.client.post(
            "/api/v1/leaves/ledger/seed/",
            {"items": [{"personnel_code": "12345", "leave_type": "ANNUAL", "minutes": 100}]},
            format="json",
        )
        self.assertEqual(res.status_code, 403, res.content)

    def test_balances_self_and_by_hr(self):
        LeaveLedger.objects.create(
            employee=self.emp, leave_type=leave_type("ANNUAL"),
            entry_kind=LeaveEntryKind.OPENING, minutes=12480,
            balance_after_minutes=12480, basis_date=timezone.localdate(),
        )
        self.client.force_authenticate(self.user)
        res = self.client.get("/api/v1/leaves/ledger/balances/")
        self.assertEqual(res.status_code, 200, res.content)
        by_code = {b["leave_type"]: b for b in res.data["balances"]}
        self.assertTrue(by_code["ANNUAL"]["tracked"])
        self.assertEqual(by_code["ANNUAL"]["balance_minutes"], 12480)
        self.assertFalse(by_code["SICK"]["tracked"])
        self.assertIsNone(by_code["SICK"]["balance_minutes"])

        # employee cannot look others up; region manager and HR can
        res = self.client.get("/api/v1/leaves/ledger/balances/?employee=HR-9")
        self.assertEqual(res.status_code, 403)
        self.client.force_authenticate(self.hr_user)
        res = self.client.get("/api/v1/leaves/ledger/balances/?employee=12345")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["employee"]["personnel_code"], "12345")
        mgr_emp, mgr_user = make_employee(self.branch, code="RM-1")
        grant(mgr_user, "REGION_MANAGER")
        self.client.force_authenticate(mgr_user)
        res = self.client.get("/api/v1/leaves/ledger/balances/?employee=12345")
        self.assertEqual(res.status_code, 200, res.content)

    def test_adjust_endpoint_appends_signed_entry(self):
        self.client.force_authenticate(self.hr_user)
        res = self.client.post(
            "/api/v1/leaves/ledger/adjust/",
            {"personnel_code": "12345", "leave_type": "ANNUAL", "minutes": -120},
            format="json",
        )
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.data["entry_kind"], LeaveEntryKind.ADJUST)
        self.assertEqual(res.data["balance_after_minutes"], -120)


class SubmissionGuardTests(TestCase):
    def setUp(self):
        self.branch = make_branch()
        self.emp, self.user = make_employee(self.branch)
        leave_type("ANNUAL")
        leave_type("SICK", name="استعلاجی")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _post(self, type_code="ANNUAL", hours=4):
        start, end = window(hours=hours)
        return self.client.post(
            "/api/v1/requests/leave/",
            {"leave_type": type_code, "starts_at": start.isoformat(), "ends_at": end.isoformat()},
        )

    def test_untracked_type_passes_without_seeding(self):
        res = self._post(type_code="SICK", hours=99)
        self.assertEqual(res.status_code, 201, res.content)

    def test_tracked_type_blocks_when_insufficient(self):
        LeaveLedger.objects.create(
            employee=self.emp, leave_type=leave_type("ANNUAL"),
            entry_kind=LeaveEntryKind.OPENING, minutes=240,
            balance_after_minutes=240, basis_date=timezone.localdate(),
        )
        res = self._post(hours=99)  # 5940 دقیقه > ۲۴۰
        self.assertEqual(res.status_code, 400, res.content)
        self.assertEqual(res.data["code"], "INSUFFICIENT_BALANCE")

    def test_tracked_type_allows_within_balance(self):
        LeaveLedger.objects.create(
            employee=self.emp, leave_type=leave_type("ANNUAL"),
            entry_kind=LeaveEntryKind.OPENING, minutes=12480,
            balance_after_minutes=12480, basis_date=timezone.localdate(),
        )
        res = self._post(hours=4)
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(LeaveLedger.objects.count(), 1)  # no deduction at submit


class DecisionDeductionTests(TestCase):
    def setUp(self):
        self.branch = make_branch()
        self.emp, self.user = make_employee(self.branch)
        self.mgr_emp, self.mgr_user = make_employee(self.branch, code="MGR-1")
        grant(self.mgr_user, "BRANCH_MANAGER", branch=self.branch)
        leave_type("ANNUAL")
        LeaveLedger.objects.create(
            employee=self.emp, leave_type=leave_type("ANNUAL"),
            entry_kind=LeaveEntryKind.OPENING, minutes=12480,
            balance_after_minutes=12480, basis_date=timezone.localdate(),
        )
        self.client = APIClient()

    def _submit(self, hours=4):
        start, end = window(hours=hours)
        return self.client_force_submit(start, end, hours)

    def client_force_submit(self, start, end, hours):
        self.client.force_authenticate(self.user)
        return self.client.post(
            "/api/v1/requests/leave/",
            {"leave_type": "ANNUAL", "starts_at": start.isoformat(), "ends_at": end.isoformat()},
        )

    def test_approve_appends_deduction_and_queue_shows_balance(self):
        res = self._submit(hours=4)  # 240 دقیقه
        self.assertEqual(res.status_code, 201, res.content)
        segment_id = res.data["segments"][0]["id"]

        self.client.force_authenticate(self.mgr_user)
        res = self.client.get("/api/v1/requests/queue/")
        self.assertEqual(res.status_code, 200)
        item = next(i for i in res.data["results"] if i["segment_id"] == segment_id)
        self.assertEqual(item["employee_balance_minutes"], 12480)

        res = self.client.post(
            "/api/v1/requests/queue/decide/",
            {"segment_id": segment_id, "action": ApprovalAction.APPROVE},
            format="json",
        )
        self.assertEqual(res.status_code, 200, res.content)
        entry = LeaveLedger.objects.filter(entry_kind=LeaveEntryKind.DEDUCTION).first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.minutes, -240)
        self.assertEqual(entry.balance_after_minutes, 12240)
        self.assertEqual(entry.source_type, "RequestSegment")
        self.assertEqual(entry.source_id, segment_id)

        # BRANCH_MANAGER cannot query balances directly (queue embed only)
        res = self.client.get("/api/v1/leaves/ledger/balances/?employee=12345")
        self.assertEqual(res.status_code, 403)
        # HR confirms the updated balance
        hr_emp, hr_user = make_employee(self.branch, code="HR-9")
        grant(hr_user, "HR")
        self.client.force_authenticate(hr_user)
        res = self.client.get("/api/v1/leaves/ledger/balances/?employee=12345")
        annual = next(b for b in res.data["balances"] if b["leave_type"] == "ANNUAL")
        self.assertEqual(annual["balance_minutes"], 12240)

    def test_reject_appends_nothing(self):
        res = self._submit(hours=2)
        self.assertEqual(res.status_code, 201, res.content)
        segment_id = res.data["segments"][0]["id"]
        self.client.force_authenticate(self.mgr_user)
        res = self.client.post(
            "/api/v1/requests/queue/decide/",
            {"segment_id": segment_id, "action": ApprovalAction.REJECT},
            format="json",
        )
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(
            LeaveLedger.objects.filter(entry_kind=LeaveEntryKind.DEDUCTION).count(), 0
        )
