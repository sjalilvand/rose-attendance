"""Monthly rollup + period closure tests — calculation-rules §7.4 and §9.

Jalali boundaries (approved decision #2), repeatable rollup, late forgiveness,
overtime approval effect, shortage, guards of close_month and the daily/today
API contract of the PWA.
"""
from __future__ import annotations

import datetime as dt
import uuid

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.enums import RestMode, RuleKind, RuleScope, RuleStatus, SegmentStatus
from apps.core.jalali import jalali_month_range
from apps.leaves.models import LeaveRequest, LeaveType, RequestSegment
from apps.orgs.models import Branch, Region
from apps.people.models import Employee, Role, RoleAssignment, User
from apps.rules.models import RuleSet
from apps.scheduling.models import ScheduledShift, Shift

from apps.attendance.models import AttendanceEvent, AttendanceSession, OvertimeProposal
from apps.attendance.services import apply_event_to_pairing

from .models import MonthlyClosure, MonthlySummary
from .services import close_month, recompute_month_summary


def make_branch(**over):
    region, _ = Region.objects.get_or_create(code="R1", defaults={"name": "منطقه یک"})
    fields = dict(code="B100", name="شعبه تجریش", region=region,
                  geo_latitude=35.7997, geo_longitude=51.4344, geo_radius_m=150)
    fields.update(over)
    return Branch.objects.create(**fields)


def make_employee(branch, code="12345"):
    emp = Employee.objects.create(
        personnel_code=code, first_name="علی", last_name="رضایی", home_branch=branch,
    )
    user = User.objects.create_user(username=f"u{code}", password="S3cret!Pass", employee=emp)
    return emp, user


def grant(user, code, branch=None):
    RoleAssignment.objects.create(
        user=user, role=Role.objects.get(code=code), branch=branch,
        valid_from=timezone.localdate() - dt.timedelta(days=1),
    )


def tehran(date_: dt.date, hour: int, minute: int = 0):
    return dt.datetime.combine(date_, dt.time(hour, minute)).replace(
        tzinfo=timezone.get_current_timezone()
    )


class JalaliBoundaryTests(TestCase):
    def test_mehr_1405_span(self):
        first, last = jalali_month_range(1405, 7)
        self.assertEqual(first, dt.date(2026, 9, 23))
        self.assertEqual(last, dt.date(2026, 10, 22))

    def test_farvardin_1404_span(self):
        first, last = jalali_month_range(1404, 1)
        self.assertEqual(first, dt.date(2025, 3, 21))
        self.assertEqual(last, dt.date(2025, 4, 20))

    def test_esfand_leap_1403_has_30_days(self):
        first, last = jalali_month_range(1403, 12)
        self.assertEqual(last, dt.date(2025, 3, 20))
        self.assertEqual((last - first).days + 1, 30)


class RollupTestBase(TestCase):
    """Month 1405/07 — today is 1405/08/01, so the whole month is in the past
    (fixed device times never fall into the offline-stale trap of pairing)."""

    def setUp(self):
        self.branch = make_branch()
        self.emp, self.user = make_employee(self.branch)
        self.shift = Shift.objects.create(
            code="D1", name="اداری", starts_at=dt.time(9, 0), ends_at=dt.time(17, 0),
            rest_minutes=60, rest_mode=RestMode.FIXED,
        )
        # شیفت‌های ماه: روزهای کاری هفته (شنبه تا چهارشنبه) نمونه کافی است
        self.work_date = dt.date(2026, 10, 12)  # ۲۰ مهر
        self.sched = ScheduledShift.objects.create(
            employee=self.emp, branch=self.branch, work_date=self.work_date, shift=self.shift,
        )

    def punch(self, kind, when):
        event = AttendanceEvent.objects.create(
            event_uuid=uuid.uuid4(), employee=self.emp, branch=self.branch,
            event_type=kind, device_time=when, effective_time=when,
            channel="PWA", connection_mode="OFFLINE_SYNC",
            event_status="ACCEPTED",
        )
        apply_event_to_pairing(event)
        return event


