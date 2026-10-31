"""Rose Hub SSO (پروتکل BASIC) — tests for /api/v1/auth/rose-sso/.

Real HS256 tokens are minted with the configured client secret, so signature,
aud/iss/exp validation, one-time consumption, identity linking and
provisioning are all exercised without network.
"""
from __future__ import annotations

import jwt as pyjwt
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.people.models import Employee, SSOIdentity, SSOUsedToken, User

from .tests_me import make_branch

ROSE_SETTINGS = {
    "ROSE_HUB_CLIENT_ID": "rose-techno-8a4e1f",
    "ROSE_HUB_CLIENT_SECRET": "test-secret-rose-hub",
    "ROSE_HUB_ISSUER": "rose-hub",
}


def mint(payload_overrides: dict | None = None, secret: str = "test-secret-rose-hub") -> str:
    import uuid

    payload = {
        "email": "neda@example.com",
        "iss": "rose-hub",
        "aud": "rose-techno-8a4e1f",
        "jti": uuid.uuid4().hex,  # هر فراخوانی توکن یکتا؛ فقط فراخوانی‌های هم‌jti یکی‌اند
    }
    payload.update(payload_overrides or {})
    return pyjwt.encode(payload, secret, algorithm="HS256")


@override_settings(**ROSE_SETTINGS)
class RoseSsoTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_missing_token_rejected(self):
        res = self.client.get(reverse("rose-sso"))
        self.assertEqual(res.status_code, 400)

    def test_valid_token_logs_in_and_provisions(self):
        token = mint()
        res = self.client.get(f"{reverse('rose-sso')}?sso_token={token}")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["via"], "rose-hub")
        self.assertIn("access", res.data)
        self.assertIn("refresh", res.data)
        user = User.objects.get(username="neda")  # بخش قبل از @ — رفتار قبلی
        self.assertTrue(SSOIdentity.objects.filter(
            user=user, provider="rose-hub", subject="neda@example.com").exists())
        # نشست دستگاه و last_login ثبت شده باشد
        self.assertTrue(user.device_sessions.exists())
        self.assertIsNotNone(user.last_login)
        # توکن access واقعاً احراز هویت می‌کند
        me = APIClient()
        me.credentials(HTTP_AUTHORIZATION=f"Bearer {res.data['access']}")
        self.assertEqual(me.get(reverse("me")).status_code, 200)
        self.assertEqual(me.get(reverse("me")).data["auth_method"], "SSO")

    def test_token_is_one_time(self):
        token = mint()
        first = self.client.get(f"{reverse('rose-sso')}?sso_token={token}")
        self.assertEqual(first.status_code, 200)
        second = self.client.get(f"{reverse('rose-sso')}?sso_token={token}")
        self.assertEqual(second.status_code, 401)
        # حتی توکن نامعتبر هم مصرف (و در نتیجه بی‌اثر) می‌شود
        self.assertTrue(SSOUsedToken.objects.exists())

    def test_garbage_or_expired_token_rejected(self):
        res = self.client.get(f"{reverse('rose-sso')}?sso_token=not-a-jwt")
        self.assertEqual(res.status_code, 401)
        expired = mint({"exp": 1_000_000_000})
        res2 = self.client.get(f"{reverse('rose-sso')}?sso_token={expired}")
        self.assertEqual(res2.status_code, 401)
        wrong_secret = mint(secret="another-secret")
        res3 = self.client.get(f"{reverse('rose-sso')}?sso_token={wrong_secret}")
        self.assertEqual(res3.status_code, 401)

    def test_second_login_uses_stable_identity_even_if_username_taken(self):
        token = mint()
        first = self.client.get(f"{reverse('rose-sso')}?sso_token={token}")
        self.assertEqual(first.status_code, 200)
        # یک کاربر تازه با همان نام‌کاربری بخش-قبل-از-@ ساخته شود؛ ورود بعدی
        # باید به همان حساب نخست برود (هویت پایدار)، نه حساب جدید.
        User.objects.create_user(username="neda2", password="S3cret!Pass")
        second = self.client.get(f"{reverse('rose-sso')}?sso_token={mint()}")
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.data["username"], first.data["username"])
        self.assertEqual(User.objects.filter(username__startswith="neda").count(), 2)

    def test_links_existing_account_by_full_email_username(self):
        User.objects.create_user(username="sara@example.com", password="S3cret!Pass")
        res = self.client.get(f"{reverse('rose-sso')}?sso_token={mint({'email': 'sara@example.com'})}")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["username"], "sara@example.com")
        self.assertEqual(User.objects.count(), 1)

    def test_token_without_email_rejected(self):
        res = self.client.get(f"{reverse('rose-sso')}?sso_token={mint({'email': None})}")
        self.assertEqual(res.status_code, 400)

    def test_inactive_account_rejected(self):
        token = mint()
        self.client.get(f"{reverse('rose-sso')}?sso_token={token}")
        user = User.objects.get(username="neda")
        user.is_active = False
        user.save(update_fields=["is_active"])
        res = self.client.get(f"{reverse('rose-sso')}?sso_token={mint()}")
        self.assertEqual(res.status_code, 400)

    def test_post_contract(self):
        res = self.client.post(reverse("rose-sso"), {"token": mint()}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["via"], "rose-hub")

    def test_provisioned_account_cannot_password_login(self):
        self.client.get(f"{reverse('rose-sso')}?sso_token={mint()}")
        res = self.client.post(
            reverse("token-obtain-pair"),
            {"username": "neda", "password": "whatever"},
            format="json",
        )
        self.assertEqual(res.status_code, 401)

    def test_sso_user_without_employee_profile_is_handled(self):
        # v3.6: NO_EMPLOYEE_PROFILE guards — حساب SSO پرونده پرسنلی ندارد
        res = self.client.get(f"{reverse('rose-sso')}?sso_token={mint()}")
        access = res.data["access"]
        me = APIClient()
        me.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        data = me.get(reverse("me")).data
        self.assertIsNone(data["employee"])
        # ویرایش موبایل هم برای این حساب پاسخ تمیز می‌دهد (نه ۵۰۰)
        res2 = me.post(reverse("profile-update"), {"mobile": "09121234567"}, format="json")
        self.assertEqual(res2.status_code, 400)
        self.assertEqual(res2.data["code"], "NO_EMPLOYEE")
