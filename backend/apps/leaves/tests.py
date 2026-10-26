"""Requests domain tests — submission, branch split, independent decisions.

Covers approved decision #5 (multi-branch segments decided independently,
composed overall status), manager scoping, cancellation rules and the
manager board. Mirrors fixtures from apps.attendance.tests.
"""
from __future__ import annotations

import datetime as dt

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from django.utils import timezone

from apps.core.enums import ApprovalAction, RequestStatus, SegmentStatus
from apps.leaves.models import LeaveType, MissionRequest, RequestSegment
from apps.orgs.models import Branch, Region
from apps.people.models import Employee, Role, RoleAssignment, User
from apps.reports.api import ManagerBoardViewSet  # noqa: F401 - route registration smoke

from .models import LeaveRequest


def make_branch(code="B100", **over):
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


def leave_type(code="HOURLY", **over):
    fields = dict(name="استحقاقی", is_hourly=True)
    fields.update(over)
    lt, _ = LeaveType.objects.get_or_create(code=code, defaults=fields)
    return lt


def window(days_ahead=1, hours=4):
    start = timezone.make_aware(
        dt.datetime.combine(timezone.localdate() + dt.timedelta(days=days_ahead), dt.time(9, 0))
    )
    return start, start + dt.timedelta(hours=hours)


class SubmitTests(TestCase):
    def setUp(self):
        self.branch = make_branch()
        self.emp, self.user = make_employee(self.branch)
        leave_type()
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_submit_leave_creates_pending_segment_for_home_branch(self):
        start, end = window()
        res = self.client.post(
            "/api/v1/requests/leave/",
            {"leave_type": "HOURLY", "starts_at": start.isoformat(), "ends_at": end.isoformat(),
             "description": "پزشک"},
        )
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.data["status"], RequestStatus.PENDING)
        self.assertEqual(len(res.data["segments"]), 1)
        self.assertEqual(res.data["segments"][0]["branch"], "B100")
        self.assertEqual(res.data["segments"][0]["status"], SegmentStatus.PENDING)
        self.assertEqual(res.data["computed_minutes"], 240)

    def test_multi_branch_employee_gets_one_segment_per_branch(self):
        other = make_branch(code="B200")
        self.emp.branch_assignments.create(
            branch=other, is_allowed=True,
            valid_from=timezone.localdate() - dt.timedelta(days=1),
        )
        start, end = window()
        res = self.client.post(
            "/api/v1/requests/leave/",
            {"leave_type": "HOURLY", "starts_at": start.isoformat(), "ends_at": end.isoformat()},
        )
        self.assertEqual(res.status_code, 201)
        self.assertEqual(len(res.data["segments"]), 2)
        self.assertEqual({s["branch"] for s in res.data["segments"]}, {"B100", "B200"})

    def test_submit_mission(self):
        start, end = window()
        res = self.client.post(
            "/api/v1/requests/mission/",
            {"subject": "نمایشگاه", "destination_text": "نمایشگاه بین‌المللی",
             "starts_at": start.isoformat(), "ends_at": end.isoformat()},
        )
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.data["kind"], "MISSION")
        self.assertTrue(MissionRequest.objects.filter(subject="نمایشگاه").exists())

    def test_invalid_window_rejected(self):
        start, _ = window()
        res = self.client.post(
            "/api/v1/requests/leave/",
            {"leave_type": "HOURLY", "starts_at": start.isoformat(),
             "ends_at": (start - dt.timedelta(hours=1)).isoformat()},
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data["code"], "INVALID")

    def test_unknown_leave_type_rejected(self):
        start, end = window()
        res = self.client.post(
            "/api/v1/requests/leave/",
            {"leave_type": "NOPE", "starts_at": start.isoformat(), "ends_at": end.isoformat()},
        )
        self.assertEqual(res.status_code, 400)

    def test_leave_types_endpoint(self):
        leave_type()
        res = self.client.get("/api/v1/leave-types/")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(any(lt["code"] == "HOURLY" for lt in res.data["results"]))


