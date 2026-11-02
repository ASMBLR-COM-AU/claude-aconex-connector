"""Stage 4 tests: sign-in, run end to end the way Claude's connector does it,
against a fake Google."""

import base64
import hashlib
import json
import secrets
from urllib.parse import parse_qs, urlsplit

import pytest
from starlette.testclient import TestClient

from gateway.guard import AuditLog, Policy
from gateway.server import build_app
from gateway.signin import CLAUDE_CALLBACK
from tests.fake_aconex import FakeAconex
from tests.fake_google import AUTHORIZE, FakeGoogle

BASE = "https://testserver"
MCP = BASE + "/mcp"
APPROVED = Policy(allowed_projects=frozenset({"1001"}),
                  allowed_emails=frozenset({"lachie@asmblr.com.au"}))


@pytest.fixture(autouse=True)
def signin_on(monkeypatch, tmp_path):
    monkeypatch.delenv("GATEWAY_NO_SIGNIN", raising=False)
    monkeypatch.setenv("PUBLIC_HOST", "testserver")
    monkeypatch.setenv("AUDIT_DB", str(tmp_path / "gateway.db"))


def app(google: FakeGoogle, policy: Policy = APPROVED, audit: AuditLog | None = None):
    return build_app(FakeAconex().client(), policy, audit or AuditLog(":memory:"),
                     idp=google.provider(BASE + "/auth/callback"))


def http(application) -> TestClient:
    return TestClient(application, base_url=BASE, follow_redirects=False)


def register(client: TestClient, redirect_uri: str = CLAUDE_CALLBACK):
    return client.post("/register", json={
        "redirect_uris": [redirect_uri], "client_name": "Claude",
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"],
    })


def sign_in(client: TestClient, google: FakeGoogle):
    """Claude's whole flow: register, authorize (PKCE), log in at Google,
    come back, swap the code for a pass. Returns (client_id, final response)."""
    client_id = register(client).json()["client_id"]
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    to_google = client.get("/authorize", params={
        "response_type": "code", "client_id": client_id, "redirect_uri": CLAUDE_CALLBACK,
        "code_challenge": challenge, "code_challenge_method": "S256",
        "state": "claude-state", "resource": MCP,
    })
    assert to_google.status_code == 302, to_google.text
    login = urlsplit(to_google.headers["location"])
    assert f"{login.scheme}://{login.netloc}{login.path}" == AUTHORIZE
    asked = {k: v[0] for k, v in parse_qs(login.query).items()}
    assert asked["redirect_uri"] == BASE + "/auth/callback" and asked["code_challenge_method"] == "S256"
    google.nonce = asked["nonce"]

    back = client.get("/auth/callback", params={"code": "google-code", "state": asked["state"]})
    if back.status_code != 302:
        return client_id, back
    to_claude = urlsplit(back.headers["location"])
    assert f"{to_claude.scheme}://{to_claude.netloc}{to_claude.path}" == CLAUDE_CALLBACK
    returned = {k: v[0] for k, v in parse_qs(to_claude.query).items()}
    assert returned["state"] == "claude-state"
    return client_id, client.post("/token", data={
        "grant_type": "authorization_code", "code": returned["code"], "client_id": client_id,
        "redirect_uri": CLAUDE_CALLBACK, "code_verifier": verifier, "resource": MCP,
    })


def mcp(client: TestClient, token: str, method: str, params: dict | None = None):
    return client.post("/mcp", headers={
        "Authorization": f"Bearer {token}", "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": "2025-06-18",
    }, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})


# ── discovery: how Claude finds the sign-in ─────────────────────────

def test_without_a_pass_claude_is_told_where_to_sign_in():
    with http(app(FakeGoogle())) as client:
        response = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert response.status_code == 401
        assert "resource_metadata=" in response.headers["www-authenticate"]

        resource = client.get("/.well-known/oauth-protected-resource/mcp").json()
        assert resource["resource"] == MCP
        assert resource["authorization_servers"][0].rstrip("/") == BASE

        server = client.get("/.well-known/oauth-authorization-server").json()
        assert server["code_challenge_methods_supported"] == ["S256"]
        assert server["registration_endpoint"].endswith("/register")


def test_health_stays_public():
    with http(app(FakeGoogle())) as client:
        assert client.get("/health").json()["status"] == "ok"


# ── signing in ──────────────────────────────────────────────────────

