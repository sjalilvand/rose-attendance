"""Daily calculation engine tests — docs/analysis/02-calculation-rules.md §6–§8.

Events are created ACCEPTED with fixed effective times (bypassing decide_event,
whose 7-day/skew behaviour is covered by tests.py), so pairing and day windows
are fully deterministic. Tehran has no DST; absolute planned windows are stable.
"""
from __future__ import annotations

import datetime as dt
import uuid

from django.test import TestCase
from django.utils import timezone

from apps.core.enums import (
    EventStatus,
    RestMode,
    RuleKind,
    RuleScope,
    RuleStatus,
    SegmentStatus,
)
from apps.orgs.models import Branch, Region
from apps.people.models import Employee
from apps.rules.models import RuleSet
from apps.scheduling.models import ScheduledShift, Shift

from .calculation import RuleResolver, compute_day
from .models import AttendanceEvent, AttendanceSession, OvertimeProposal
from .services import apply_event_to_pairing


def make_branch(**over):
    region, _ = Region.objects.get_or_create(code="R1", defaults={"name": "منطقه یک"})
    fields = dict(code="B100", name="شعبه تجریش", region=region,
                  geo_latitude=35.7997, geo_longitude=51.4344, geo_radius_m=150)
    fields.update(over)
    return Branch.objects.create(**fields)


def make_employee(branch, code="12345"):
    return Employee.objects.create(
        personnel_code=code, first_name="علی", last_name="رضایی", home_branch=branch,
    )


def make_rule(kind, payload, **over):
    fields = dict(
        rule_kind=kind, scope=RuleScope.GLOBAL, payload=payload,
        effective_from=dt.date(2024, 1, 1), status=RuleStatus.ACTIVE,
    )
    fields.update(over)
    return RuleSet.objects.create(**fields)


def day_shift(**over):
    fields = dict(
        code="D1", name="اداری", starts_at=dt.time(9, 0), ends_at=dt.time(17, 0),
        rest_minutes=60, rest_mode=RestMode.FIXED, grace_minutes=0,
    )
    fields.update(over)
    return Shift.objects.create(**fields)


def tehran(date_: dt.date, hour: int, minute: int = 0):
    return dt.datetime.combine(date_, dt.time(hour, minute)).replace(
        tzinfo=timezone.get_current_timezone()
    )


class CalculationTestBase(TestCase):
    def setUp(self):
        self.branch = make_branch()
        self.emp = make_employee(self.branch)
        self.shift = day_shift()
        self.work_date = dt.date(2026, 10, 12)  # دوشنبه، ۲۰ مهر ۱۴۰۵
        self.sched = ScheduledShift.objects.create(
            employee=self.emp, branch=self.branch, work_date=self.work_date,
            shift=self.shift,
        )

    def _punch(self, kind: str, when: dt.datetime):
        """Accepted event with a DETERMINISTIC effective time.

        Deliberately bypasses decide_event: staleness (7-day) and skew are
        covered by tests.py; here we need fixed effective times in the past.
        """
        event = AttendanceEvent.objects.create(
            event_uuid=uuid.uuid4(), employee=self.emp, branch=self.branch,
            event_type=kind, device_time=when, effective_time=when,
            channel="PWA", connection_mode="OFFLINE_SYNC",
            event_status=EventStatus.ACCEPTED,
        )
        apply_event_to_pairing(event)
        return event

    def _compute(self, work_date=None):
        from apps.reports.services import _approved_overtime_map

        d = work_date or self.work_date
        sessions = list(
            AttendanceSession.objects.filter(
                employee=self.emp, branch=self.branch, shift_date=d
            ).select_related("check_in_event", "check_out_event")
        )
        return compute_day(
            employee_id=self.emp.id, branch_id=self.branch.id,
            shift_date=d,
            sessions=sessions, scheduled_shift=self.sched,
            leave_spans=[], resolver=RuleResolver(self.branch),
            overtime_approved_by_session=_approved_overtime_map(
                self.emp.id, self.branch.id, d, d
            ),
        )


class DefaultsWithoutRulesTests(CalculationTestBase):
    """No RuleSet rows → neutral FLAG_ONLY behaviour, shift rest applies."""

    def test_plain_full_day(self):
        d = self.work_date
        self._punch("CHECK_IN", tehran(d, 9, 0))
        self._punch("CHECK_OUT", tehran(d, 17, 0))
        day = self._compute()
        # raw 480, FIXED rest 60 → 420 accepted; obligation 480-60=420
        self.assertEqual(day.valid_presence_minutes, 480)
        self.assertEqual(day.rest_minutes, 60)
        self.assertEqual(day.accepted_work_minutes, 420)
        self.assertEqual(day.required_minutes, 420)
        self.assertEqual(day.late_minutes, 0)
        self.assertEqual(day.overtime_proposed_minutes, 0)

    def test_late_flag_only_and_shift_grace(self):
        d = self.work_date
        self._punch("CHECK_IN", tehran(d, 9, 20))
        self._punch("CHECK_OUT", tehran(d, 17, 0))
        day = self._compute()
        self.assertEqual(day.late_minutes, 20)  # grace 0 from shift, FLAG_ONLY
        self.assertEqual(day.late_deduction_minutes, 0)
        self.assertIn("LATE_FLAGGED", day.flags)


