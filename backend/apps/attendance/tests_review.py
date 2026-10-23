"""Review-flow completion tests — reject path + branch-manager alerts.

Complements ReviewFlowTests (approve path in tests.py):
- POST review-queue/reject → REJECTED_TECHNICAL + VOID adjustment + no pairing
- stale punch persists a REVIEW_REQUIRED Notification for branch managers
- employees / non-managers get neither the queue nor reject access
"""
from __future__ import annotations

import datetime as dt
import uuid

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.enums import ConnectionMode, EventStatus, EventType, SessionState
from apps.messaging.models import Notification
from apps.orgs.models import Branch
from apps.people.models import Employee, User

from .models import AttendanceAdjustment, AttendanceEvent, AttendanceSession
from .services import receive_punch
from .tests import grant, make_branch, make_employee


class RejectReviewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.branch = make_branch()
        self.emp, self.emp_user = make_employee(self.branch)
        self.mgr_emp = Employee.objects.create(
            personnel_code="99901", first_name="مدیر", last_name="شعبه",
            home_branch=self.branch,
        )
        self.mgr = User.objects.create_user(
            username="manager2", password="S3cret!Pass", employee=self.mgr_emp
        )
        grant(self.mgr, "BRANCH_MANAGER", branch=self.branch)
        self.reject_url = reverse("review-queue-reject")

    def _stale_event(self):
        return receive_punch(
            employee=self.emp, branch=self.branch,
            event_type=EventType.CHECK_IN, event_uuid=uuid.uuid4(),
            device_time=timezone.now() - dt.timedelta(days=9),
            connection_mode=ConnectionMode.OFFLINE_SYNC, channel="ANDROID",
        )[0]

    def test_reject_marks_event_and_creates_void_adjustment(self):
        stale = self._stale_event()
        self.client.force_authenticate(self.mgr)
        r = self.client.post(
            self.reject_url,
            {"event_uuid": str(stale.event_uuid), "reason": "رویداد آزمایشی دستگاه"},
            format="json",
        )
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["event_status"], EventStatus.REJECTED_TECHNICAL)
        stale.refresh_from_db()
        self.assertEqual(stale.event_status, EventStatus.REJECTED_TECHNICAL)
        self.assertIn("REVIEW_REJECTED", stale.flags)
        self.assertIn("REVIEW_RESOLVED", stale.flags)
        adj = AttendanceAdjustment.objects.get(target_event=stale)
        self.assertEqual(adj.adjustment_kind, "VOID")
        self.assertEqual(adj.decided_by, self.mgr)
        # rejected event never enters pairing
        self.assertFalse(
            AttendanceSession.objects.filter(check_in_event=stale).exists()
        )

    def test_reject_requires_reason(self):
        stale = self._stale_event()
        self.client.force_authenticate(self.mgr)
        r = self.client.post(
            self.reject_url, {"event_uuid": str(stale.event_uuid), "reason": "  "},
            format="json",
        )
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["code"], "REASON_REQUIRED")
        stale.refresh_from_db()
        self.assertEqual(stale.event_status, EventStatus.NEEDS_REVIEW)

    def test_employee_cannot_reject(self):
        stale = self._stale_event()
        self.client.force_authenticate(self.emp_user)
        r = self.client.post(
            self.reject_url,
            {"event_uuid": str(stale.event_uuid), "reason": "دلیل پرسنل"},
            format="json",
        )
        self.assertEqual(r.status_code, 403)
        stale.refresh_from_db()
        self.assertEqual(stale.event_status, EventStatus.NEEDS_REVIEW)

    def test_rejected_event_leaves_queue(self):
        stale = self._stale_event()
        self.client.force_authenticate(self.mgr)
        self.client.post(
            self.reject_url,
            {"event_uuid": str(stale.event_uuid), "reason": "دوبار ثبت شد"},
            format="json",
        )
        r = self.client.get(reverse("review-queue-list"))
        uuids = [item["event_uuid"] for item in r.data["results"]]
        self.assertNotIn(str(stale.event_uuid), uuids)


class ManagerAlertTests(TestCase):
    def setUp(self):
        self.branch = make_branch(code="B200", name="شعبهٔ دوم")
        self.emp, _user = make_employee(self.branch, code="55555")
        self.mgr_emp = Employee.objects.create(
            personnel_code="88888", first_name="مدیر", last_name="دوم",
            home_branch=self.branch,
        )
        self.mgr = User.objects.create_user(
            username="manager3", password="S3cret!Pass", employee=self.mgr_emp
        )
        grant(self.mgr, "BRANCH_MANAGER", branch=self.branch)

    def test_stale_punch_notifies_branch_manager(self):
        self.assertEqual(Notification.objects.count(), 0)
        receive_punch(
            employee=self.emp, branch=self.branch,
            event_type=EventType.CHECK_OUT, event_uuid=uuid.uuid4(),
            device_time=timezone.now() - dt.timedelta(days=10),
            connection_mode=ConnectionMode.OFFLINE_SYNC, channel="ANDROID",
        )
        rows = Notification.objects.filter(recipient=self.mgr_emp, kind="REVIEW_REQUIRED")
        self.assertEqual(rows.count(), 1)
        payload = rows.first().payload
        self.assertEqual(payload["personnel_code"], "55555")

    def test_online_accepted_punch_does_not_notify(self):
        receive_punch(
            employee=self.emp, branch=self.branch,
            event_type=EventType.CHECK_IN, event_uuid=uuid.uuid4(),
            device_time=None, connection_mode=ConnectionMode.ONLINE, channel="PWA",
        )
        self.assertFalse(Notification.objects.filter(kind="REVIEW_REQUIRED").exists())

    def test_manager_without_employee_profile_is_skipped(self):
        # Manager account without a personnel file — must not crash ingestion.
        User.objects.create_user(username="bare-mgr", password="S3cret!Pass", employee=None)
        grant(User.objects.get(username="bare-mgr"), "BRANCH_MANAGER", branch=self.branch)
        receive_punch(
            employee=self.emp, branch=self.branch,
            event_type=EventType.CHECK_IN, event_uuid=uuid.uuid4(),
            device_time=timezone.now() - dt.timedelta(days=8),
            connection_mode=ConnectionMode.OFFLINE_SYNC, channel="ANDROID",
        )
        self.assertEqual(
            Notification.objects.filter(kind="REVIEW_REQUIRED").count(), 1
        )  # only the profiled manager

    def test_other_branch_manager_not_notified(self):
        other = make_branch(code="B300", name="شعبهٔ سوم")
        other_mgr_emp = Employee.objects.create(
            personnel_code="77777", first_name="مدیر", last_name="سوم",
            home_branch=other,
        )
        other_mgr = User.objects.create_user(
            username="manager4", password="S3cret!Pass", employee=other_mgr_emp
        )
        grant(other_mgr, "BRANCH_MANAGER", branch=other)
        receive_punch(
            employee=self.emp, branch=self.branch,
            event_type=EventType.CHECK_IN, event_uuid=uuid.uuid4(),
            device_time=timezone.now() - dt.timedelta(days=9),
            connection_mode=ConnectionMode.OFFLINE_SYNC, channel="ANDROID",
        )
        self.assertFalse(
            Notification.objects.filter(recipient=other_mgr_emp).exists()
        )
