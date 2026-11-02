"""Stage 4: sign-in.

The gateway runs its own sign-in for Claude's connector and hands the "who are
you" step to the company's identity provider (Google Workspace or Microsoft
Entra ID; both speak OpenID Connect, so only the settings differ):

  1. Claude registers itself with the gateway and sends the person to the
     gateway's /authorize.
  2. The gateway sends them on to Google or Microsoft to log in.
  3. Google or Microsoft sends them back to /auth/callback with proof of who
     they are. The gateway checks the email is on the approved list.
  4. The gateway gives Claude a pass (an access token) that only works here.

The standard OAuth endpoints (/register, /authorize, /token, /revoke and the
discovery documents) come from the MCP library; this module supplies the
storage and the identity-provider hand-off behind them.

Passes are stored as hashes, so a copy of the database can't be used to sign
in. Every use of a pass re-checks the approved list, so removing someone cuts
them off at their next request.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit

import httpx
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    RefreshToken,
    RegistrationError,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

from gateway.guard import AuditLog, Policy

GOOGLE = "https://accounts.google.com"

LOGIN_TTL_S = 10 * 60          # time allowed at the Google/Microsoft login page
CODE_TTL_S = 5 * 60            # gateway's one-time code, swapped by Claude for a pass
ACCESS_TTL_S = 60 * 60         # a pass lasts an hour...
REFRESH_TTL_S = 14 * 24 * 3600  # ...and renews automatically for two weeks

# Where Claude may ask for people to be sent back to after signing in.
CLAUDE_CALLBACK = "https://claude.ai/api/mcp/auth_callback"
LOOPBACK_HOSTS = ("localhost", "127.0.0.1")  # Claude Code on someone's computer


class SignInError(Exception):
    """Sign-in failed; the message is shown to the person."""


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def redirect_allowed(uri: str) -> bool:
    if uri == CLAUDE_CALLBACK:
        return True
    parts = urlsplit(uri)
    return parts.scheme == "http" and parts.hostname in LOOPBACK_HOSTS and parts.path == "/callback"


# ── the company's identity provider (Google or Microsoft) ──────────


@dataclass(frozen=True)
class IdentitySettings:
    issuer: str = GOOGLE
    client_id: str = ""
    client_secret: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    @classmethod
    def from_env(cls) -> "IdentitySettings":
        return cls(
            issuer=os.environ.get("SIGNIN_ISSUER", "").strip().rstrip("/") or GOOGLE,
            client_id=os.environ.get("SIGNIN_CLIENT_ID", "").strip(),
            client_secret=os.environ.get("SIGNIN_CLIENT_SECRET", "").strip(),
        )


def _id_token_claims(id_token: str) -> dict:
    """The claims inside an ID token. Its signature isn't checked: the token
    came straight from the identity provider's token endpoint over HTTPS, in
    exchange for the gateway's client secret, which OpenID Connect Core
    (section 3.1.3.7) accepts in place of a signature check. Issuer, audience,
    expiry and nonce are still checked by the caller."""
    try:
        payload = id_token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError):
        raise SignInError("The sign-in service sent back an unreadable identity.") from None


class IdentityProvider:
    def __init__(self, settings: IdentitySettings, callback_url: str,
                 transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self.callback_url = callback_url
        self._http = httpx.AsyncClient(transport=transport, timeout=15)
        self._endpoints: dict | None = None

    async def _discover(self) -> dict:
        if self._endpoints is None:
            url = self.settings.issuer + "/.well-known/openid-configuration"
            try:
                response = await self._http.get(url)
                response.raise_for_status()
                self._endpoints = response.json()
            except (httpx.HTTPError, ValueError):
                raise SignInError("Couldn't reach the company sign-in service.") from None
        return self._endpoints

    async def login_url(self, state: str, nonce: str, verifier: str) -> str:
        if not self.settings.configured:
            raise SignInError("Sign-in isn't set up on the gateway yet.")
        endpoints = await self._discover()
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        return endpoints["authorization_endpoint"] + "?" + urlencode({
            "response_type": "code",
            "client_id": self.settings.client_id,
            "redirect_uri": self.callback_url,
            "scope": "openid email profile",
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "prompt": "select_account",
        })

    async def email_for(self, code: str, verifier: str, nonce: str) -> str:
        """Swap the code Google/Microsoft sent back for the person's verified email."""
        endpoints = await self._discover()
        try:
            response = await self._http.post(endpoints["token_endpoint"], data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.callback_url,
                "client_id": self.settings.client_id,
                "client_secret": self.settings.client_secret,
                "code_verifier": verifier,
            })
        except httpx.HTTPError:
            raise SignInError("Couldn't reach the company sign-in service.") from None
        if response.status_code != 200:
            raise SignInError("The company sign-in service didn't accept the login. Please try again.")
        claims = _id_token_claims(response.json().get("id_token", ""))

        issuers = {self.settings.issuer}
        if self.settings.issuer == GOOGLE:
            issuers.add("accounts.google.com")  # Google uses both forms
        audience = claims.get("aud")
        audiences = audience if isinstance(audience, list) else [audience]
        if claims.get("iss") not in issuers or self.settings.client_id not in audiences:
            raise SignInError("The identity came from the wrong sign-in service.")
        if float(claims.get("exp", 0)) < time.time() or claims.get("nonce") != nonce:
            raise SignInError("The sign-in expired or didn't match. Please try again.")
        if claims.get("email_verified") is False:
            raise SignInError("That account's email address isn't verified.")
        # Google sends `email`; Microsoft often sends `preferred_username` instead.
        email = (claims.get("email") or claims.get("preferred_username") or "").strip().lower()
        if "@" not in email:
            raise SignInError("The sign-in service didn't say which email address you used.")
        return email