class DecideTests(TestCase):
    def setUp(self):
        self.branch_a = make_branch("B100")
        self.branch_b = make_branch("B200")
        self.emp, self.user = make_employee(self.branch_a, code="12345")
        self.manager, self.manager_user = make_employee(self.branch_a, code="99001")
        grant(self.manager_user, "BRANCH_MANAGER", branch=self.branch_a)
        self.hr, self.hr_user = make_employee(self.branch_b, code="99002")
        grant(self.hr_user, "HR")
        self.client = APIClient()
        lt = leave_type()
        self.leave = LeaveRequest.objects.create(
            employee=self.emp, leave_type=lt,
            starts_at=timezone.make_aware(dt.datetime(2026, 10, 25, 9, 0)),
            ends_at=timezone.make_aware(dt.datetime(2026, 10, 25, 13, 0)),
            computed_minutes=240, overall_status=RequestStatus.PENDING,
        )
        self.segment = RequestSegment.objects.create(
            request_kind="LEAVE", leave_request=self.leave,
            branch=self.branch_a,
            starts_at=self.leave.starts_at, ends_at=self.leave.ends_at,
            computed_minutes=240, segment_status=SegmentStatus.PENDING,
        )

    def test_queue_scoped_to_manager_branch(self):
        client = APIClient(); client.force_authenticate(self.manager_user)
        res = client.get("/api/v1/requests/queue/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["count"], 1)
        self.assertEqual(res.data["results"][0]["segment_id"], self.segment.id)

    def test_employee_cannot_see_queue_or_decide(self):
        client = APIClient(); client.force_authenticate(self.user)
        self.assertEqual(client.get("/api/v1/requests/queue/").status_code, 403)
        res = client.post(
            "/api/v1/requests/queue/decide/",
            {"segment_id": self.segment.id, "action": "APPROVE"},
        )
        self.assertEqual(res.status_code, 403)

    def test_out_of_scope_segment_hidden_from_branch_manager(self):
        client = APIClient(); client.force_authenticate(self.manager_user)
        other_seg = RequestSegment.objects.create(
            request_kind="LEAVE", leave_request=self.leave,
            branch=self.branch_b,
            starts_at=self.leave.starts_at, ends_at=self.leave.ends_at,
            computed_minutes=240, segment_status=SegmentStatus.PENDING,
        )
        res = client.post(
            "/api/v1/requests/queue/decide/",
            {"segment_id": other_seg.id, "action": "APPROVE"},
        )
        self.assertEqual(res.status_code, 404)

    def test_approve_updates_segment_overall_and_logs_action(self):
        client = APIClient(); client.force_authenticate(self.manager_user)
        res = client.post(
            "/api/v1/requests/queue/decide/",
            {"segment_id": self.segment.id, "action": "APPROVE", "comment": "باشه"},
        )
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.data["segment_status"], SegmentStatus.APPROVED)
        self.leave.refresh_from_db()
        self.assertEqual(self.leave.overall_status, RequestStatus.APPROVED)
        self.assertTrue(self.segment.actions.filter(action=ApprovalAction.APPROVE).exists())

    def test_multi_branch_composition(self):
        seg_b = RequestSegment.objects.create(
            request_kind="LEAVE", leave_request=self.leave,
            branch=self.branch_b,
            starts_at=self.leave.starts_at, ends_at=self.leave.ends_at,
            computed_minutes=240, segment_status=SegmentStatus.PENDING,
        )
        client_m = APIClient(); client_m.force_authenticate(self.manager_user)
        client_hr = APIClient(); client_hr.force_authenticate(self.hr_user)
        res1 = client_m.post("/api/v1/requests/queue/decide/",
                             {"segment_id": self.segment.id, "action": "APPROVE"})
        self.assertEqual(res1.status_code, 200)
        self.leave.refresh_from_db()
        self.assertEqual(self.leave.overall_status, RequestStatus.PENDING)  # one branch still pending
        res2 = client_hr.post("/api/v1/requests/queue/decide/",
                              {"segment_id": seg_b.id, "action": "APPROVE"})
        self.assertEqual(res2.status_code, 200)
        self.leave.refresh_from_db()
        self.assertEqual(self.leave.overall_status, RequestStatus.APPROVED)

    def test_any_rejection_rejects_overall(self):
        seg_b = RequestSegment.objects.create(
            request_kind="LEAVE", leave_request=self.leave,
            branch=self.branch_b,
            starts_at=self.leave.starts_at, ends_at=self.leave.ends_at,
            computed_minutes=240, segment_status=SegmentStatus.PENDING,
        )
        client_hr = APIClient(); client_hr.force_authenticate(self.hr_user)
        res = client_hr.post("/api/v1/requests/queue/decide/",
                             {"segment_id": seg_b.id, "action": "REJECT", "comment": "تعداد کمبود"})
        self.assertEqual(res.status_code, 200)
        self.leave.refresh_from_db()
        self.assertEqual(self.leave.overall_status, RequestStatus.REJECTED)

    def test_double_decision_conflicts(self):
        self.segment.segment_status = SegmentStatus.APPROVED
        self.segment.save(update_fields=["segment_status"])
        client = APIClient(); client.force_authenticate(self.manager_user)
        res = client.post("/api/v1/requests/queue/decide/",
                          {"segment_id": self.segment.id, "action": "REJECT"})
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.data["code"], "ALREADY_DECIDED")


