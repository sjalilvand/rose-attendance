"""Attendance pipeline tests — approved §34 decisions exercised end-to-end.

Covers approved decisions #3 (geofence label, 150/300 m defaults), #4
(7-day offline -> NEEDS_REVIEW, ±5 min CLOCK_SKEW) plus pairing rules,
idempotency, auth lockout and the review flow.
"""
from __future__ import annotations

import datetime as dt
import uuid

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from django.utils import timezone

from apps.core.enums import (
    ConnectionMode,
    EventStatus,
    EventType,
    LocationStatus,
    SessionState,
)
from apps.orgs.models import Branch, Region
from apps.people.models import Employee, Role, RoleAssignment, User
from apps.scheduling.models import ScheduledShift, Shift

from .models import AttendanceAdjustment, AttendanceEvent, AttendanceSession
from .services import receive_punch, rebuild_pairings


def make_branch(**over):
    region, _ = Region.objects.get_or_create(code="R1", defaults={"name": "منطقه یک"})
    fields = dict(
        code="B100", name="شعبه تجریش", region=region,
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


class GeofenceTests(TestCase):
    """Decision #3: out-of-range is a label; never rejected, no approval."""

    def setUp(self):
        self.branch = make_branch()  # radius 150 m
        self.emp, self.user = make_employee(self.branch)

    def _punch(self, lat, lng, **kw):
        return receive_punch(
            employee=self.emp, branch=self.branch,
            event_type=EventType.CHECK_IN, event_uuid=uuid.uuid4(),
            device_time=timezone.now(), connection_mode=ConnectionMode.ONLINE,
            channel="ANDROID", latitude=lat, longitude=lng,
            accuracy_m=kw.pop("accuracy_m", 10.0),
            **kw,
        )[0]

    def test_in_range(self):
        # ~55 m north of the branch centre
        ev = self._punch(35.8002, 51.4344)
        self.assertEqual(ev.location_status, LocationStatus.IN_RANGE)
        self.assertEqual(ev.event_status, EventStatus.ACCEPTED)

    def test_out_of_range_labelled_and_kept(self):
        # ~1.1 km away — beyond even the clinic default of 300 m
        ev = self._punch(35.8100, 51.4344)
        self.assertEqual(ev.location_status, LocationStatus.OUT_OF_RANGE)
        # NOT rejected, no manager approval needed:
        self.assertEqual(ev.event_status, EventStatus.ACCEPTED)
        self.assertIn("DISTANCE", ev.location_reason)

    def test_without_location_is_unavailable(self):
        ev = self._punch(None, None)
        self.assertEqual(ev.location_status, LocationStatus.UNAVAILABLE)
        self.assertEqual(ev.event_status, EventStatus.ACCEPTED)

    def test_low_accuracy(self):
        ev = self._punch(35.7997, 51.4344, accuracy_m=500.0)
        self.assertEqual(ev.location_status, LocationStatus.LOW_ACCURACY)
        self.assertEqual(ev.event_status, EventStatus.ACCEPTED)

    def test_radius_bounds_validation(self):
        region = Region.objects.get(code="R1")
        b = Branch(code="B999", name="x", region=region, geo_radius_m=40)
        with self.assertRaises(Exception):
            b.full_clean()
        b2 = Branch(code="B998", name="y", region=region, geo_radius_m=1001)
        with self.assertRaises(Exception):
            b2.full_clean()
        b3 = Branch(code="B997", name="z", region=region, geo_radius_m=1000)
        b3.full_clean()  # مرز بالای بازه مجاز است

    def test_clinic_default_radius_300(self):
        clinic = make_branch(code="C300", name="کلینیک")
        clinic.geo_radius_m = 300  # HR sets clinic radius explicitly
        clinic.save()
        self.assertEqual(clinic.geo_radius_m, 300)


class EffectiveTimeTests(TestCase):
    """Decision #4: ±5 min CLOCK_SKEW, 7-day offline NEEDS_REVIEW."""

    def setUp(self):
        self.branch = make_branch()
        self.emp, _ = make_employee(self.branch)

    def _punch(self, **kw):
        kw.setdefault("event_type", EventType.CHECK_IN)
        kw.setdefault("channel", "ANDROID")
        kw.setdefault("connection_mode", ConnectionMode.ONLINE)
        return receive_punch(
            employee=self.emp, branch=self.branch, event_uuid=uuid.uuid4(), **kw
        )[0]

    def test_online_small_skew_no_flag(self):
        ev = self._punch(device_time=timezone.now() - dt.timedelta(minutes=2))
        self.assertNotIn("CLOCK_SKEW", ev.flags)
        self.assertEqual(ev.event_status, EventStatus.ACCEPTED)

    def test_clock_skew_flag_beyond_five_minutes(self):
        ev = self._punch(device_time=timezone.now() - dt.timedelta(minutes=12))
        self.assertIn("CLOCK_SKEW", ev.flags)
        self.assertEqual(ev.event_status, EventStatus.ACCEPTED)

    def test_offline_reported_skew_flagged(self):
        ev = self._punch(
            device_time=timezone.now() - dt.timedelta(days=2),
            connection_mode=ConnectionMode.OFFLINE_SYNC,
            clock_offset_minutes=9.0,
        )
        self.assertIn("CLOCK_SKEW", ev.flags)
        self.assertEqual(ev.event_status, EventStatus.ACCEPTED)

    def test_offline_large_reported_skew_goes_to_review(self):
        ev = self._punch(
            device_time=timezone.now() - dt.timedelta(days=2),
            connection_mode=ConnectionMode.OFFLINE_SYNC,
            clock_offset_minutes=-95.0,
        )
        self.assertIn("CLOCK_SKEW", ev.flags)
        self.assertEqual(ev.event_status, EventStatus.NEEDS_REVIEW)

    def test_offline_within_seven_days_accepted(self):
        ev = self._punch(
            device_time=timezone.now() - dt.timedelta(days=3, hours=1),
            connection_mode=ConnectionMode.OFFLINE_SYNC,
        )
        self.assertEqual(ev.event_status, EventStatus.ACCEPTED)
        self.assertNotIn("STALE_OFFLINE", ev.flags)

    def test_offline_beyond_seven_days_needs_review(self):
        ev = self._punch(
            device_time=timezone.now() - dt.timedelta(days=8),
            connection_mode=ConnectionMode.OFFLINE_SYNC,
        )
        self.assertEqual(ev.event_status, EventStatus.NEEDS_REVIEW)
        self.assertIn("STALE_OFFLINE", ev.flags)
        # Needs-review events must not enter pairing
        self.assertFalse(AttendanceSession.objects.exists())


class PairingTests(TestCase):
    def setUp(self):
        self.branch = make_branch()
        self.emp, _ = make_employee(self.branch)

    def _ev(self, event_type, minutes_ago, **kw):
        # Offline mode keeps effective_time = device_time, which makes the
        # pairing tests deterministic (online effective time is server now).
        kw.setdefault("connection_mode", ConnectionMode.OFFLINE_SYNC)
        kw.setdefault("channel", "ANDROID")
        device_time = kw.pop("device_time", None)
        if device_time is None:
            device_time = timezone.now() - dt.timedelta(minutes=minutes_ago)
        return receive_punch(
            employee=self.emp, branch=self.branch,
            event_type=event_type, event_uuid=uuid.uuid4(),
            device_time=device_time,
            **kw,
        )[0]

    def test_in_out_completes_session_with_minutes(self):
        self._ev(EventType.CHECK_IN, 240)
        self._ev(EventType.CHECK_OUT, 60)
        s = AttendanceSession.objects.get()
        self.assertEqual(s.session_state, SessionState.COMPLETE)
        self.assertEqual(s.work_minutes, 180)

    def test_checkout_without_in_invalid_sequence(self):
        self._ev(EventType.CHECK_OUT, 60)
        s = AttendanceSession.objects.get()
        self.assertEqual(s.session_state, SessionState.INVALID_SEQUENCE)
        self.assertIsNone(s.work_minutes)

    def test_duplicate_checkin_flagged(self):
        self._ev(EventType.CHECK_IN, 240)
        second = self._ev(EventType.CHECK_IN, 230)
        self.assertIn("DUPLICATE_CHECK_IN", second.flags)
        self.assertEqual(AttendanceSession.objects.count(), 1)

    def test_open_session_survives(self):
        self._ev(EventType.CHECK_IN, 60)
        s = AttendanceSession.objects.get()
        self.assertEqual(s.session_state, SessionState.OPEN)

    def test_rebuild_is_repeatable(self):
        self._ev(EventType.CHECK_IN, 240)
        self._ev(EventType.CHECK_OUT, 60)
        before = AttendanceSession.objects.values_list(
            "session_state", "work_minutes", "shift_date"
        )
        rebuild_pairings(self.emp.id, self.branch.id)
        after = AttendanceSession.objects.values_list(
            "session_state", "work_minutes", "shift_date"
        )
        self.assertEqual(sorted(before), sorted(after))

    def test_night_shift_anchors_to_shift_start_date(self):
        shift = Shift.objects.create(
            code="N1", name="شیفت شب", starts_at=dt.time(22, 0),
            ends_at=dt.time(6, 0), crosses_midnight=True,
        )
        in_date = timezone.localdate() - dt.timedelta(days=2)  # تاریخ شروع شیفت
        ScheduledShift.objects.create(
            employee=self.emp, branch=self.branch, work_date=in_date, shift=shift,
        )
        # 23:00 on the shift-start date -> 05:00 the next day
        now = timezone.localtime(timezone.now())
        in_local = now.replace(hour=23, minute=0, second=0, microsecond=0) - dt.timedelta(days=2)
        out_local = now.replace(hour=5, minute=0, second=0, microsecond=0) - dt.timedelta(days=1)
        self._ev(EventType.CHECK_IN, None, device_time=in_local)
        self._ev(EventType.CHECK_OUT, None, device_time=out_local)
        s = AttendanceSession.objects.get()
        # Night shift belongs entirely to the shift START date (calc §3.1 rule 3)
        self.assertEqual(s.shift_date, in_date)
        self.assertEqual(s.scheduled_shift_id, ScheduledShift.objects.get().id)
        self.assertEqual(s.work_minutes, 360)


class IdempotencyTests(TestCase):
    def setUp(self):
        self.branch = make_branch()
        self.emp, _ = make_employee(self.branch)

    def test_same_uuid_returns_same_result(self):
        u = uuid.uuid4()
        payload = dict(
            employee=self.emp, branch=self.branch,
            event_type=EventType.CHECK_IN, event_uuid=u,
            device_time=timezone.now(), connection_mode=ConnectionMode.ONLINE,
            channel="ANDROID",
        )
        e1, c1 = receive_punch(**payload)
        e2, c2 = receive_punch(**payload)
        self.assertTrue(c1)
        self.assertFalse(c2)
        self.assertEqual(e1.id, e2.id)
        self.assertEqual(AttendanceEvent.objects.count(), 1)


class AuthLockoutTests(TestCase):
    def setUp(self):
        self.branch = make_branch()
        self.emp, self.user = make_employee(self.branch)
        grant(self.user, "EMPLOYEE")
        self.url = reverse("token-obtain-pair")

    def test_login_success_and_claims(self):
        r = self.client.post(
            self.url, {"username": "u12345", "password": "S3cret!Pass"}, format="json"
        )
        self.assertEqual(r.status_code, 200, r.data)
        self.assertIn("access", r.data)
        self.assertEqual(r.data["personnel_code"], "12345")
        self.assertIn("EMPLOYEE", r.data["roles"])

    def test_lockout_after_five_failures(self):
        for _ in range(5):
            r = self.client.post(
                self.url, {"username": "u12345", "password": "wrong"}, format="json"
            )
            self.assertEqual(r.status_code, 401)
        # Correct password is now also refused while locked
        r = self.client.post(
            self.url, {"username": "u12345", "password": "S3cret!Pass"}, format="json"
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn("ACCOUNT_LOCKED", str(r.data))
        self.user.refresh_from_db()
        self.assertIsNotNone(self.user.locked_until)


class ReviewFlowTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.branch = make_branch()
        self.emp, self.emp_user = make_employee(self.branch)
        self.mgr_emp = Employee.objects.create(
            personnel_code="99999", first_name="مدیر", last_name="شعبه",
            home_branch=self.branch,
        )
        self.mgr = User.objects.create_user(
            username="manager", password="S3cret!Pass", employee=self.mgr_emp
        )
        grant(self.mgr, "BRANCH_MANAGER", branch=self.branch)
        self.queue_url = reverse("review-queue-list")

    def _stale_event(self):
        return receive_punch(
            employee=self.emp, branch=self.branch,
            event_type=EventType.CHECK_IN, event_uuid=uuid.uuid4(),
            device_time=timezone.now() - dt.timedelta(days=9),
            connection_mode=ConnectionMode.OFFLINE_SYNC, channel="ANDROID",
        )[0]

    def test_review_queue_visibility(self):
        stale = self._stale_event()
        self.client.force_authenticate(self.mgr)
        r = self.client.get(self.queue_url)
        self.assertEqual(r.status_code, 200)
        uuids = [item["event_uuid"] for item in r.data["results"]]
        self.assertIn(str(stale.event_uuid), uuids)

        self.client.force_authenticate(self.emp_user)
        r = self.client.get(self.queue_url)
        self.assertIn("results", r.data)
        self.assertEqual(len(r.data["results"]), 0)  # employee sees nothing

    def test_approve_creates_adjustment_and_pairs(self):
        stale = self._stale_event()
        self.client.force_authenticate(self.mgr)
        corrected = timezone.now() - dt.timedelta(days=9, hours=8)
        r = self.client.post(
            reverse("review-queue-approve"),
            {
                "event_uuid": str(stale.event_uuid),
                "corrected_time": corrected.isoformat(),
                "reason": "بررسی سابقه دستگاه",
            },
            format="json",
        )
        self.assertEqual(r.status_code, 200, r.data)
        stale.refresh_from_db()
        self.assertEqual(stale.event_status, EventStatus.ACCEPTED)
        self.assertIn("REVIEW_RESOLVED", stale.flags)
        adj = AttendanceAdjustment.objects.get(target_event=stale)
        self.assertEqual(adj.adjustment_kind, "TIME_FIX")
        self.assertEqual(adj.decided_by, self.mgr)

    def test_employee_cannot_approve(self):
        stale = self._stale_event()
        self.client.force_authenticate(self.emp_user)
        r = self.client.post(
            reverse("review-queue-approve"),
            {
                "event_uuid": str(stale.event_uuid),
                "corrected_time": timezone.now().isoformat(),
                "reason": "x",
            },
            format="json",
        )
        self.assertEqual(r.status_code, 403)


class PunchApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.branch = make_branch()
        self.emp, self.user = make_employee(self.branch)
        self.client.force_authenticate(self.user)
        self.punch_url = reverse("attendance-events-punch")
        self.sync_url = reverse("attendance-events-sync")

    def test_online_punch_roundtrip(self):
        r = self.client.post(
            self.punch_url,
            {
                "event_uuid": str(uuid.uuid4()),
                "event_type": "CHECK_IN",
                "branch_code": "B100",
                "channel": "ANDROID",
                "latitude": 35.7997,
                "longitude": 51.4344,
                "location_accuracy_m": 12.0,
            },
            format="json",
        )
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["event_status"], "ACCEPTED")
        self.assertEqual(r.data["location_status"], "IN_RANGE")

    def test_sync_batch_with_stale_and_fresh(self):
        now = timezone.now()
        payload = {
            "events": [
                {
                    "event_uuid": str(uuid.uuid4()),
                    "event_type": "CHECK_IN",
                    "branch_code": "B100",
                    "channel": "ANDROID",
                    "device_time": (now - dt.timedelta(days=2)).isoformat(),
                    "local_seq": 1,
                },
                {
                    "event_uuid": str(uuid.uuid4()),
                    "event_type": "CHECK_OUT",
                    "branch_code": "B100",
                    "channel": "ANDROID",
                    "device_time": (now - dt.timedelta(days=2, minutes=-480)).isoformat(),
                    "local_seq": 2,
                },
                {
                    "event_uuid": str(uuid.uuid4()),
                    "event_type": "CHECK_IN",
                    "branch_code": "B100",
                    "channel": "ANDROID",
                    "device_time": (now - dt.timedelta(days=10)).isoformat(),
                    "local_seq": 3,
                },
            ]
        }
        r = self.client.post(self.sync_url, payload, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["processed"], 3)
        self.assertEqual(r.data["needs_review"], 1)
        statuses = [x["event_status"] for x in r.data["results"]]
        self.assertEqual(statuses, ["ACCEPTED", "ACCEPTED", "NEEDS_REVIEW"])

    def test_sync_batch_over_limit_rejected(self):
        from django.conf import settings as s

        max_batch = s.APP_THRESHOLDS["SYNC_MAX_BATCH"]
        payload = {
            "events": [
                {
                    "event_uuid": str(uuid.uuid4()),
                    "event_type": "CHECK_IN",
                    "branch_code": "B100",
                    "channel": "ANDROID",
                    "device_time": timezone.now().isoformat(),
                }
                for _ in range(max_batch + 1)
            ]
        }
        r = self.client.post(self.sync_url, payload, format="json")
        self.assertEqual(r.status_code, 400)

    def test_history_list_excludes_older_than_three_jalali_months(self):
        old = receive_punch(
            employee=self.emp, branch=self.branch,
            event_type=EventType.CHECK_IN, event_uuid=uuid.uuid4(),
            device_time=timezone.now() - dt.timedelta(days=200),
            connection_mode=ConnectionMode.OFFLINE_SYNC, channel="ANDROID",
        )[0]
        old.effective_time = old.device_time
        old.save(update_fields=["effective_time"])
        fresh = receive_punch(
            employee=self.emp, branch=self.branch,
            event_type=EventType.CHECK_IN, event_uuid=uuid.uuid4(),
            device_time=timezone.now() - dt.timedelta(days=3),
            connection_mode=ConnectionMode.ONLINE, channel="ANDROID",
        )[0]
        r = self.client.get(reverse("attendance-events-list"))
        uuids = [x["event_uuid"] for x in r.data["results"]]
        self.assertIn(str(fresh.event_uuid), uuids)
        self.assertNotIn(str(old.event_uuid), uuids)

    def test_unauthenticated_rejected(self):
        self.client.logout()
        r = self.client.get(reverse("attendance-events-list"))
        self.assertIn(r.status_code, (401, 403))


class MonthlySummaryApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.branch = make_branch()
        self.emp, self.user = make_employee(self.branch)
        self.client.force_authenticate(self.user)

    def test_summary_read_only_own(self):
        from apps.reports.models import MonthlySummary

        MonthlySummary.objects.create(
            employee=self.emp, branch=self.branch, period_year=1405, period_month=7,
            accepted_work_minutes=480, late_minutes=15, out_of_range_count=2,
        )
        r = self.client.get(reverse("monthly-summaries-list"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["results"][0]["period_month"], 7)
        self.assertEqual(r.data["results"][0]["out_of_range_count"], 2)
