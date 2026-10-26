"""Superuser bootstrap — admin accounts without a personnel file.

Regression for the production incident on deployment 711f63a:
createsuperuser crashed with NotNullViolation on users.employee_id, and even
with a nullable column the token endpoint and /me/ would have 500'd on
user.employee access. Admin accounts must be first-class citizens.
"""
from __future__ import annotations

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.people.models import User

ADMIN_PASSWORD = "S3cret!Pass"


class SuperuserWithoutEmployeeTests(TestCase):
    def setUp(self):
        call_command("createsuperuser", "--noinput", "--username", "admin")
        user = User.objects.get(username="admin")
        user.set_password(ADMIN_PASSWORD)
        user.save(update_fields=["password"])

    def test_created_without_employee(self):
        user = User.objects.get(username="admin")
        self.assertIsNone(user.employee_id)
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_active)

    def test_login_returns_admin_role_without_employee(self):
        client = APIClient()
        res = client.post(
            reverse("token-obtain-pair"),
            {"username": "admin", "password": ADMIN_PASSWORD},
            format="json",
        )
        self.assertEqual(res.status_code, 200)
        self.assertIsNone(res.data["employee_id"])
        self.assertIsNone(res.data["personnel_code"])
        self.assertEqual(res.data["full_name"], "admin")
        self.assertIn("ADMIN", res.data["roles"])

    def test_me_endpoint_handles_missing_employee(self):
        client = APIClient()
        token = client.post(
            reverse("token-obtain-pair"),
            {"username": "admin", "password": ADMIN_PASSWORD},
            format="json",
        ).data["access"]
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        res = client.get(reverse("me"))
        self.assertEqual(res.status_code, 200)
        self.assertIsNone(res.data["employee"])
        self.assertIn("ADMIN", res.data["roles"])
        self.assertEqual(res.data["branches"], [])

    def test_second_createsuperuser_run_fails_cleanly(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            call_command("createsuperuser", "--noinput", "--username", "admin")