class CancelTests(TestCase):
    def setUp(self):
        self.branch = make_branch()
        self.emp, self.user = make_employee(self.branch)
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        lt = leave_type()
        self.leave = LeaveRequest.objects.create(
            employee=self.emp, leave_type=lt,
            starts_at=timezone.make_aware(dt.datetime(2026, 10, 25, 9, 0)),
            ends_at=timezone.make_aware(dt.datetime(2026, 10, 25, 13, 0)),
            computed_minutes=240, overall_status=RequestStatus.PENDING,
        )
        self.segment = RequestSegment.objects.create(
            request_kind="LEAVE", leave_request=self.leave, branch=self.branch,
            starts_at=self.leave.starts_at, ends_at=self.leave.ends_at,
            computed_minutes=240, segment_status=SegmentStatus.PENDING,
        )

    def test_cancel_own_pending_request(self):
        res = self.client.post("/api/v1/requests/cancel/",
                               {"kind": "LEAVE", "id": self.leave.id})
        self.assertEqual(res.status_code, 200)
        self.leave.refresh_from_db()
        self.segment.refresh_from_db()
        self.assertEqual(self.leave.overall_status, RequestStatus.CANCELLED)
        self.assertEqual(self.segment.segment_status, SegmentStatus.CANCELLED)

    def test_cannot_cancel_decided_request(self):
        self.segment.segment_status = SegmentStatus.REJECTED
        self.segment.save(update_fields=["segment_status"])
        self.leave.overall_status = RequestStatus.REJECTED
        self.leave.save(update_fields=["overall_status"])
        res = self.client.post("/api/v1/requests/cancel/",
                               {"kind": "LEAVE", "id": self.leave.id})
        self.assertEqual(res.status_code, 409)

    def test_cannot_cancel_someone_else_request(self):
        other_emp, other_user = make_employee(self.branch, code="777")
        client = APIClient(); client.force_authenticate(other_user)
        res = client.post("/api/v1/requests/cancel/", {"kind": "LEAVE", "id": self.leave.id})
        self.assertEqual(res.status_code, 404)

    def test_my_requests_listed_with_segments(self):
        res = self.client.get("/api/v1/requests/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["count"], 1)
        self.assertEqual(res.data["results"][0]["kind"], "LEAVE")
        self.assertEqual(len(res.data["results"][0]["segments"]), 1)


class ManagerBoardTests(TestCase):
    def setUp(self):
        self.branch = make_branch()
        self.emp, self.user = make_employee(self.branch)
        self.manager, self.manager_user = make_employee(self.branch, code="99001")
        grant(self.manager_user, "BRANCH_MANAGER", branch=self.branch)

    def test_board_requires_manager(self):
        client = APIClient(); client.force_authenticate(self.user)
        self.assertEqual(client.get("/api/v1/reports/manager-board/").status_code, 403)

    def test_board_lists_employee_row(self):
        client = APIClient(); client.force_authenticate(self.manager_user)
        today = timezone.localdate()
        res = client.get(f"/api/v1/reports/manager-board/?date={today.isoformat()}")
        self.assertEqual(res.status_code, 200, res.content)
        codes = [r["employee"]["personnel_code"] for r in res.data["results"]]
        self.assertIn("12345", codes)
        row = next(r for r in res.data["results"] if r["employee"]["personnel_code"] == "12345")
        self.assertEqual(row["branch"], "B100")