class LateTierTests(CalculationTestBase):
    """Payload tiers of calculation-rules §6 — FLAG_ONLY / DEDUCT / ABSENCE_HALF."""

    def setUp(self):
        super().setUp()
        make_rule(RuleKind.LATE, {
            "grace_minutes": 10,
            "tiers": [
                {"up_to_minutes": 30, "deduct_mode": "FLAG_ONLY"},
                {"up_to_minutes": 120, "deduct_mode": "DEDUCT", "multiplier": 1.5},
                {"above_minutes": 120, "deduct_mode": "TREAT_AS_ABSENCE_HALF"},
            ],
            "monthly_forgive_count": 2,
            "rounding_minutes": 5,
        })

    def test_grace_and_rounding_tier1(self):
        d = self.work_date
        self._punch("CHECK_IN", tehran(d, 9, 14))  # 14 late − 10 grace = 4 → round up 5
        self._punch("CHECK_OUT", tehran(d, 17, 0))
        day = self._compute()
        self.assertEqual(day.late_minutes, 5)
        self.assertEqual(day.late_deduction_minutes, 0)
        self.assertIn("LATE_FLAGGED", day.flags)

    def test_tier2_deduct_multiplier(self):
        d = self.work_date
        self._punch("CHECK_IN", tehran(d, 10, 0))  # 60 late − 10 = 50 → round 50, DEDUCT×1.5
        self._punch("CHECK_OUT", tehran(d, 17, 0))
        day = self._compute()
        self.assertEqual(day.late_minutes, 50)
        self.assertEqual(day.late_deduction_minutes, 75)
        self.assertIn("LATE_DEDUCTED", day.flags)

    def test_tier3_absence_half(self):
        d = self.work_date
        self._punch("CHECK_IN", tehran(d, 13, 0))  # 240 late → ABSENCE_HALF
        self._punch("CHECK_OUT", tehran(d, 17, 0))
        day = self._compute()
        self.assertIn("LATE_AS_ABSENCE_HALF", day.flags)


class EarlyLeaveTests(CalculationTestBase):
    def test_early_leave_flagged(self):
        make_rule(RuleKind.EARLY_LEAVE, {
            "grace_minutes": 15,
            "tiers": [{"up_to_minutes": 60, "deduct_mode": "FLAG_ONLY"}],
            "rounding_minutes": 5,
        })
        d = self.work_date
        self._punch("CHECK_IN", tehran(d, 9, 0))
        self._punch("CHECK_OUT", tehran(d, 16, 0))  # 60 early − 15 grace = 45 → 45
        day = self._compute()
        self.assertEqual(day.early_leave_minutes, 45)
        self.assertIn("EARLY_FLAGGED", day.flags)


class RestModeTests(CalculationTestBase):
    def test_none_mode_keeps_full_presence(self):
        self.shift.rest_mode = RestMode.NONE
        self.shift.save()
        d = self.work_date
        self._punch("CHECK_IN", tehran(d, 9, 0))
        self._punch("CHECK_OUT", tehran(d, 17, 0))
        day = self._compute()
        self.assertEqual(day.rest_minutes, 0)
        self.assertEqual(day.accepted_work_minutes, 480)

    def test_deduct_if_short(self):
        make_rule(RuleKind.REST, {
            "mode": RestMode.DEDUCT_IF_SHORT,
            "default_minutes": 45,
            "min_presence_for_deduct": 300,
        })
        d = self.work_date
        # presence 240 < 300 → rest deducted
        self._punch("CHECK_IN", tehran(d, 9, 0))
        self._punch("CHECK_OUT", tehran(d, 13, 0))
        day = self._compute()
        self.assertEqual(day.rest_minutes, 45)
        self.assertEqual(day.accepted_work_minutes, 195)

    def test_deduct_if_short_not_applied_on_long_day(self):
        make_rule(RuleKind.REST, {
            "mode": RestMode.DEDUCT_IF_SHORT,
            "default_minutes": 45,
            "min_presence_for_deduct": 300,
        })
        d = self.work_date
        self._punch("CHECK_IN", tehran(d, 9, 0))
        self._punch("CHECK_OUT", tehran(d, 17, 0))  # 480 ≥ 300 → no deduction
        day = self._compute()
        self.assertEqual(day.rest_minutes, 0)

    def test_two_sessions_one_day(self):
        d = self.work_date
        self._punch("CHECK_IN", tehran(d, 9, 0))
        self._punch("CHECK_OUT", tehran(d, 12, 0))
        self._punch("CHECK_IN", tehran(d, 13, 0))
        self._punch("CHECK_OUT", tehran(d, 17, 0))
        day = self._compute()
        self.assertEqual(day.valid_presence_minutes, 420)  # 180 + 240
        self.assertEqual(day.rest_minutes, 60)  # FIXED capped at presence
        self.assertEqual(day.accepted_work_minutes, 360)


