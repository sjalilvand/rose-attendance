"""SSO endpoints — browser-facing redirects (PWA login via OIDC provider).

GET /api/v1/auth/sso/status/    -> {enabled, label}     (public, gates the button)
GET /api/v1/auth/sso/login/     -> 302 to the provider  (?redirect=<PWA origin>)
GET /api/v1/auth/sso/callback/  -> 302 back to PWA      (#access=…&refresh=… / #error=…)
"""
from __future__ import annotations

import urllib.parse

from django.http import HttpResponse, HttpResponseRedirect
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from . import sso


def _error_page_html(message: str) -> str:
    return (
        '<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8">'
        '<title>خطای ورود یکپارچه</title>'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<style>body{font-family:Vazirmatn,Tahoma,sans-serif;background:#faf7f5;"
        "display:flex;align-items:center;justify-content:center;height:100vh;margin:0}"
        ".card{background:#fff;border:1px solid #e8dcd6;border-radius:12px;padding:24px 32px;"
        "max-width:420px;text-align:center;box-shadow:0 2px 12px rgba(0,0,0,.06)}"
        "h1{font-size:18px;color:#8c2f39;margin:0 0 8px}p{color:#5c4a44;margin:0}</style>"
        "</head><body><div class=\"card\"><h1>ورود با SSO ناموفق بود</h1>"
        f"<p>{message}</p></div></body></html>"
    )


class SSOStatusView(APIView):
    """Public: the login page shows the SSO button only when enabled."""

    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"enabled": sso.is_enabled(), "label": sso.provider_label()})


class SSOLoginView(APIView):
    """Starts the authorization-code flow: validates the PWA origin, stores a
    single-use state, redirects the browser to the provider."""

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"

    def get(self, request):
        if not sso.is_enabled():
            return Response(status=status.HTTP_404_NOT_FOUND)
        try:
            redirect_origin = sso.validate_redirect(
                str(request.query_params.get("redirect", "") or "")
            )
            authorize_url = sso.start_login(request, redirect_origin)
        except sso.SSOError as exc:
            return Response(
                {"detail": str(exc), "code": "SSO_ERROR"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return HttpResponseRedirect(authorize_url)


class SSOCallbackView(APIView):
    """Provider lands here with ?code&state; issues our JWTs and redirects the
    browser to the PWA with tokens in the URL fragment (#...)."""

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"

    def get(self, request):
        if not sso.is_enabled():
            return HttpResponse(_error_page_html("ورود یکپارچه روی سرور فعال نیست."), status=404)

        state_value = str(request.query_params.get("state", "") or "")
        code = str(request.query_params.get("code", "") or "")
        provider_error = str(request.query_params.get("error", "") or "")
        redirect_to = ""

        try:
            if not state_value:
                raise sso.SSOError("پارامترهای بازگشت از سامانهٔ سازمانی ناقص است.")
            # Consume the state first so the user is sent back to the PWA with
            # a readable error even when the provider refused the login
            # (providers return only ?error&state, without a code).
            redirect_to = sso.consume_state(state_value)
            if provider_error:
                raise sso.SSOError("سامانهٔ سازمانی اجازهٔ ورود نداد؛ دوباره تلاش کنید.")
            if not code:
                raise sso.SSOError("کد ورود از سامانهٔ سازمانی دریافت نشد.")
            access_token = sso.exchange_code(code, sso.callback_uri(request))
            claims = sso.fetch_userinfo(access_token)
            user, _created = sso.find_or_provision_user(claims)
            if not user.is_active:
                raise sso.SSOError("حساب شما غیرفعال است؛ با منابع انسانی تماس بگیرید.")
            access, refresh = sso.issue_session(request, user)
        except sso.SSOError as exc:
            if redirect_to:
                fragment = urllib.parse.urlencode({"error": str(exc)})
                return HttpResponseRedirect(f"{redirect_to}/sso#{fragment}")
            return HttpResponse(_error_page_html(str(exc)), status=400)

        fragment = urllib.parse.urlencode({"access": access, "refresh": refresh})
        return HttpResponseRedirect(f"{redirect_to}/sso#{fragment}")
