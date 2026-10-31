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

import jwt as pyjwt
from django.conf import settings
from django.test import TestCase
from rest_framework.test import APIClient

from apps.people.models import User

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