# ── the gateway's own sign-in records ───────────────────────────────


class SignInStore:
    def __init__(self, path: str):
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock, self._db:
            self._db.executescript("""
                CREATE TABLE IF NOT EXISTS clients (client_id TEXT PRIMARY KEY, info TEXT NOT NULL,
                                                    created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS logins (state TEXT PRIMARY KEY, client_id TEXT NOT NULL,
                                                   params TEXT NOT NULL, nonce TEXT NOT NULL,
                                                   verifier TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS codes (hash TEXT PRIMARY KEY, data TEXT NOT NULL,
                                                  expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS tokens (hash TEXT PRIMARY KEY, kind TEXT NOT NULL,
                                                   family TEXT NOT NULL, data TEXT NOT NULL,
                                                   expires REAL NOT NULL);
            """)

    def run(self, sql: str, args: tuple = ()) -> list:
        with self._lock, self._db:
            return self._db.execute(sql, args).fetchall()

    def tidy(self) -> None:
        now = time.time()
        for table in ("logins", "codes", "tokens"):
            self.run(f"DELETE FROM {table} WHERE expires < ?", (now,))


class GatewaySignIn:
    """The provider the MCP library calls for each step of Claude's sign-in."""

    def __init__(self, store: SignInStore, idp: IdentityProvider, policy: Policy,
                 audit: AuditLog, resource_url: str):
        self.store = store
        self.idp = idp
        self.policy = policy
        self.audit = audit
        self.resource_url = resource_url

    # client registration (Claude registers itself; only its own callbacks are accepted)

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        rows = self.store.run("SELECT info FROM clients WHERE client_id = ?", (client_id,))
        return OAuthClientInformationFull.model_validate_json(rows[0][0]) if rows else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        uris = [str(u) for u in (client_info.redirect_uris or [])]
        if not uris or not all(redirect_allowed(u) for u in uris):
            raise RegistrationError(
                error="invalid_redirect_uri",
                error_description="This gateway only signs in Claude.",
            )
        self.store.run("INSERT OR REPLACE INTO clients VALUES (?, ?, ?)",
                       (client_info.client_id, client_info.model_dump_json(), time.time()))

    # sign-in: off to Google/Microsoft, and back

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        self.store.tidy()
        state, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(3))
        self.store.run("INSERT INTO logins VALUES (?, ?, ?, ?, ?, ?)",
                       (state, client.client_id, params.model_dump_json(), nonce, verifier,
                        time.time() + LOGIN_TTL_S))
        try:
            return await self.idp.login_url(state, nonce, verifier)
        except SignInError as err:
            raise AuthorizeError(error="temporarily_unavailable", error_description=str(err)) from None

    async def callback(self, request: Request) -> Response:
        """Where Google/Microsoft send the person back to."""
        state = request.query_params.get("state", "")
        rows = self.store.run("SELECT client_id, params, nonce, verifier, expires FROM logins "
                              "WHERE state = ?", (state,))
        self.store.run("DELETE FROM logins WHERE state = ?", (state,))
        if not rows or rows[0][4] < time.time():
            return _page("This sign-in link has expired. Go back to Claude and connect again.", 400)
        client_id, params_json, nonce, verifier, _ = rows[0]
        if "error" in request.query_params or "code" not in request.query_params:
            return _page("Sign-in was cancelled. Go back to Claude and connect again.", 400)
        try:
            email = await self.idp.email_for(request.query_params["code"], verifier, nonce)
        except SignInError as err:
            return _page(str(err), 400)

        if not self.policy.person_allowed(email):
            self.audit.record(person=email, tool="sign-in", project="", arguments={},
                              outcome="blocked", detail="not on the approved list")
            return _page(f"{email} isn't approved to use the Aconex gateway. "
                         "Ask IT to add you.", 403)

        params = AuthorizationParams.model_validate_json(params_json)
        code = secrets.token_urlsafe(32)
        record = AuthorizationCode(
            code=code,
            scopes=params.scopes or [],
            expires_at=time.time() + CODE_TTL_S,
            client_id=client_id,
            code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=params.resource or self.resource_url,
            subject=email,
        )
        self.store.run("INSERT INTO codes VALUES (?, ?, ?)",
                       (_hash(code), record.model_dump_json(), record.expires_at))
        self.audit.record(person=email, tool="sign-in", project="", arguments={}, outcome="ok")
        return RedirectResponse(construct_redirect_uri(str(params.redirect_uri), code=code,
                                                       state=params.state), status_code=302)

    # passes

    async def load_authorization_code(self, client: OAuthClientInformationFull,
                                      authorization_code: str) -> AuthorizationCode | None:
        rows = self.store.run("SELECT data, expires FROM codes WHERE hash = ?", (_hash(authorization_code),))
        if not rows or rows[0][1] < time.time():
            return None
        code = AuthorizationCode.model_validate_json(rows[0][0])
        return code if code.client_id == client.client_id else None

    async def exchange_authorization_code(self, client: OAuthClientInformationFull,
                                          authorization_code: AuthorizationCode) -> OAuthToken:
        self.store.run("DELETE FROM codes WHERE hash = ?", (_hash(authorization_code.code),))
        return self._issue(client.client_id, authorization_code.scopes, authorization_code.resource,
                           authorization_code.subject or "", family=secrets.token_urlsafe(16))

    async def load_refresh_token(self, client: OAuthClientInformationFull,
                                 refresh_token: str) -> RefreshToken | None:
        token = self._load("refresh", refresh_token)
        if token is None or token["client_id"] != client.client_id:
            return None
        return RefreshToken(token=refresh_token, client_id=token["client_id"], scopes=token["scopes"],
                            expires_at=int(token["expires"]), resource=token["resource"],
                            subject=token["subject"])

    async def exchange_refresh_token(self, client: OAuthClientInformationFull,
                                     refresh_token: RefreshToken, scopes: list[str]) -> OAuthToken:
        if not self.policy.person_allowed(refresh_token.subject or ""):
            raise TokenError(error="invalid_grant", error_description="No longer approved.")
        family = self._family(refresh_token.token)
        # Rotate: the used refresh token and its access token stop working.
        self.store.run("DELETE FROM tokens WHERE family = ?", (family,))
        return self._issue(client.client_id, scopes or refresh_token.scopes, refresh_token.resource,
                           refresh_token.subject or "", family=family)

    async def load_access_token(self, token: str) -> AccessToken | None:
        data = self._load("access", token)
        if data is None or not self.policy.person_allowed(data["subject"]):
            return None
        return AccessToken(token=token, client_id=data["client_id"], scopes=data["scopes"],
                           expires_at=int(data["expires"]), resource=data["resource"],
                           subject=data["subject"])

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        family = self._family(token.token)
        if family:
            self.store.run("DELETE FROM tokens WHERE family = ?", (family,))

    # internals

    def _issue(self, client_id: str, scopes: list[str], resource: str | None, subject: str,
               family: str) -> OAuthToken:
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        now = time.time()
        for kind, value, ttl in (("access", access, ACCESS_TTL_S), ("refresh", refresh, REFRESH_TTL_S)):
            data = {"client_id": client_id, "scopes": scopes, "resource": resource,
                    "subject": subject, "expires": now + ttl}
            self.store.run("INSERT INTO tokens VALUES (?, ?, ?, ?, ?)",
                           (_hash(value), kind, family, json.dumps(data), now + ttl))
        return OAuthToken(access_token=access, token_type="Bearer", expires_in=ACCESS_TTL_S,
                          refresh_token=refresh, scope=" ".join(scopes) or None)

    def _load(self, kind: str, value: str) -> dict | None:
        rows = self.store.run("SELECT data, expires FROM tokens WHERE hash = ? AND kind = ?",
                              (_hash(value), kind))
        if not rows or rows[0][1] < time.time():
            return None
        return json.loads(rows[0][0])

    def _family(self, value: str) -> str:
        rows = self.store.run("SELECT family FROM tokens WHERE hash = ?", (_hash(value),))
        return rows[0][0] if rows else ""


def _page(message: str, status: int) -> HTMLResponse:
    from html import escape

    return HTMLResponse(
        "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
        "<title>Aconex Gateway</title>"
        "<body style='font-family:system-ui;max-width:32rem;margin:4rem auto;padding:0 1rem'>"
        f"<h1 style='font-size:1.3rem'>Aconex Gateway</h1><p>{escape(message, quote=False)}</p></body>",
        status_code=status,
    )
