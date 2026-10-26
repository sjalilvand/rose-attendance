"""Messaging REST API tests — partners, conversations, thread, notifications."""
from __future__ import annotations

import datetime as dt
import uuid

from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.messaging.models import Conversation, Message, Notification
from apps.orgs.models import Branch, Region
from apps.people.models import Employee, Role, RoleAssignment, User


def _fixtures():
    region = Region.objects.create(code="RM", name="منطقه مرکزی")
    branch = Branch.objects.create(code="BM1", name="شعبه مرکزی", region=region)
    other = Branch.objects.create(code="BM2", name="شعبه دیگر", region=region)

    emp = Employee.objects.create(
        personnel_code="9001", first_name="علی", last_name="کریمی", home_branch=branch,
    )
    emp_user = User.objects.create_user(username="emp1", password="Emp!Pass123", employee=emp)

    coworker = Employee.objects.create(
        personnel_code="9002", first_name="مریم", last_name="صادقی", home_branch=branch,
    )
    User.objects.create_user(username="cow1", password="Cow!Pass123", employee=coworker)

    manager_emp = Employee.objects.create(
        personnel_code="9003", first_name="رضا", last_name="مدیری", home_branch=branch,
    )
    manager_user = User.objects.create_user(
        username="mgr1", password="Mgr!Pass123", employee=manager_emp,
    )
    today = timezone.localdate()
    RoleAssignment.objects.create(
        user=manager_user,
        role=Role.objects.get(code="BRANCH_MANAGER"),
        branch=branch,
        valid_from=today - dt.timedelta(days=1),
    )

    hr_emp = Employee.objects.create(
        personnel_code="9004", first_name="هما", last_name="منابعی", home_branch=other,
    )
    hr_user = User.objects.create_user(username="hr1", password="Hr!Pass123", employee=hr_emp)
    RoleAssignment.objects.create(
        user=hr_user,
        role=Role.objects.get(code="HR"),
        branch=None,
        valid_from=today - dt.timedelta(days=1),
    )

    return {
        "branch": branch,
        "emp": emp,
        "emp_user": emp_user,
        "coworker": coworker,
        "manager_emp": manager_emp,
        "manager_user": manager_user,
        "hr_emp": hr_emp,
        "hr_user": hr_user,
    }


def _auth(client, user: User) -> None:
    token = str(RefreshToken.for_user(user).access_token)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")


class PartnerRuleTests(APITestCase):
    """Role-based partner visibility (§12 v1 contract)."""

    def setUp(self):
        self.fx = _fixtures()

    def test_employee_sees_own_managers_and_hr_only(self):
        _auth(self.client, self.fx["emp_user"])
        res = self.client.get("/api/v1/messages/partners/")
        self.assertEqual(res.status_code, 200)
        ids = {row["id"] for row in res.data["results"]}
        self.assertIn(self.fx["manager_emp"].id, ids)
        self.assertIn(self.fx["hr_emp"].id, ids)
        self.assertNotIn(self.fx["coworker"].id, ids)  # همکار هم‌شعبه مجاز نیست

    def test_branch_manager_sees_staff_and_global_roles(self):
        _auth(self.client, self.fx["manager_user"])
        res = self.client.get("/api/v1/messages/partners/")
        self.assertEqual(res.status_code, 200)
        ids = {row["id"] for row in res.data["results"]}
        self.assertIn(self.fx["emp"].id, ids)
        self.assertIn(self.fx["hr_emp"].id, ids)

    def test_hr_sees_everyone(self):
        _auth(self.client, self.fx["hr_user"])
        res = self.client.get("/api/v1/messages/partners/")
        ids = {row["id"] for row in res.data["results"]}
        self.assertIn(self.fx["emp"].id, ids)
        self.assertIn(self.fx["manager_emp"].id, ids)


