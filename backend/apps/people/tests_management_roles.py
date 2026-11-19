"""مدیریت نقش‌ها در صفحهٔ مدیریت — فهرست، تخصیص و پایان نقش."""
from __future__ import annotations

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.orgs.models import Branch, Region
from apps.people.models import Employee, Role, RoleAssignment, User


def make_admin() -> tuple[APIClient, User, Branch]:
    region, _ = Region.objects.get_or_create(code="R1", defaults={"name": "منطقهٔ یک"})
    branch = Branch.objects.create(code="B9", name="شعبهٔ ۹", region=region)
    emp = Employee.objects.create(
        personnel_code="ADM", first_name="مدیر", last_name="سامانه", home_branch=branch,
    )
    admin = User.objects.create_user(
        username="adm", password="Adm!Pass123", employee=emp, is_superuser=True,
    )
    client = APIClient()
    client.force_authenticate(user=admin)
    return client, admin, branch


class RoleManagementTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client_api, self.admin, self.branch = make_admin()

    def _target_user(self) -> User:
        emp = Employee.objects.create(
            personnel_code="T1", first_name="هدف", last_name="تست", home_branch=self.branch,
        )
        return User.objects.create_user(username="target", password="Tg!Pass123", employee=emp)

    def test_roles_list(self):
        res = self.client_api.get(reverse("mgmt-roles"))
        self.assertEqual(res.status_code, 200)
        codes = {r["code"] for r in res.json()["results"]}
        self.assertIn("BRANCH_MANAGER", codes)
        self.assertIn("HR", codes)

    def test_assign_and_list_role(self):
        target = self._target_user()
        res = self.client_api.post(
            reverse("mgmt-user-roles", args=[target.id]),
            {"role_code": "BRANCH_MANAGER", "branch_id": self.branch.id},
            format="json",
        )
        self.assertEqual(res.status_code, 201)
        self.assertTrue(target.has_role("BRANCH_MANAGER", branch_id=self.branch.id))

        listing = self.client_api.get(reverse("mgmt-user-roles", args=[target.id])).json()
        self.assertEqual(listing["count"], 1)
        self.assertEqual(listing["results"][0]["role_code"], "BRANCH_MANAGER")
        self.assertTrue(listing["results"][0]["is_active"])

    def test_revoke_past_assignment_ends_yesterday(self):
        target = self._target_user()
        role = Role.objects.get(code="AUDITOR")
        ra = RoleAssignment.objects.create(user=target, role=role, valid_from="2020-01-01")
        res = self.client_api.delete(reverse("mgmt-user-roles", args=[target.id]) + f"?assignment_id={ra.id}")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.json()["removed"])  # پایان‌یافته، نه حذف
        ra.refresh_from_db()
        self.assertIsNotNone(ra.valid_to)
        self.assertFalse(target.has_role("AUDITOR"))

    def test_revoke_same_day_assignment_deletes_row(self):
        target = self._target_user()
        res = self.client_api.post(
            reverse("mgmt-user-roles", args=[target.id]), {"role_code": "HR"}, format="json"
        )
        ra_id = res.json()["id"]
        res2 = self.client_api.delete(
            reverse("mgmt-user-roles", args=[target.id]) + f"?assignment_id={ra_id}"
        )
        self.assertEqual(res2.status_code, 200)
        self.assertTrue(res2.json()["removed"])
        self.assertEqual(target.role_assignments.count(), 0)

    def test_invalid_role_rejected(self):
        target = self._target_user()
        res = self.client_api.post(
            reverse("mgmt-user-roles", args=[target.id]), {"role_code": "NOPE"}, format="json"
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()["code"], "INVALID_ROLE")

    def test_plain_user_forbidden(self):
        target = self._target_user()
        client = APIClient()
        client.force_authenticate(user=target)
        res = client.get(reverse("mgmt-user-roles", args=[self.admin.id]))
        self.assertEqual(res.status_code, 403)
