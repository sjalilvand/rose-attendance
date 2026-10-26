"""WebSocket notifications — auth middleware, live push, service hooks.

End-to-end consumer tests run against the real ASGI application with an
InMemory channel layer (development settings). TransactionTestCase is used so
the middleware's database_sync_to_async thread can see committed fixtures.
"""
from __future__ import annotations

import sys
import types

# channels.testing.__init__ unconditionally imports daphne (an optional extra
# that production does not use — gunicorn/uvicorn serves ASGI). We only need
# WebsocketCommunicator, so stub the daphne.testing import for this module.
try:
    import daphne  # noqa: F401
except ModuleNotFoundError:
    _daphne = types.ModuleType("daphne")
    _daphne_testing = types.ModuleType("daphne.testing")
    _daphne_testing.DaphneProcess = type("DaphneProcess", (), {})
    _daphne.testing = _daphne_testing
    sys.modules.setdefault("daphne", _daphne)
    sys.modules.setdefault("daphne.testing", _daphne_testing)

import datetime as dt

from asgiref.sync import sync_to_async
from channels.testing.websocket import WebsocketCommunicator
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken

from apps.messaging.models import Notification
from apps.messaging.services import notify_employee
from apps.orgs.models import Branch, Region
from apps.people.models import Employee, User

from config.asgi import application  # noqa: E402 — settings already configured


def _fixtures():
    region = Region.objects.create(code="RW", name="منطقه ویدیو")
    branch = Branch.objects.create(code="BW", name="شعبه ویدیو", region=region)
    emp = Employee.objects.create(
        personnel_code="8001", first_name="سارا", last_name="محمدی", home_branch=branch,
    )
    user = User.objects.create_user(username="wsuser", password="Ws!Pass123", employee=emp)
    return emp, user


def _access_token(user: User) -> str:
    return str(RefreshToken.for_user(user).access_token)


class NotifyServiceTests(TestCase):
    def test_notify_persists_notification(self):
        emp, _user = _fixtures()
        notify_employee(
            employee_id=emp.id, kind="REQUEST_DECISION", title="ت", payload={"a": 1},
        )
        row = Notification.objects.get(recipient_id=emp.id)
        self.assertEqual(row.kind, "REQUEST_DECISION")
        self.assertEqual(row.payload["a"], 1)
        self.assertEqual(row.payload["title"], "ت")

    def test_notify_without_user_account_still_persists(self):
        region = Region.objects.create(code="RN", name="ن")
        branch = Branch.objects.create(code="BN", name="ن", region=region)
        emp = Employee.objects.create(
            personnel_code="8002", first_name="بی", last_name="حساب", home_branch=branch,
        )
        notify_employee(employee_id=emp.id, kind="X", title="ی")
        self.assertTrue(Notification.objects.filter(recipient_id=emp.id, kind="X").exists())


class ConsumerLiveTests(TransactionTestCase):
    def setUp(self):
        self.emp, self.user = _fixtures()

    async def test_connect_ping_and_live_push(self):
        comm = WebsocketCommunicator(application, f"/ws/notifications/?token={_access_token(self.user)}")
        try:
            connected, _scope = await comm.connect()
            self.assertTrue(connected)

            await comm.send_json_to({"type": "ping"})
            pong = await comm.receive_json_from(timeout=3)
            self.assertEqual(pong["type"], "pong")

            await sync_to_async(notify_employee)(
                employee_id=self.emp.id,
                kind="REQUEST_DECISION",
                title="درخواست شما تأیید شد",
                payload={"segment_id": 1},
            )
            msg = await comm.receive_json_from(timeout=3)
            self.assertEqual(msg["type"], "notification")
            self.assertEqual(msg["kind"], "REQUEST_DECISION")
            self.assertEqual(msg["title"], "درخواست شما تأیید شد")
            self.assertEqual(msg["payload"]["segment_id"], 1)
        finally:
            await comm.disconnect()

    async def test_connect_rejected_without_valid_token(self):
        comm = WebsocketCommunicator(application, "/ws/notifications/")
        connected, _scope = await comm.connect()
        self.assertFalse(connected)

    async def test_connect_rejected_with_refresh_token(self):
        refresh = str(RefreshToken.for_user(self.user))  # token_type != access
        comm = WebsocketCommunicator(application, f"/ws/notifications/?token={refresh}")
        connected, _scope = await comm.connect()
        self.assertFalse(connected)
