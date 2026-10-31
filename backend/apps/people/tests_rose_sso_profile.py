"""فاز ۶۵ — انتقال مشخصات کامل کاربر از توکن رز هاب در ورود یکپارچه.

توکن رز هاب علاوه بر email/name/role/nationalId، ``mobile``، ``province``،
``provinceCode`` و ``clinic`` را هم حمل می‌کند؛ این آزمون‌ها رفتار سرتاسری
``GET /api/v1/auth/rose-sso/`` را روی جریان بازبینی‌شدهٔ SSO (توکن
یک‌بارمصرف + هویت پایدار) بررسی می‌کنند:

- ساخت حساب + ذخیرهٔ کامل مشخصات در پاسخ و دیتابیس؛
- ورود دوم با مشخصات تغییر‌یافته → بروزرسانی همان حساب؛
- مقدار خالی توکن → مقدار محلی پاک نمی‌شود.
"""
from __future__ import annotations

from unittest import mock

import jwt as pyjwt
from django.conf import settings
from django.test import TestCase
from rest_framework.test import APIClient

from apps.people.models import Employee, User

EMAIL = "1639818146@rose.ir"


def _hub_token(**claims) -> str:
    base = {
        "iss": settings.ROSE_HUB_ISSUER,
        "aud": settings.ROSE_HUB_CLIENT_ID,
        "sub": "hub-user-1",
        "email": EMAIL,
        "name": "پری ملکی گلندوز",
        "role": "THERAPIST",
        "nationalId": "1639818146",
        "mobile": "09147446047",
        "province": "اردبیل",
        "provinceCode": "009006",
        "clinic": "کلینیک رز اردبیل",
        "scope": "sso-launch",
    }
    base.update(claims)
    return pyjwt.encode(base, settings.ROSE_HUB_CLIENT_SECRET, algorithm="HS256")


class RoseSSOProfileTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def _sso(self, token: str):
        return self.client.get("/api/v1/auth/rose-sso/", {"sso_token": token})

    def test_creates_user_with_full_profile(self):
        r = self._sso(_hub_token())
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertEqual(body["via"], "rose-hub")
        self.assertEqual(body["profile"]["national_id"], "1639818146")
        self.assertEqual(body["profile"]["clinic"], "کلینیک رز اردبیل")

        user = User.objects.get(username="1639818146")
        self.assertEqual(user.full_name, "پری ملکی گلندوز")
        self.assertEqual(user.mobile, "09147446047")
        self.assertEqual(user.province, "اردبیل")
        self.assertEqual(user.province_code, "009006")
        self.assertEqual(user.clinic, "کلینیک رز اردبیل")

    def test_second_login_updates_same_account(self):
        self._sso(_hub_token())
        r = self._sso(_hub_token(clinic="کلینیک رز تهران", mobile="09121111111"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(User.objects.filter(username="1639818146").count(), 1)
        user = User.objects.get(username="1639818146")
        self.assertEqual(user.clinic, "کلینیک رز تهران")
        self.assertEqual(user.mobile, "09121111111")

    def test_empty_claim_does_not_wipe_local_value(self):
        self._sso(_hub_token())
        self._sso(_hub_token(clinic="", province=""))
        user = User.objects.get(username="1639818146")
        self.assertEqual(user.clinic, "کلینیک رز اردبیل")
        self.assertEqual(user.province, "اردبیل")

    def test_linked_employee_file_is_updated_and_me_returns_profile(self):
        """حسابی که به پروندهٔ پرسنلی پیوند است: نام/موبایل/کد ملی پرونده هم
        از توکن بروزرسانی می‌شود (نام نمایشی UI از employee می‌خواند) و
        GET /api/v1/me/ مشخصات کامل رز هاب را برمی‌گرداند."""
        from apps.orgs.models import Branch, Region
        from apps.people.models import SSOIdentity

        region = Region.objects.create(code="R-TST", name="منطقهٔ آزمون")
        branch = Branch.objects.create(code="B-TST", name="شعبهٔ آزمون", region=region)
        employee = Employee.objects.create(
            personnel_code="1639818146",
            first_name="رضا",
            last_name="سفید",
            mobile="09120000000",
            home_branch=branch,
        )
        user = User.objects.create_user(username="1639818146", password=None)
        user.employee = employee
        user.save(update_fields=["employee"])
        SSOIdentity.objects.create(
            provider=settings.ROSE_HUB_ISSUER, subject=EMAIL, user=user, email=EMAIL,
        )

        r = self._sso(_hub_token())
        self.assertEqual(r.status_code, 200, r.content)

        employee.refresh_from_db()
        self.assertEqual(employee.first_name, "پری")
        self.assertEqual(employee.last_name, "ملکی گلندوز")
        self.assertEqual(employee.full_name, "پری ملکی گلندوز")
        self.assertEqual(employee.mobile, "09147446047")
        self.assertEqual(employee.national_id, "1639818146")

        # کاربر پس از SSO در دیتابیس بروزرسانی شده؛ نسخهٔ تازه را می‌خوانیم
        user = User.objects.get(pk=user.pk)
        self.assertEqual(user.province, "اردبیل")
        self.client.force_authenticate(user=user)
        me = self.client.get("/api/v1/me/").json()
        self.assertEqual(me["full_name"], "پری ملکی گلندوز")
        self.assertEqual(me["national_id"], "1639818146")
        self.assertEqual(me["mobile"], "09147446047")
        self.assertEqual(me["province"], "اردبیل")
        self.assertEqual(me["province_code"], "009006")
        self.assertEqual(me["clinic"], "کلینیک رز اردبیل")
        self.assertEqual(me["employee"]["full_name"], "پری ملکی گلندوز")

    def test_employee_names_not_wiped_when_name_claim_empty(self):
        """نام خالی در توکن نباید نام پروندهٔ پرسنلی را پاک کند."""
        from apps.orgs.models import Branch, Region
        from apps.people.models import SSOIdentity

        region = Region.objects.create(code="R-TST2", name="منطقهٔ آزمون ۲")
        branch = Branch.objects.create(code="B-TST2", name="شعبهٔ آزمون ۲", region=region)
        employee = Employee.objects.create(
            personnel_code="1639818146",
            first_name="رضا",
            last_name="سفید",
            home_branch=branch,
        )
        user = User.objects.create_user(username="1639818146", password=None)
        user.employee = employee
        user.save(update_fields=["employee"])
        SSOIdentity.objects.create(
            provider=settings.ROSE_HUB_ISSUER, subject=EMAIL, user=user, email=EMAIL,
        )

        r = self._sso(_hub_token(name=""))
        self.assertEqual(r.status_code, 200, r.content)
        employee.refresh_from_db()
        self.assertEqual(employee.first_name, "رضا")
        self.assertEqual(employee.last_name, "سفید")

    def test_password_login_syncs_profile_from_rose_hub(self):
        """ورود محلی (گذرواژه) هم پروفایل را از رز هاب استعلام و همگام می‌کند.

        سناریوی گزارش‌شده: کاربر مستقیماً در سامانه با گذرواژه وارد می‌شود؛
        مشخصات رز هاب (که فقط در ورود SSO همگام می‌شد) باید اینجا هم اعمال شود.
        """
        User.objects.create_user(username="1282777076", password="test-pass-123")
        profile = {
            "email": "1282777076@rose.ir",
            "name": "نرگس عطاران",
            "role": "THERAPIST",
            "username": "1282777076",
            "nationalId": "1282777076",
            "mobile": "09131291153",
            "province": "اصفهان",
            "provinceCode": "009007",
            "clinic": "کلینیک رز اصفهان",
        }
        with mock.patch(
            "apps.people.rose_sso._fetch_rose_hub_profile_detailed",
            return_value=(profile, None),
        ):
            r = self.client.post(
                "/api/v1/auth/token/",
                {"username": "1282777076", "password": "test-pass-123"},
                format="json",
            )
        self.assertEqual(r.status_code, 200, r.content)

        user = User.objects.get(username="1282777076")
        self.assertEqual(user.full_name, "نرگس عطاران")
        self.assertEqual(user.mobile, "09131291153")
        self.assertEqual(user.province, "اصفهان")
        self.assertEqual(user.province_code, "009007")
        self.assertEqual(user.clinic, "کلینیک رز اصفهان")

        # /me هم پروفایل کامل را برمی‌گرداند
        access = r.json()["access"]
        me = self.client.get(
            "/api/v1/me/", HTTP_AUTHORIZATION=f"Bearer {access}"
        ).json()
        self.assertEqual(me["full_name"], "نرگس عطاران")
        self.assertEqual(me["national_id"], "1282777076")
        self.assertEqual(me["province"], "اصفهان")
        self.assertEqual(me["clinic"], "کلینیک رز اصفهان")

    def test_password_login_survives_rose_hub_outage(self):
        """قطع/در دسترس نبودن رز هاب نباید ورود محلی را خراب کند."""
        User.objects.create_user(username="1282777076", password="test-pass-123")
        with mock.patch(
            "apps.people.rose_sso._fetch_rose_hub_profile_detailed",
            return_value=(None, "unreachable"),
        ):
            r_ok = self.client.post(
                "/api/v1/auth/token/",
                {"username": "1282777076", "password": "test-pass-123"},
                format="json",
            )
        self.assertEqual(r_ok.status_code, 200, r_ok.content)

        with mock.patch(
            "apps.people.rose_sso._fetch_rose_hub_profile_detailed",
            side_effect=RuntimeError("boom"),
        ):
            r_err = self.client.post(
                "/api/v1/auth/token/",
                {"username": "1282777076", "password": "test-pass-123"},
                format="json",
            )
        self.assertEqual(r_err.status_code, 200, r_err.content)


HUB_PROFILE = {
    "email": "1282777076@rose.ir",
    "name": "نرگس عطاران",
    "role": "THERAPIST",
    "username": "1282777076",
    "nationalId": "1282777076",
    "mobile": "09131291153",
    "province": "اصفهان",
    "provinceCode": "009007",
    "clinic": "کلینیک رز اصفهان",
}


class ProfileSyncFromHubTests(TestCase):
    """POST /api/v1/auth/profile/sync-from-hub/ — استعلام دستی مشخصات از رز هاب.

    سناریوی گزارش‌شده: نشست‌های موجود (بدون خروج/ورود مجدد) باید بتوانند
    مشخصات رز هاب را یک‌جا و با پیام قابل‌نمایش به‌روز کنند.
    """

    def setUp(self):
        self.client = APIClient()

    def _login(self):
        user = User.objects.create_user(username="1282777076", password="test-pass-123")
        self.client.force_authenticate(user=user)
        return user

    def test_syncs_profile_and_returns_visible_result(self):
        user = self._login()
        with mock.patch(
            "apps.people.rose_sso._fetch_rose_hub_profile_detailed",
            return_value=(dict(HUB_PROFILE), None),
        ):
            r = self.client.post("/api/v1/auth/profile/sync-from-hub/")
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertTrue(body["synced"])
        self.assertTrue(body["detail"])
        self.assertEqual(body["profile"]["full_name"], "نرگس عطاران")
        self.assertEqual(body["profile"]["clinic"], "کلینیک رز اصفهان")

        user = User.objects.get(pk=user.pk)
        self.assertEqual(user.full_name, "نرگس عطاران")
        self.assertEqual(user.mobile, "09131291153")
        self.assertEqual(user.province, "اصفهان")
        self.assertEqual(user.province_code, "009007")
        self.assertEqual(user.clinic, "کلینیک رز اصفهان")

        # /me هم پس از همگام‌سازی دستی پروفایل کامل را می‌دهد
        me = self.client.get("/api/v1/me/").json()
        self.assertEqual(me["full_name"], "نرگس عطاران")
        self.assertEqual(me["clinic"], "کلینیک رز اصفهان")

    def test_reports_failure_without_touching_local_values(self):
        user = self._login()
        user.full_name = "مقدار محلی"
        user.save(update_fields=["full_name", "updated_at"])
        with mock.patch(
            "apps.people.rose_sso._fetch_rose_hub_profile_detailed",
            return_value=(None, "unreachable"),
        ):
            r = self.client.post("/api/v1/auth/profile/sync-from-hub/")
        self.assertEqual(r.status_code, 502, r.content)
        body = r.json()
        self.assertFalse(body["synced"])
        self.assertEqual(body["reason"], "unreachable")
        self.assertTrue(body["detail"])
        user = User.objects.get(pk=user.pk)
        self.assertEqual(user.full_name, "مقدار محلی")

    def test_endpoint_maps_failure_reasons_to_persian_messages(self):
        user = self._login()
        for reason, fragment in [
            ("http-401", "clientSecret"),
            ("not-found", "یافت نشد"),
            ("config", "ROSE_HUB_URL"),
        ]:
            with mock.patch(
                "apps.people.rose_sso._fetch_rose_hub_profile_detailed",
                return_value=(None, reason),
            ):
                r = self.client.post("/api/v1/auth/profile/sync-from-hub/")
            self.assertEqual(r.status_code, 502, r.content)
            body = r.json()
            self.assertFalse(body["synced"])
            self.assertEqual(body["reason"], reason)
            self.assertIn(fragment, body["detail"])


class MeSelfHealFromHubTests(TestCase):
    """خودترمیمی /me — نشست‌های قدیمی (قبل از استقرار همگام‌سازی) بدون
    خروج/ورود مجدد باید پروفایل رز هاب را بگیرند.
    """

    def setUp(self):
        self.client = APIClient()

    def test_me_fills_empty_profile_from_hub(self):
        user = User.objects.create_user(username="1282777076", password="test-pass-123")
        self.client.force_authenticate(user=user)
        with mock.patch(
            "apps.people.rose_sso._fetch_rose_hub_profile_detailed",
            return_value=(dict(HUB_PROFILE), None),
        ):
            me = self.client.get("/api/v1/me/").json()
        self.assertEqual(me["full_name"], "نرگس عطاران")
        self.assertEqual(me["mobile"], "09131291153")
        self.assertEqual(me["national_id"], "1282777076")
        self.assertEqual(me["province"], "اصفهان")
        self.assertEqual(me["clinic"], "کلینیک رز اصفهان")
        user = User.objects.get(username="1282777076")
        self.assertEqual(user.mobile, "09131291153")

    def test_me_survives_hub_outage(self):
        user = User.objects.create_user(username="1282777076", password="test-pass-123")
        self.client.force_authenticate(user=user)
        with mock.patch(
            "apps.people.rose_sso._fetch_rose_hub_profile_detailed",
            return_value=(None, "unreachable"),
        ):
            r = self.client.get("/api/v1/me/")
        self.assertEqual(r.status_code, 200, r.content)
        # نام به نام‌کاربری برمی‌گردد و پروفایل خالی می‌ماند — بدون خطا
        self.assertEqual(r.json()["full_name"], "1282777076")

    def test_me_skips_hub_when_profile_already_synced(self):
        user = User.objects.create_user(username="1282777076", password="test-pass-123")
        user.full_name = "قبلاً همگام شده"
        user.save(update_fields=["full_name", "updated_at"])
        self.client.force_authenticate(user=user)
        self.addCleanup(mock.patch.stopall)
        fetch = mock.patch(
            "apps.people.rose_sso._fetch_rose_hub_profile_detailed"
        ).start()
        me = self.client.get("/api/v1/me/").json()
        self.assertEqual(me["full_name"], "قبلاً همگام شده")
        fetch.assert_not_called()
