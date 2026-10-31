"""SSO (OIDC) login flow + self-service profile endpoints.

The provider is stubbed at the HTTP boundary — `sso.exchange_code` and
`sso.fetch_userinfo` are replaced — so tests exercise the real flow
(state consumption, linking, provisioning, redirects) without network.
"""
from __future__ import annotations

import urllib.parse

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.people.models import Employee, SSOIdentity, SSOLoginState, User

from .tests_me import login_client, make_branch

SSO_CONF = {
    "SSO_ENABLED": True,
    "SSO_ISSUER": "https://sso.example.com/realms/rose",
    "SSO_CLIENT_ID": "rose-attendance",
    "SSO_CLIENT_SECRET": "shhh",
    "SSO_LABEL": "سامانهٔ سازمانی",
    "SSO_AUTO_PROVISION": True,
    "SSO_ADMIN_EMAILS": "boss@example.com",
    "SSO_EXTRA_REDIRECT_ORIGINS": "https://attendance.example.com",
}

DISCOVERY = {
    "authorization_endpoint": "https://sso.example.com/realms/rose/protocol/openid-connect/auth",
    "token_endpoint": "https://sso.example.com/realms/rose/protocol/openid-connect/token",
    "userinfo_endpoint": "https://sso.example.com/realms/rose/protocol/openid-connect/userinfo",
}


def stub_provider(claims_by_code: dict[str, dict]) -> None:
    """Replaces the two provider HTTP calls with in-memory claims."""
    import apps.people.sso as sso

    def exchange(code, redirect_uri):
        assert redirect_uri.endswith("/api/v1/auth/sso/callback/")
        if code not in claims_by_code:
            raise sso.SSOError("provider rejected the code")
        return f"provider-token-{code}"

    def fetch(token):
        code = token.removeprefix("provider-token-")
        return claims_by_code[code]

    sso.exchange_code, sso.fetch_userinfo = exchange, fetch


def prime_discovery() -> None:
    """Seeds the discovery cache so no network call happens in tests."""
    import apps.people.sso as sso

    sso.settings.SSO_DISCOVERY_CACHE = {
        "issuer": SSO_CONF["SSO_ISSUER"],
        "at": timezone.now(),
        "doc": DISCOVERY,
    }


def start_state(client, origin="https://attendance.example.com") -> str:
    res = client.get(f"{reverse('sso-login')}?redirect={urllib.parse.quote(origin)}")
    assert res.status_code == 302, res.status_code
    state = urllib.parse.parse_qs(urllib.parse.urlparse(res["Location"]).query)["state"][0]
    return state


class SsoStatusTests(TestCase):
    def test_disabled_by_default(self):
        res = APIClient().get(reverse("sso-status"))
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.data["enabled"])

    @override_settings(**SSO_CONF)
    def test_enabled_reports_label(self):
        res = APIClient().get(reverse("sso-status"))
        self.assertTrue(res.data["enabled"])
        self.assertEqual(res.data["label"], "سامانهٔ سازمانی")


@override_settings(**SSO_CONF)
class SsoLoginRedirectTests(TestCase):
    def setUp(self):
        prime_discovery()
        cache.clear()  # fresh 'auth' throttle bucket per test

    def test_login_redirects_to_provider_and_persists_state(self):
        res = APIClient().get(
            f"{reverse('sso-login')}?redirect=https%3A%2F%2Fattendance.example.com"
        )
        self.assertEqual(res.status_code, 302)
        url = urllib.parse.urlparse(res["Location"])
        self.assertEqual(url.netloc, "sso.example.com")
        qs = urllib.parse.parse_qs(url.query)
        self.assertEqual(qs["client_id"][0], "rose-attendance")
        self.assertEqual(qs["response_type"][0], "code")
        self.assertIn("openid", qs["scope"][0])
        self.assertTrue(SSOLoginState.objects.filter(state=qs["state"][0]).exists())

    def test_unknown_redirect_origin_rejected(self):
        res = APIClient().get(f"{reverse('sso-login')}?redirect=https%3A%2F%2Fevil.example.com")
        self.assertEqual(res.status_code, 400)

    def test_redirect_with_path_or_query_rejected(self):
        res = APIClient().get(
            f"{reverse('sso-login')}?redirect=https%3A%2F%2Fattendance.example.com%2Fx%3Fa%3D1"
        )
        self.assertEqual(res.status_code, 400)