class RollupTests(RollupTestBase):
    def test_rollup_counters_and_repeatable(self):
        d = self.work_date
        # روز کامل با ۱۵ دقیقه تأخیر
        self.punch("CHECK_IN", tehran(d, 9, 15))
        self.punch("CHECK_OUT", tehran(d, 17, 0))
        s1 = recompute_month_summary(self.emp.id, self.branch.id, 1405, 7)
        s2 = recompute_month_summary(self.emp.id, self.branch.id, 1405, 7)
        self.assertEqual(s2.accepted_work_minutes, 405)  # 480 − 60 rest − 15 late-punish? نه: کارکرد مستقل از تأخیر
        self.assertEqual(s2.accepted_work_minutes, s1.accepted_work_minutes)
        self.assertEqual(s2.late_minutes, 15)  # بدون قاعده: FLAG_ONLY ولی شمرده می‌شود
        self.assertEqual(s2.summary_state, "PROVISIONAL")
        self.assertEqual(s2.period_year, 1405)
        self.assertEqual(s2.period_month, 7)

    def test_out_of_range_counter_from_events(self):
        d = self.work_date
        far = self.punch("CHECK_IN", tehran(d, 9, 0))
        far.latitude, far.longitude = 35.8100, 51.4344  # ~1.1km
        far.location_status = "OUT_OF_RANGE"
        far.save(update_fields=["latitude", "longitude", "location_status"])
        self.punch("CHECK_OUT", tehran(d, 17, 0))
        s = recompute_month_summary(self.emp.id, self.branch.id, 1405, 7)
        self.assertEqual(s.out_of_range_count, 1)

    def test_incomplete_session_counted(self):
        self.punch("CHECK_IN", tehran(self.work_date, 9, 0))  # بدون خروج
        s = recompute_month_summary(self.emp.id, self.branch.id, 1405, 7)
        self.assertEqual(s.incomplete_session_count, 1)

    def test_late_forgiveness_monthly(self):
        RuleSet.objects.create(
            rule_kind=RuleKind.LATE, scope=RuleScope.GLOBAL, payload={
                "grace_minutes": 0,
                "tiers": [{"above_minutes": 0, "deduct_mode": "DEDUCT", "multiplier": 1.0}],
                "monthly_forgive_count": 2, "rounding_minutes": 1,
            },
            effective_from=dt.date(2024, 1, 1), status=RuleStatus.ACTIVE,
        )
        days = [dt.date(2026, 10, 12), dt.date(2026, 10, 13), dt.date(2026, 10, 14)]
        for i, d in enumerate(days):
            ScheduledShift.objects.get_or_create(
                employee=self.emp, branch=self.branch, work_date=d,
                defaults=dict(shift=self.shift),
            )
            self.punch("CHECK_IN", tehran(d, 9, 5 + i))   # تأخیرهای ۵/۶/۷ دقیقه
            self.punch("CHECK_OUT", tehran(d, 17, 0))
        s = recompute_month_summary(self.emp.id, self.branch.id, 1405, 7)
        # دو تأخیر اول (۵ و ۶ دقیقه) بخشیده می‌شود؛ ۷ دقیقه باقی می‌ماند
        self.assertEqual(s.late_minutes, 7)

    def test_overtime_only_approved_enters_summary(self):
        d = self.work_date
        self.punch("CHECK_IN", tehran(d, 9, 0))
        self.punch("CHECK_OUT", tehran(d, 18, 0))  # 60 دقیقه فراتر
        s1 = recompute_month_summary(self.emp.id, self.branch.id, 1405, 7)
        self.assertEqual(s1.overtime_minutes, 0)  # بدون تأیید مدیر
        proposal = OvertimeProposal.objects.get()
        self.assertEqual(proposal.proposed_minutes, 60)
        proposal.status = SegmentStatus.APPROVED
        proposal.approved_minutes = 60
        proposal.save()
        s2 = recompute_month_summary(self.emp.id, self.branch.id, 1405, 7)
        self.assertEqual(s2.overtime_minutes, 60)

    def test_rule_set_ids_recorded(self):
        rule = RuleSet.objects.create(
            rule_kind=RuleKind.LATE, scope=RuleScope.GLOBAL,
            payload={"grace_minutes": 5, "tiers": [{"above_minutes": 0, "deduct_mode": "FLAG_ONLY"}]},
            effective_from=dt.date(2024, 1, 1), status=RuleStatus.ACTIVE,
        )
        self.punch("CHECK_IN", tehran(self.work_date, 9, 30))
        self.punch("CHECK_OUT", tehran(self.work_date, 17, 0))
        s = recompute_month_summary(self.emp.id, self.branch.id, 1405, 7)
        self.assertIn(rule.id, s.rule_set_ids)


