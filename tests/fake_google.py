"""A fake Google sign-in service for tests. It answers OpenID Connect
discovery, publishes its signing key, and swaps a login code for a properly
signed ID token naming whichever email the test chose."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qs

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from gateway.signin import IdentityProvider, IdentitySettings

ISSUER = "https://accounts.google.com"
AUTHORIZE = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN = "https://oauth2.googleapis.com/token"
JWKS = "https://www.googleapis.com/oauth2/v3/certs"
CLIENT_ID = "gateway-client.apps.googleusercontent.com"

GOOGLE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
ATTACKER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def public_jwk(key, kid: str) -> dict:
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    return {**jwk, "kid": kid, "use": "sig", "alg": "RS256"}


class FakeGoogle:
    def __init__(self, email: str = "lachie@asmblr.com.au"):
        self.email = email
        self.nonce = ""            # copied by the test from the login URL
        self.claims_override: dict = {}
        self.signing_key = GOOGLE_KEY   # a test can swap in ATTACKER_KEY
        self.algorithm = "RS256"
        self.raw_id_token: str | None = None  # a test can send any token text
        self.token_requests: list[dict] = []

    def id_token(self) -> str:
        now = time.time()
        claims = {"iss": ISSUER, "aud": CLIENT_ID, "iat": int(now), "exp": int(now) + 300,
                  "nonce": self.nonce, "email": self.email, "email_verified": True,
                  "hd": self.email.rsplit("@", 1)[-1], **self.claims_override}
        claims = {k: v for k, v in claims.items() if v is not None}
        if self.algorithm == "none":
            return jwt.encode(claims, None, algorithm="none", headers={"kid": "google-1"})
        if self.algorithm == "HS256":  # "sign" with Google's PUBLIC key as a shared secret
            def part(data: dict) -> str:
                return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()
            body = f"{part({'alg': 'HS256', 'typ': 'JWT', 'kid': 'google-1'})}.{part(claims)}"
            secret = json.dumps(public_jwk(GOOGLE_KEY, "google-1")).encode()
            mac = hmac.new(secret, body.encode(), hashlib.sha256).digest()
            return body + "." + base64.urlsafe_b64encode(mac).rstrip(b"=").decode()
        return jwt.encode(claims, self.signing_key, algorithm="RS256", headers={"kid": "google-1"})

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/.well-known/openid-configuration":
            return httpx.Response(200, json={"issuer": ISSUER, "authorization_endpoint": AUTHORIZE,
                                             "token_endpoint": TOKEN, "jwks_uri": JWKS})
        if str(request.url) == JWKS:
            return httpx.Response(200, json={"keys": [public_jwk(GOOGLE_KEY, "google-1")]})
        if str(request.url) == TOKEN:
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            self.token_requests.append(form)
            if form.get("code") != "google-code":
                return httpx.Response(400, json={"error": "invalid_grant"})
            token = self.raw_id_token if self.raw_id_token is not None else self.id_token()
            return httpx.Response(200, json={"id_token": token, "access_token": "g"})
        return httpx.Response(404)

    def provider(self, callback_url: str, issuer: str = ISSUER) -> IdentityProvider:
        settings = IdentitySettings(issuer=issuer, client_id=CLIENT_ID, client_secret="google-secret")
        return IdentityProvider(settings, callback_url, transport=httpx.MockTransport(self.handler))