class ConversationFlowTests(APITestCase):
    def setUp(self):
        self.fx = _fixtures()
        _auth(self.client, self.fx["emp_user"])

    def _open(self, partner):
        res = self.client.post(
            "/api/v1/messages/conversations/", {"partner_id": partner.id}, format="json"
        )
        self.assertEqual(res.status_code, 201, res.data)
        return res.data["id"]

    def test_open_send_fetch_and_unread_cycle(self):
        conv = self._open(self.fx["manager_emp"])

        # ارسال از سمت کارمند
        res = self.client.post(
            f"/api/v1/messages/conversations/{conv}/send/",
            {"body": "سلام؛ برای مرخصی فردا هماهنگ بود؟", "client_uuid": str(uuid.uuid4())},
            format="json",
        )
        self.assertEqual(res.status_code, 201, res.data)

        # فهرست گفتگوها از سمت مدیر — یک نخوانده
        _auth(self.client, self.fx["manager_user"])
        res = self.client.get("/api/v1/messages/conversations/")
        self.assertEqual(res.status_code, 200)
        row = next(r for r in res.data["results"] if r["id"] == conv)
        self.assertEqual(row["unread_count"], 1)
        self.assertEqual(row["partner"]["personnel_code"], "9001")

        # بازکردن رشته → نخوانده صفر می‌شود
        res = self.client.get(f"/api/v1/messages/conversations/{conv}/messages/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.data["results"]), 1)
        self.assertFalse(res.data["results"][0]["mine"])
        res = self.client.get("/api/v1/messages/conversations/")
        row = next(r for r in res.data["results"] if r["id"] == conv)
        self.assertEqual(row["unread_count"], 0)

        # پاسخ مدیر → بج کارمند
        res = self.client.post(
            f"/api/v1/messages/conversations/{conv}/send/", {"body": "بله، ثبت شد."}, format="json"
        )
        self.assertEqual(res.status_code, 201)
        _auth(self.client, self.fx["emp_user"])
        res = self.client.get("/api/v1/messages/notifications/unread/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["messages"], 1)

    def test_client_uuid_is_idempotent(self):
        conv = self._open(self.fx["manager_emp"])
        payload = {"body": "پیام آفلاین", "client_uuid": str(uuid.uuid4())}
        first = self.client.post(
            f"/api/v1/messages/conversations/{conv}/send/", payload, format="json"
        )
        second = self.client.post(
            f"/api/v1/messages/conversations/{conv}/send/", payload, format="json"
        )
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.data["id"], second.data["id"])
        self.assertEqual(Message.objects.count(), 1)

    def test_direct_conversation_is_reused(self):
        first = self._open(self.fx["manager_emp"])
        second = self._open(self.fx["manager_emp"])
        self.assertEqual(first, second)
        self.assertEqual(Conversation.objects.count(), 1)

    def test_forbidden_partner_is_rejected(self):
        res = self.client.post(
            "/api/v1/messages/conversations/", {"partner_id": self.fx["coworker"].id}, format="json"
        )
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.data["code"], "FORBIDDEN_PARTNER")

    def test_thread_of_non_participant_is_404(self):
        conv = self._open(self.fx["manager_emp"])
        _auth(self.client, self.fx["hr_user"])
        res = self.client.get(f"/api/v1/messages/conversations/{conv}/messages/")
        self.assertEqual(res.status_code, 404)


class NotificationTests(APITestCase):
    def setUp(self):
        self.fx = _fixtures()
        _auth(self.client, self.fx["emp_user"])

    def test_list_read_all_and_badge(self):
        Notification.objects.create(
            recipient_id=self.fx["emp"].id, kind="REQUEST_DECISION", payload={"title": "تأیید شد"}
        )
        Notification.objects.create(
            recipient_id=self.fx["emp"].id, kind="OVERTIME_APPROVED", payload={"title": "اضافه‌کاری"}
        )
        res = self.client.get("/api/v1/messages/notifications/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["count"], 2)
        self.assertEqual(res.data["unread"], 2)

        res = self.client.post("/api/v1/messages/notifications/read-all/")
        self.assertEqual(res.data["marked"], 2)
        res = self.client.get("/api/v1/messages/notifications/")
        self.assertEqual(res.data["unread"], 0)

    def test_badge_shows_both_counters(self):
        Message.objects.create(
            conversation=Conversation.objects.create(kind="DIRECT"),
            sender_id=self.fx["manager_emp"].id,
            body="سلام",
        )
        # عضویت کارمند در گفتگو
        from apps.messaging.models import ConversationParticipant

        conv = Conversation.objects.first()
        ConversationParticipant.objects.create(conversation=conv, employee=self.fx["emp"])
        res = self.client.get("/api/v1/messages/notifications/unread/")
        self.assertEqual(res.data["messages"], 1)
        self.assertEqual(res.data["notifications"], 0)