@override_settings(**SSO_CONF)
class SsoCallbackTests(TestCase):
    def setUp(self):
        cache.clear()

    def _state(self, client):
        prime_discovery()
        return start_state(client)

    def test_unknown_state_rejected(self):
        res = APIClient().get(f"{reverse('sso-callback')}?state=bogus&code=c1")
        self.assertEqual(res.status_code, 400)

    def test_state_is_single_use(self):
        client = APIClient()
        state = self._state(client)
        stub_provider({"c1": {"sub": "subj-1", "email": "ali@example.com", "name": "علی رضایی"}})
        first = client.get(f"{reverse('sso-callback')}?state={state}&code=c1")
        self.assertEqual(first.status_code, 302)
        second = client.get(f"{reverse('sso-callback')}?state={state}&code=c1")
        self.assertEqual(second.status_code, 400)

    def test_provisions_new_employee_role_and_identity(self):
        client = APIClient()
        state = self._state(client)
        stub_provider({"c1": {"sub": "subj-1", "email": "ali@example.com"}})
        res = client.get(f"{reverse('sso-callback')}?state={state}&code=c1")
        self.assertEqual(res.status_code, 302)
        self.assertTrue(res["Location"].startswith("https://attendance.example.com/sso#"))
        fragment = urllib.parse.parse_qs(
            urllib.parse.urlparse(res["Location"]).fragment
        )
        self.assertIn("access", fragment)
        self.assertIn("refresh", fragment)

        user = User.objects.get(username="ali@example.com")
        self.assertFalse(user.has_usable_password())
        self.assertTrue(SSOIdentity.objects.filter(user=user, subject="subj-1").exists())
        roles = user.active_role_codes()
        self.assertIn("EMPLOYEE", roles)
        # The issued access token really authenticates against /me/.
        me = APIClient()
        me.credentials(HTTP_AUTHORIZATION=f"Bearer {fragment['access'][0]}")
        res_me = me.get(reverse("me"))
        self.assertEqual(res_me.status_code, 200)
        self.assertEqual(res_me.data["auth_method"], "SSO")

    def test_admin_email_becomes_superuser_without_employee_role(self):
        client = APIClient()
        state = self._state(client)
        stub_provider({"c1": {"sub": "subj-admin", "email": "boss@example.com"}})
        client.get(f"{reverse('sso-callback')}?state={state}&code=c1")
        user = User.objects.get(username="boss@example.com")
        self.assertTrue(user.is_superuser)
        self.assertFalse(user.role_assignments.exists())

    def test_links_existing_user_by_username_email(self):
        user = User.objects.create_user(username="sara@example.com", password="S3cret!Pass")
        client = APIClient()
        state = self._state(client)
        stub_provider({"c1": {"sub": "subj-2", "email": "sara@example.com"}})
        res = client.get(f"{reverse('sso-callback')}?state={state}&code=c1")
        self.assertEqual(res.status_code, 302)
        self.assertEqual(User.objects.count(), 1)
        user.refresh_from_db()
        self.assertTrue(SSOIdentity.objects.filter(user=user, subject="subj-2").exists())

    def test_second_login_reuses_linked_user(self):
        client = APIClient()
        for code in ("c1", "c2"):
            state = self._state(client)
            stub_provider({code: {"sub": "subj-9", "email": "nima@example.com"}})
            res = client.get(f"{reverse('sso-callback')}?state={state}&code={code}")
            self.assertEqual(res.status_code, 302)
        self.assertEqual(User.objects.filter(username="nima@example.com").count(), 1)

    def test_provider_error_is_surfaced(self):
        client = APIClient()
        state = self._state(client)
        res = client.get(f"{reverse('sso-callback')}?state={state}&error=access_denied")
        self.assertEqual(res.status_code, 302)
        self.assertIn("error=", urllib.parse.urlparse(res["Location"]).fragment)

    def test_disabled_sso_returns_404(self):
        with override_settings(SSO_ENABLED=False):
            res = APIClient().get(f"{reverse('sso-callback')}?state=x&code=y")
            self.assertEqual(res.status_code, 404)


class ProfileTests(TestCase):
    def setUp(self):
        cache.clear()
        self.branch = make_branch("V9", "ونک ۹")
        self.emp = Employee.objects.create(
            personnel_code="90100", first_name="مریم", last_name="احمدی",
            home_branch=self.branch, job_title="حسابدار", mobile="09121110000",
        )
        self.user = User.objects.create_user(
            username="u90100", password="S3cret!Pass", employee=self.emp
        )
        self.client = login_client("u90100")

    def test_me_includes_profile_fields(self):
        res = self.client.get(reverse("me"))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["employee"]["job_title"], "حسابدار")
        self.assertEqual(res.data["employee"]["mobile"], "09121110000")
        self.assertEqual(res.data["employee"]["home_branch_name"], "ونک ۹")
        self.assertEqual(res.data["auth_method"], "PASSWORD")

    def test_profile_mobile_update(self):
        res = self.client.post(reverse("profile-update"), {"mobile": "09351234567"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.emp.refresh_from_db()
        self.assertEqual(self.emp.mobile, "09351234567")

    def test_profile_mobile_invalid(self):
        res = self.client.post(reverse("profile-update"), {"mobile": "12345"}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_password_change_flow(self):
        res = self.client.post(
            reverse("password-change"),
            {"current_password": "S3cret!Pass", "new_password": "N3wStrong!Pass"},
            format="json",
        )
        self.assertEqual(res.status_code, 200)
        # Old password rejected, new one accepted by the token endpoint.
        # (simplejwt answers 401 AuthenticationFailed for bad credentials.)
        token = APIClient().post(
            reverse("token-obtain-pair"),
            {"username": "u90100", "password": "S3cret!Pass"},
            format="json",
        )
        self.assertEqual(token.status_code, 401)
        token2 = APIClient().post(
            reverse("token-obtain-pair"),
            {"username": "u90100", "password": "N3wStrong!Pass"},
            format="json",
        )
        self.assertEqual(token2.status_code, 200)

    def test_password_change_wrong_current(self):
        res = self.client.post(
            reverse("password-change"),
            {"current_password": "Wrong!Pass1", "new_password": "N3wStrong!Pass"},
            format="json",
        )
        self.assertEqual(res.status_code, 400)

    def test_password_change_weak_rejected(self):
        res = self.client.post(
            reverse("password-change"),
            {"current_password": "S3cret!Pass", "new_password": "short"},
            format="json",
        )
        self.assertEqual(res.status_code, 400)

    def test_password_change_requires_authentication(self):
        res = APIClient().post(
            reverse("password-change"),
            {"current_password": "x", "new_password": "y"},
            format="json",
        )
        self.assertEqual(res.status_code, 401)