class OvertimeTests(CalculationTestBase):
    def test_overtime_proposed_not_counted_without_approval(self):
        d = self.work_date
        self._punch("CHECK_IN", tehran(d, 9, 0))
        self._punch("CHECK_OUT", tehran(d, 18, 10))  # 70 beyond planned_end
        day = self._compute()
        self.assertEqual(day.overtime_proposed_minutes, 70)
        self.assertEqual(day.overtime_approved_minutes, 0)  # awaiting manager

    def test_below_min_block_no_proposal(self):
        make_rule(RuleKind.OVERTIME, {
            "min_block_minutes": 30, "requires_approval": True,
            "max_daily_minutes": 240, "rounding_minutes": 15,
        })
        d = self.work_date
        self._punch("CHECK_IN", tehran(d, 9, 0))
        self._punch("CHECK_OUT", tehran(d, 17, 20))  # 20 < 30 → nothing
        day = self._compute()
        self.assertEqual(day.overtime_proposed_minutes, 0)

    def test_rounding_down_and_daily_cap(self):
        make_rule(RuleKind.OVERTIME, {
            "min_block_minutes": 30, "requires_approval": False,
            "max_daily_minutes": 60, "rounding_minutes": 15,
        })
        d = self.work_date
        self._punch("CHECK_IN", tehran(d, 9, 0))
        self._punch("CHECK_OUT", tehran(d, 18, 40))  # 100 → round 90 → cap 60
        day = self._compute()
        self.assertEqual(day.overtime_proposed_minutes, 60)
        self.assertEqual(day.overtime_approved_minutes, 60)  # auto-approved gate
        self.assertIn("OVERTIME_AUTO_APPROVED", day.flags)

    def test_approved_proposal_counts(self):
        from apps.reports.services import _sync_overtime_proposals

        d = self.work_date
        self._punch("CHECK_IN", tehran(d, 9, 0))
        self._punch("CHECK_OUT", tehran(d, 18, 0))  # 60 beyond
        day = self._compute()
        self.assertEqual(day.overtime_proposed_minutes, 60)
        _sync_overtime_proposals(self.emp, self.branch, [day])
        proposal = OvertimeProposal.objects.get()
        self.assertEqual(proposal.proposed_minutes, 60)
        proposal.status = SegmentStatus.APPROVED
        proposal.approved_minutes = 45  # manager trimmed the claim
        proposal.save()
        day2 = self._compute()
        self.assertEqual(day2.overtime_approved_minutes, 45)


class NightShiftTests(TestCase):
    def test_night_shift_overtime_after_midnight(self):
        branch = make_branch()
        emp = make_employee(branch)
        night = Shift.objects.create(
            code="N1", name="شیفت شب", starts_at=dt.time(22, 0),
            ends_at=dt.time(6, 0), crosses_midnight=True, rest_minutes=0,
        )
        d = dt.date(2026, 10, 12)  # دوشنبه
        sched = ScheduledShift.objects.create(
            employee=emp, branch=branch, work_date=d, shift=night,
        )

        def _punch(kind, when):
            event = AttendanceEvent.objects.create(
                event_uuid=uuid.uuid4(), employee=emp, branch=branch,
                event_type=kind, device_time=when, effective_time=when,
                channel="PWA", connection_mode="OFFLINE_SYNC",
                event_status=EventStatus.ACCEPTED,
            )
            apply_event_to_pairing(event)
            return event

        _punch("CHECK_IN", tehran(d, 21, 50))
        _punch("CHECK_OUT", tehran(d + dt.timedelta(days=1), 6, 40))  # 40 beyond 06:00
        sessions = list(
            AttendanceSession.objects.filter(employee=emp, branch=branch)
            .select_related("check_in_event", "check_out_event")
        )
        day = compute_day(
            employee_id=emp.id, branch_id=branch.id, shift_date=d,
            sessions=sessions, scheduled_shift=sched,
            leave_spans=[], resolver=RuleResolver(branch),
        )
        self.assertEqual(day.shift_date, d)  # anchored to shift start
        self.assertEqual(day.overtime_proposed_minutes, 40)
        self.assertEqual(day.late_minutes, 0)  # 21:50 before 22:00
        self.assertEqual(day.accepted_work_minutes, 530)  # 21:50→06:40 = 530


class HolidayTests(CalculationTestBase):
    def test_holiday_no_obligation(self):
        d = self.work_date
        self._punch("CHECK_IN", tehran(d, 9, 0))
        self._punch("CHECK_OUT", tehran(d, 17, 0))
        day = self._compute()
        day2 = compute_day(
            employee_id=day.employee_id, branch_id=day.branch_id,
            shift_date=d,
            sessions=AttendanceSession.objects.filter(
                employee=self.emp, branch=self.branch
            ).select_related("check_in_event", "check_out_event"),
            scheduled_shift=self.sched, leave_spans=[],
            resolver=RuleResolver(self.branch), is_holiday=True,
        )
        self.assertEqual(day2.required_minutes, 0)
        self.assertIn("HOLIDAY", day2.flags)
        self.assertEqual(day2.accepted_work_minutes, 420)  # work still counted