class LeaveOverlapRollupTests(RollupTestBase):
    def _leave(self, starts, ends, code="HOURLY"):
        lt, _ = LeaveType.objects.get_or_create(code=code, defaults={"name": code, "is_hourly": True})
        req = LeaveRequest.objects.create(
            employee=self.emp, leave_type=lt, starts_at=starts, ends_at=ends,
            computed_minutes=int((ends - starts).total_seconds() // 60),
            overall_status="APPROVED",
        )
        return RequestSegment.objects.create(
            request_kind="LEAVE", leave_request=req, branch=self.branch,
            starts_at=starts, ends_at=ends,
            computed_minutes=req.computed_minutes, segment_status="APPROVED",
        )

    def test_presence_wins_no_double_count(self):
        d = self.work_date
        # مرخصی تأییدشده ۱۲ تا ۱۴ — ولی پرسنل در محل بوده و کار کرده
        self._leave(tehran(d, 12, 0), tehran(d, 14, 0))
        self.punch("CHECK_IN", tehran(d, 9, 0))
        self.punch("CHECK_OUT", tehran(d, 17, 0))
        s = recompute_month_summary(self.emp.id, self.branch.id, 1405, 7)
        # کارکرد کامل (کسر استراحت FIXED ولی مرخصی هم‌پوشان اعتبار نمی‌گیرد)
        self.assertEqual(s.accepted_work_minutes, 420)
        self.assertEqual(s.leave_minutes_by_type.get("HOURLY", 0), 0)  # اولویت حضور

    def test_leave_covers_absence(self):
        d = self.work_date
        self._leave(tehran(d, 8, 0), tehran(d, 18, 0))  # کل روز
        s = recompute_month_summary(self.emp.id, self.branch.id, 1405, 7)
        self.assertEqual(s.absence_minutes, 0)
        self.assertGreaterEqual(
            s.leave_minutes_by_type.get("HOURLY", 0), s.required_minutes
        )


class CloseMonthTests(RollupTestBase):
    def test_close_happy_path(self):
        d = self.work_date
        self.punch("CHECK_IN", tehran(d, 9, 0))
        self.punch("CHECK_OUT", tehran(d, 17, 0))
        closure = close_month(jy=1405, jm=7, closed_by=self.user)
        self.assertEqual(closure.state, "CLOSED")
        s = MonthlySummary.objects.get(employee=self.emp, branch=self.branch, period_year=1405, period_month=7)
        self.assertEqual(s.summary_state, "FINAL")
        self.assertEqual(s.closure_id, closure.id)
        self.assertIsNotNone(s.finalized_at)

    def test_close_blocked_by_open_session(self):
        self.punch("CHECK_IN", tehran(self.work_date, 9, 0))  # بازه باز
        with self.assertRaises(ValidationError):
            close_month(jy=1405, jm=7, closed_by=self.user)

    def test_close_blocked_by_pending_segment(self):
        lt, _ = LeaveType.objects.get_or_create(code="H", defaults={"name": "x"})
        req = LeaveRequest.objects.create(
            employee=self.emp, leave_type=lt,
            starts_at=tehran(self.work_date, 12, 0), ends_at=tehran(self.work_date, 14, 0),
            overall_status="PENDING",
        )
        RequestSegment.objects.create(
            request_kind="LEAVE", leave_request=req, branch=self.branch,
            starts_at=req.starts_at, ends_at=req.ends_at,
        )
        with self.assertRaises(ValidationError):
            close_month(jy=1405, jm=7, closed_by=self.user)

    def test_closed_period_protected_from_recompute(self):
        d = self.work_date
        self.punch("CHECK_IN", tehran(d, 9, 0))
        self.punch("CHECK_OUT", tehran(d, 17, 0))
        close_month(jy=1405, jm=7, closed_by=self.user)
        # تلاش برای بازنویسی دوره بسته‌شده بی‌اثر است
        s = recompute_month_summary(self.emp.id, self.branch.id, 1405, 7)
        self.assertEqual(s.summary_state, "FINAL")


class DailyApiTests(RollupTestBase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_daily_board_window(self):
        d = self.work_date
        self.punch("CHECK_IN", tehran(d, 9, 0))
        self.punch("CHECK_OUT", tehran(d, 17, 0))
        r = self.client.get(
            reverse("attendance-daily-list"),
            {"from": str(dt.date(2026, 10, 12)), "to": str(dt.date(2026, 10, 14))},
        )
        self.assertEqual(r.status_code, 200, r.data)
        rows = r.data["results"]
        self.assertTrue(any(row["shift_date"] == d and row["accepted_work_minutes"] == 420 for row in rows))
        row = next(row for row in rows if row["shift_date"] == d)
        self.assertEqual(row["required_minutes"], 420)

    def test_daily_window_validation(self):
        r = self.client.get(
            reverse("attendance-daily-list"),
            {"from": "2026-01-01", "to": "2026-12-30"},
        )
        self.assertEqual(r.status_code, 400)

    def test_today_card(self):
        self.punch("CHECK_IN", tehran(timezone.localdate(), 9, 0))
        r = self.client.get(reverse("attendance-daily-today"))
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(len(r.data["events"]), 1)
        # ورود بدون خروج → بازه باز در کارت امروز گزارش می‌شود (تردد ناقص)
        self.assertIsNotNone(r.data["open_session"])
        self.assertEqual(r.data["open_session"]["branch"], "B100")

    def test_me_view_has_server_time_and_branches(self):
        r = self.client.get(reverse("me"))
        self.assertEqual(r.status_code, 200)
        self.assertIn("server_time", r.data)
        codes = [b["code"] for b in r.data["branches"]]
        self.assertIn("B100", codes)
        self.assertTrue(r.data["branches"][0]["is_home"])

    def test_overtime_approve_api(self):
        d = self.work_date
        self.punch("CHECK_IN", tehran(d, 9, 0))
        self.punch("CHECK_OUT", tehran(d, 18, 0))
        recompute_month_summary(self.emp.id, self.branch.id, 1405, 7)
        proposal = OvertimeProposal.objects.get()
        # پرسنل اجازه تأیید ندارد
        r = self.client.post(
            reverse("attendance-overtime-approve"), {"id": proposal.id}, format="json"
        )
        self.assertEqual(r.status_code, 403)
        # مدیر شعبه تأیید می‌کند
        mgr_emp = Employee.objects.create(
            personnel_code="99999", first_name="مدیر", last_name="شعبه", home_branch=self.branch,
        )
        mgr = User.objects.create_user(username="mgr", password="S3cret!Pass", employee=mgr_emp)
        grant(mgr, "BRANCH_MANAGER", branch=self.branch)
        client2 = APIClient()
        client2.force_authenticate(mgr)
        r = client2.post(
            reverse("attendance-overtime-approve"),
            {"id": proposal.id, "approved_minutes": 45}, format="json",
        )
        self.assertEqual(r.status_code, 200, r.data)
        proposal.refresh_from_db()
        self.assertEqual(proposal.approved_minutes, 45)
        s = MonthlySummary.objects.get(employee=self.emp, period_year=1405, period_month=7)
        self.assertEqual(s.overtime_minutes, 45)
