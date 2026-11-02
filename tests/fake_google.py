"""A fake Google sign-in service for tests. It answers OpenID Connect
discovery and swaps a login code for an ID token naming whichever email the
test chose."""

from __future__ import annotations

import base64
import json
import time
from urllib.parse import parse_qs

import httpx

from gateway.signin import IdentityProvider, IdentitySettings

ISSUER = "https://accounts.google.com"
AUTHORIZE = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN = "https://oauth2.googleapis.com/token"
CLIENT_ID = "gateway-client.apps.googleusercontent.com"


def _b64(data: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()


class FakeGoogle:
    def __init__(self, email: str = "lachie@asmblr.com.au"):
        self.email = email
        self.nonce = ""            # copied by the test from the login URL
        self.claims_override: dict = {}
        self.token_requests: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/.well-known/openid-configuration":
            return httpx.Response(200, json={"issuer": ISSUER, "authorization_endpoint": AUTHORIZE,
                                             "token_endpoint": TOKEN})
        if str(request.url) == TOKEN:
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            self.token_requests.append(form)
            if form.get("code") != "google-code":
                return httpx.Response(400, json={"error": "invalid_grant"})
            claims = {"iss": ISSUER, "aud": CLIENT_ID, "exp": time.time() + 300,
                      "nonce": self.nonce, "email": self.email, "email_verified": True,
                      **self.claims_override}
            id_token = f"{_b64({'alg': 'RS256'})}.{_b64(claims)}.signature"
            return httpx.Response(200, json={"id_token": id_token, "access_token": "g"})
        return httpx.Response(404)

    def provider(self, callback_url: str) -> IdentityProvider:
        settings = IdentitySettings(issuer=ISSUER, client_id=CLIENT_ID, client_secret="google-secret")
        return IdentityProvider(settings, callback_url, transport=httpx.MockTransport(self.handler))
