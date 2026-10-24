"""GET /me/ — branch payload for the Android app (phase-2 app step 3).

The app's «تاریخچهٔ کارکرد» shows per-(day, branch) rows from
/attendance/daily/ whose `branch` field is the branch **id**. To render the
branch name for multi-branch staff, /me/ now exposes each branch's id next
to code/name (additive change — PWA ignores unknown keys).
"""
from __future__ import annotations

import datetime as dt

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.orgs.models import Branch, EmployeeBranchAssignment, Region
from apps.people.models import Employee, User


def make_branch(code: str, name: str) -> Branch:
    region = Region.objects.first() or Region.objects.create(name="تهران")
    return Branch.objects.create(
        code=code, name=name, region=region,
        geo_latitude=35.7997, geo_longitude=51.4344,
        geo_radius_m=150, city="تهران",
    )


def login_client(username: str) -> APIClient:
    client = APIClient()
    token = client.post(
        reverse("token-obtain-pair"),
        {"username": username, "password": "S3cret!Pass"},
        format="json",
    ).data["access"]
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


class MeBranchPayloadTests(TestCase):
    def test_me_exposes_branch_id(self):
        branch = make_branch("V1", "ونک")
        emp = Employee.objects.create(
            personnel_code="90001", first_name="سارا", last_name="محمدی",
            home_branch=branch,
        )
        User.objects.create_user(
            username="u90001", password="S3cret!Pass", employee=emp
        )

        res = login_client("u90001").get(reverse("me"))
        self.assertEqual(res.status_code, 200)
        branches = res.data["branches"]
        self.assertEqual(len(branches), 1)
        self.assertEqual(branches[0]["id"], branch.id)
        self.assertEqual(branches[0]["code"], "V1")
        self.assertEqual(branches[0]["name"], "ونک")
        self.assertTrue(branches[0]["is_home"])

    def test_me_lists_home_first_then_assignments(self):
        home = make_branch("H1", "شعبهٔ اصلی")
        extra = make_branch("A1", "شعبهٔ مجاز")
        emp = Employee.objects.create(
            personnel_code="90002", first_name="رضا", last_name="کریمی",
            home_branch=home,
        )
        User.objects.create_user(
            username="u90002", password="S3cret!Pass", employee=emp
        )
        EmployeeBranchAssignment.objects.create(
            employee=emp, branch=extra,
            valid_from=timezone.localdate() - dt.timedelta(days=1),
            is_allowed=True,
        )

        res = login_client("u90002").get(reverse("me"))
        self.assertEqual(res.status_code, 200)
        branches = res.data["branches"]
        self.assertEqual([b["id"] for b in branches], [home.id, extra.id])
        self.assertEqual([b["is_home"] for b in branches], [True, False])
