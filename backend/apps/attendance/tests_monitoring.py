"""مانیتورینگ وب — KPI ها، جریان زنده، انحراف GPS، غایب و محدودهٔ دسترسی مدیر شعبه."""
from __future__ import annotations

import datetime as dt
import uuid as uuid_mod

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from django.utils import timezone

from apps.attendance.services import receive_punch
from apps.orgs.models import Branch, Region
from apps.people.models import Employee, Role, RoleAssignment, User


def make_world() -> dict:
    region, _ = Region.objects.get_or_create(code="R1", defaults={"name": "منطقهٔ یک"})
    region2, _ = Region.objects.get_or_create(code="R2", defaults={"name": "منطقهٔ دو"})
    geo = Branch.objects.create(
        code="GEO", name="کلینیک جیو", region=region,
        geo_latitude=35.7797, geo_longitude=51.3806, geo_radius_m=150,
    )
    other = Branch.objects.create(code="OTH", name="شعبهٔ دیگر", region=region2)
    hr_branch = Branch.objects.create(code="HB", name="ستاد", region=region)

    def emp_with_user(code: str, name: str, branch: Branch, username: str, role_code: str | None = None,
                      role_branch: Branch | None = None) -> User:
        e = Employee.objects.create(
            personnel_code=code, first_name=name, last_name="*", home_branch=branch,
        )
        u = User.objects.create_user(username=username, password="Xy12345678", employee=e)
        if role_code:
            RoleAssignment.objects.create(
                user=u, role=Role.objects.get(code=role_code),
                branch=role_branch, valid_from="2020-01-01",
            )
        return u

    admin = emp_with_user("A1", "مدیر سامانه", hr_branch, "admin", role_code="ADMIN")
    emp_geo = emp_with_user("E1", "پرسنل جیو", geo, "empgeo").employee
    emp_oth = emp_with_user("E2", "پرسنل دیگر", other, "empoth").employee
    mgr = emp_with_user("M1", "مدیر شعبهٔ جیو", geo, "mgr", role_code="BRANCH_MANAGER", role_branch=geo)
    plain = emp_with_user("P1", "ساده", geo, "plain").employee
    plain_user = User.objects.get(username="plain")
    return {
        "geo": geo, "other": other, "admin": admin, "emp_geo": emp_geo,
        "emp_oth": emp_oth, "mgr": mgr, "plain": plain, "plain_user": plain_user,
    }


def client_for(user: User) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def punch_geo(employee, branch, lat, lng, minutes_ago: int, kind="CHECK_IN"):
    now = timezone.now()
    event, _ = receive_punch(
        employee=employee, branch=branch, event_type=kind,
        event_uuid=uuid_mod.uuid4(),
        device_time=now - dt.timedelta(minutes=minutes_ago),
        connection_mode="ONLINE", channel="PWA",
        latitude=lat, longitude=lng, accuracy_m=10.0,
    )
    return event


class MonitoringDashboardTests(TestCase):
    def setUp(self):
        cache.clear()
        self.w = make_world()

    def test_plain_employee_forbidden(self):
        res = client_for(self.w["plain_user"]).get(reverse("monitoring-dashboard"))
        self.assertEqual(res.status_code, 403)

    def test_admin_sees_all_kpis(self):
        w = self.w
        in_event = punch_geo(w["emp_geo"], w["geo"], 35.7797, 51.3806, 30)  # در مرکز
        punch_geo(w["emp_oth"], w["geo"], 35.7900, 51.3900, 20)  # خارج از محدوده (~1km+)
        punch_geo(w["plain"], w["geo"], None, None, 10)  # بدون GPS

        res = client_for(w["admin"]).get(reverse("monitoring-dashboard"))
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["kpis"]["events_today"], 3)
        self.assertEqual(data["kpis"]["present_now"], 3)  # سه CHECK_IN باز
        self.assertEqual(data["kpis"]["out_of_range_today"], 1)
        self.assertEqual(data["kpis"]["no_gps_today"], 1)
        self.assertEqual(data["kpis"]["employees_active"], 5)
        self.assertEqual(data["absent_total"], 2)  # emp های بدون تردد: admin + mgr

        # انحراف با متر عددی
        dev = data["deviations_today"]
        self.assertEqual(len(dev), 1)
        self.assertGreater(dev[0]["location_distance_m"], 1000)

        # حاضران الان شامل پرسنل جیو است
        names = {p["personnel_code"] for p in data["present_now"]}
        self.assertIn("E1", names)

        # جریان زنده با نام شعبه
        self.assertEqual(len(data["live_events"]), 3)
        self.assertEqual(data["live_events"][0]["branch"], "GEO")

        # غایب‌ها
        absent_codes = {a["personnel_code"] for a in data["absent_today"]}
        self.assertNotIn("E1", absent_codes)
        self.assertIn("M1", absent_codes)

    def test_branch_manager_scoped_to_own_branch(self):
        w = self.w
        punch_geo(w["emp_geo"], w["geo"], 35.7797, 51.3806, 30)
        punch_geo(w["emp_oth"], w["other"], None, None, 20)
        res = client_for(w["mgr"]).get(reverse("monitoring-dashboard"))
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["branches_in_scope"], 1)
        self.assertEqual(data["kpis"]["events_today"], 1)
        self.assertEqual(data["kpis"]["employees_active"], 3)  # E1, M1, P1 در شعبهٔ GEO
        # فیلتر شعبهٔ دیگر → خالی
        res2 = client_for(w["mgr"]).get(reverse("monitoring-dashboard") + "?branch=OTH")
        self.assertEqual(res2.json()["kpis"]["events_today"], 0)

    def test_distance_recorded_on_event(self):
        w = self.w
        # ~۳۷ متر از مرکز — درون شعاع ۱۵۰ متری
        ev = punch_geo(w["emp_geo"], w["geo"], 35.7800, 51.3808, 5)
        self.assertIsNotNone(ev.location_distance_m)
        self.assertGreater(ev.location_distance_m, 0)
        self.assertEqual(ev.location_status, "IN_RANGE")

    def test_check_out_closes_session_and_monitoring_updates(self):
        w = self.w
        punch_geo(w["emp_geo"], w["geo"], 35.7797, 51.3806, 60, kind="CHECK_IN")
        punch_geo(w["emp_geo"], w["geo"], 35.7797, 51.3806, 10, kind="CHECK_OUT")
        res = client_for(w["admin"]).get(reverse("monitoring-dashboard"))
        self.assertEqual(res.json()["kpis"]["present_now"], 0)
        self.assertEqual(res.json()["kpis"]["with_events_today"], 1)