def test_approved_person_signs_in_and_their_email_is_logged():
    google, audit = FakeGoogle(), AuditLog(":memory:")
    with http(app(google, audit=audit)) as client:
        _, response = sign_in(client, google)
        assert response.status_code == 200, response.text
        token = response.json()["access_token"]
        assert response.json()["expires_in"] == 3600 and response.json()["refresh_token"]

        assert mcp(client, token, "initialize", {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "test", "version": "0"}}).status_code == 200
        listed = mcp(client, token, "tools/call", {"name": "list_projects", "arguments": {}})
        assert listed.status_code == 200, listed.text

    rows = audit.recent(5)
    assert rows[0]["tool"] == "list_projects" and rows[0]["person"] == "lachie@asmblr.com.au"
    assert rows[1]["tool"] == "sign-in" and rows[1]["outcome"] == "ok"
    # The gateway proved its own identity to Google with PKCE.
    assert google.token_requests[0]["code_verifier"]


def test_someone_not_approved_is_refused_at_sign_in():
    google, audit = FakeGoogle(email="someone@else.example"), AuditLog(":memory:")
    with http(app(google, audit=audit)) as client:
        _, response = sign_in(client, google)
    assert response.status_code == 403 and "isn't approved" in response.text
    assert audit.recent(1)[0]["outcome"] == "blocked"


def test_whole_domain_can_be_approved():
    google = FakeGoogle(email="colleague@asmblr.com.au")
    policy = Policy(allowed_domains=frozenset({"asmblr.com.au"}))
    with http(app(google, policy)) as client:
        assert sign_in(client, google)[1].status_code == 200


def test_unverified_email_is_refused():
    google = FakeGoogle()
    google.claims_override = {"email_verified": False}
    with http(app(google)) as client:
        response = sign_in(client, google)[1]
    assert response.status_code == 400 and "isn't verified" in response.text


def test_identity_for_another_app_is_refused():
    google = FakeGoogle()
    google.claims_override = {"aud": "someone-elses-app"}
    with http(app(google)) as client:
        assert "wrong sign-in service" in sign_in(client, google)[1].text


def test_only_claude_can_register():
    with http(app(FakeGoogle())) as client:
        assert register(client, "https://evil.example/callback").status_code == 400
        assert register(client, "http://localhost:3118/callback").status_code == 201  # Claude Code


def test_a_stale_or_made_up_login_is_refused():
    with http(app(FakeGoogle())) as client:
        response = client.get("/auth/callback", params={"code": "google-code", "state": "made-up"})
    assert response.status_code == 400 and "expired" in response.text


def test_sign_in_not_set_up_is_explained(monkeypatch):
    monkeypatch.delenv("SIGNIN_CLIENT_ID", raising=False)
    application = build_app(FakeAconex().client(), APPROVED, AuditLog(":memory:"))
    with http(application) as client:
        client_id = register(client).json()["client_id"]
        response = client.get("/authorize", params={
            "response_type": "code", "client_id": client_id, "redirect_uri": CLAUDE_CALLBACK,
            "code_challenge": "x" * 43, "code_challenge_method": "S256", "state": "s"})
    assert "isn't set up" in parse_qs(urlsplit(response.headers["location"]).query)["error_description"][0]


# ── passes ──────────────────────────────────────────────────────────

def test_a_made_up_pass_is_refused():
    with http(app(FakeGoogle())) as client:
        assert mcp(client, "not-a-real-pass", "tools/list").status_code == 401


def test_renewing_a_pass_retires_the_old_one():
    google = FakeGoogle()
    with http(app(google)) as client:
        client_id, response = sign_in(client, google)
        first = response.json()
        renewed = client.post("/token", data={"grant_type": "refresh_token", "client_id": client_id,
                                              "refresh_token": first["refresh_token"]})
        assert renewed.status_code == 200, renewed.text
        second = renewed.json()
        assert mcp(client, first["access_token"], "tools/list").status_code == 401
        assert mcp(client, second["access_token"], "tools/list").status_code == 200
        reused = client.post("/token", data={"grant_type": "refresh_token", "client_id": client_id,
                                             "refresh_token": first["refresh_token"]})
        assert reused.status_code == 400 and reused.json()["error"] == "invalid_grant"


def test_removing_someone_cuts_them_off_after_the_setting_restarts_the_gateway():
    google = FakeGoogle()
    with http(app(google)) as client:
        client_id, response = sign_in(client, google)
        passes = response.json()
    nobody = Policy(allowed_projects=frozenset({"1001"}))
    with http(app(google, nobody)) as client:  # same database, new approved list
        assert mcp(client, passes["access_token"], "tools/list").status_code == 401
        renewed = client.post("/token", data={"grant_type": "refresh_token", "client_id": client_id,
                                              "refresh_token": passes["refresh_token"]})
        assert renewed.status_code == 400


def test_passes_are_stored_scrambled(tmp_path):
    google = FakeGoogle()
    with http(app(google)) as client:
        token = sign_in(client, google)[1].json()["access_token"]
    raw = (tmp_path / "gateway.db").read_bytes()
    assert token.encode() not in raw
    assert hashlib.sha256(token.encode()).hexdigest().encode() in raw
