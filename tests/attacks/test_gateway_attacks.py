"""Independent attack review, 2026-11-02.

Each test here either DEMONSTRATES a finding (these pass, and their docstring
starts with "FINDING:") or confirms a defence that HELD (docstring starts with
"HELD:"). The companion report is docs/attacks/2026-11-02-gateway-review.md.

These go past tests/test_security.py (the already-tried attacks); they do not
repeat them. Nothing here sends mail, contacts Aconex/Oracle, or uses any key.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import sqlite3
from urllib.parse import parse_qs, urlsplit

import anyio
import httpx
import pytest
from mcp.client.client import Client
from starlette.requests import Request

from gateway.aconex.client import AconexClient, Refused, Settings, check_outgoing
from gateway.guard import AuditLog, Policy
from gateway.server import build_server
from gateway.tools import Gateway, PersonLimit
from gateway.tools.files import FileLinks
from tests.fake_aconex import FakeAconex
from tests.fake_google import FakeGoogle
from tests.test_stage4 import BASE, CLAUDE_CALLBACK, MCP, app, http, register, sign_in

API = "https://api.aconex.com/api"


# Sign-in tests need the gateway's own sign-in turned on (the project-wide
# conftest turns it off for the direct-tool tests).
@pytest.fixture
def signin_env(monkeypatch, tmp_path):
    monkeypatch.delenv("GATEWAY_NO_SIGNIN", raising=False)
    monkeypatch.setenv("PUBLIC_HOST", "testserver")
    monkeypatch.setenv("AUDIT_DB", str(tmp_path / "gateway.db"))


def _call_tools(policy: Policy, fake: FakeAconex, names_and_args: list[tuple]):
    """Call tools directly (sign-in off) and return {tool: CallToolResult}."""
    out: dict = {}

    async def run():
        async with Client(build_server(fake.client(), policy, AuditLog(":memory:"))) as c:
            for name, args in names_and_args:
                out[name] = await c.call_tool(name, args)
    anyio.run(run)
    return out


# ── Q1 / Q5. Sign-in: can an unapproved person get a pass? ──────────────────

def _authorize_to_code(client, google, client_id, *, verifier):
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    to_google = client.get("/authorize", params={
        "response_type": "code", "client_id": client_id, "redirect_uri": CLAUDE_CALLBACK,
        "code_challenge": challenge, "code_challenge_method": "S256", "state": "st", "resource": MCP})
    asked = {k: v[0] for k, v in parse_qs(urlsplit(to_google.headers["location"]).query).items()}
    google.nonce = asked["nonce"]
    back = client.get("/auth/callback", params={"code": "google-code", "state": asked["state"]})
    if back.status_code != 302:
        return None, back
    returned = {k: v[0] for k, v in parse_qs(urlsplit(back.headers["location"]).query).items()}
    return returned["code"], back


def test_pkce_is_required_and_a_stolen_code_needs_the_verifier(signin_env):
    """HELD: the MCP library refuses to swap an authorization code for a pass
    unless the PKCE code_verifier is presented, so a code intercepted on the
    way back to Claude is useless on its own."""
    google = FakeGoogle()
    with http(app(google)) as client:
        client_id = register(client).json()["client_id"]
        code, _ = _authorize_to_code(client, google, client_id, verifier=secrets.token_urlsafe(48))
        assert code
        no_verifier = client.post("/token", data={
            "grant_type": "authorization_code", "code": code, "client_id": client_id,
            "redirect_uri": CLAUDE_CALLBACK, "resource": MCP})
    assert no_verifier.status_code == 400
    assert "code_verifier" in no_verifier.text


def test_authorization_code_is_bound_to_the_client_that_asked_for_it(signin_env):
    """HELD: a code issued to one registered client can't be redeemed by a
    different client, even with that client's own valid PKCE verifier."""
    google = FakeGoogle()
    with http(app(google)) as client:
        victim = register(client).json()["client_id"]
        attacker = register(client).json()["client_id"]
        verifier = secrets.token_urlsafe(48)
        code, _ = _authorize_to_code(client, google, victim, verifier=verifier)
        assert code
        stolen = client.post("/token", data={
            "grant_type": "authorization_code", "code": code, "client_id": attacker,
            "redirect_uri": CLAUDE_CALLBACK, "code_verifier": verifier, "resource": MCP})
    assert stolen.status_code >= 400


def test_failed_signins_are_audited(signin_env):
    """WAS Finding 3 (now fixed): a sign-in that fails the identity checks
    (here, a long-expired identity) is written to the audit log as a blocked
    sign-in, so probing /auth/callback with bad identities leaves a trace.
    docs/security.md promise 7 says every sign-in is logged.

    Before the fix this attempt produced zero audit rows; it now records one.
    """
    google = FakeGoogle()
    google.claims_override = {"exp": 1_000_000_000}  # long-expired identity
    audit = AuditLog(":memory:")
    with http(app(google, audit=audit)) as client:
        client_id = register(client).json()["client_id"]
        _, back = _authorize_to_code(client, google, client_id, verifier=secrets.token_urlsafe(48))
    assert back.status_code == 400 and "expired" in back.text
    rows = audit.recent(10)
    assert rows and rows[0]["tool"] == "sign-in" and rows[0]["outcome"] == "blocked"
    assert rows[0]["person"] == ""  # no verified identity to attribute it to


# ── Q2. Can anything but an unsent draft be written to Aconex? ──────────────

def _attempt(method, path, params=None, content=b"x"):
    recorder = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "constructionandengineering.oraclecloud.com":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        recorder.append(f"{request.method} {request.url}")
        return httpx.Response(200, content=b"<SendMailResult sendStatus='Drafted'><NewMailId>1</NewMailId></SendMailResult>")

    client = AconexClient(Settings("id", "secret"), transport=httpx.MockTransport(handler))

    async def run():
        return await client._send(method, path, params, "application/xml", content=content)
    try:
        anyio.run(run)
        return "sent", recorder
    except Refused:
        return "refused", recorder


@pytest.mark.parametrize("method,path,params", [
    ("POST", "/projects/1001/mail", {"is_draft": "true", "": ""}),          # empty extra param
    ("POST", "/projects/1001/mail", {"is_draft": "true ", }),               # trailing space in value
    ("POST", "/projects/1001/mail", {"IS_DRAFT": "true"}),                  # upper-case key
    ("POST", "/projects/1001/mail/m1/recall", {"is_draft": "true"}),        # recall endpoint
    ("POST", "/projects/1001/mail/m1/markasread", {"is_draft": "true"}),    # side-effect endpoint
    ("POST", "/projects/1001/mail/m1/reply/extra", {"is_draft": "true"}),   # deeper path
    ("POST", "/PROJECTS/1001/mail", {"is_draft": "true"}),                  # upper-case path
    ("PUT", "/projects/1001/mail", {"is_draft": "true"}),                   # PUT a "draft"
    ("OPTIONS", "/projects/1001/mail", {"is_draft": "true"}),               # odd verb
    ("POST", "/projects/1001/register/search/../mail", {"is_draft": "true"}),  # traversal in path
])
def test_only_exact_unsent_draft_posts_get_through(method, path, params):
    """HELD: beyond the 16 cases in test_security.py, these too are refused
    before anything leaves the gateway."""
    outcome, seen = _attempt(method, path, params)
    assert outcome == "refused" and seen == []


def test_the_two_real_draft_posts_still_work():
    """HELD (sanity): the exactly-right draft POSTs are the only POSTs allowed
    through (so the test above isn't just refusing everything)."""
    assert _attempt("POST", "/projects/1001/mail", {"is_draft": "true"})[0] == "sent"
    assert _attempt("POST", "/projects/1001/mail/m1/reply", {"is_draft": "true"})[0] == "sent"


# ── Q3. Reaching data outside the approved projects / the fixed menu ────────

def test_global_tools_ignore_the_approved_project_list():
    """FINDING (Q3, medium): with NO projects approved, an approved, signed-in
    person can still read any company's details, look up any Aconex user, and
    search the whole Aconex directory across every company. These tools take no
    project_id, so the stage-3 project gate never runs on them. docs/security.md
    promise 6 ("Only approved projects") doesn't cover them, and the honest-
    limits section doesn't mention this wider reach.

    Suggested fix: decide this is intended and document it in the honest-limits
    section, or gate the Aconex-wide directory/company/user lookups behind a
    separate allowlist (e.g. ALLOW_GLOBAL_DIRECTORY).
    """
    fake = FakeAconex()
    no_projects = Policy(allowed_projects=frozenset())  # nothing approved at all
    results = _call_tools(no_projects, fake, [
        ("gateway_account", {}),
        ("get_company", {"organization_id": "88"}),
        ("get_person", {"user_id": "501"}),               # no project_id -> Aconex-wide /users/501
        ("search_aconex_directory", {"company": "Steelworks"}),
    ])
    # All four succeed despite zero approved projects:
    assert all(not r.is_error for r in results.values()), {k: r.content for k, r in results.items()}
    # And they really did reach Aconex-wide endpoints:
    reached = {c["path"] for c in fake.calls}
    assert "/organizations/88" in reached and "/users/501" in reached and "/directory" in reached


def test_project_scoped_tools_still_block_an_unapproved_project():
    """HELD (contrast): a tool that DOES take a project_id is correctly blocked
    when the project isn't approved."""
    fake = FakeAconex()
    results = _call_tools(Policy(allowed_projects=frozenset({"9999"})), fake, [
        ("search_register", {"project_id": "1001", "words": "slab"}),
    ])
    assert results["search_register"].is_error
    assert "isn't switched on" in results["search_register"].content[0].text
    # Nothing was sent to Aconex for the blocked project:
    assert not any(c["path"].startswith("/projects/1001") for c in fake.calls)


def test_lucene_injection_stays_inside_the_quoted_phrase():
    """HELD (Q3): a search term crafted to break out of its quoted phrase and
    add Lucene clauses is escaped, so it can't widen the query to other fields.
    (It can still match more rows within the SAME project, which Aconex scopes
    by the URL path - that is not a cross-project breach.)"""
    fake = FakeAconex()
    evil = 'x" OR docno:* OR title:"'    # tries to inject an always-true clause
    _call_tools(Policy(allowed_projects=frozenset({"1001"})), fake, [
        ("search_register", {"project_id": "1001", "number": evil}),
    ])
    sent = [c for c in fake.calls if c["path"] == "/projects/1001/register"]
    assert sent, fake.calls
    query = sent[0]["params"]["search_query"]
    # The bare (unescaped) injection must not appear; the quote is backslash-escaped.
    assert 'OR docno:*' in query  # present only as literal text inside the phrase
    assert '\\"' in query          # the attacker's closing quote was escaped
    assert 'docno:"x\\" OR docno:* OR title:\\""' == query


# ── Q4. Download links: guess, reuse, race, use after removal ───────────────

def _get_request(token: str) -> Request:
    scope = {
        "type": "http", "http_version": "1.1", "method": "GET",
        "path": f"/files/{token}", "raw_path": f"/files/{token}".encode(),
        "headers": [], "query_string": b"", "path_params": {"token": token},
        "client": ("test", 1), "server": ("test", 80), "scheme": "https",
    }

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(scope, receive)


def test_download_link_survives_only_one_of_two_simultaneous_downloads():
    """HELD (Q4): two downloads of the same link at the same moment -> exactly
    one 200, one 410. The single atomic UPDATE closes the race an earlier
    review found."""
    fake = FakeAconex()
    policy = Policy(allowed_projects=frozenset({"1001"}),
                    allowed_emails=frozenset({"lachie@asmblr.com.au"}))
    gw = Gateway(fake.client(), policy, AuditLog(":memory:"))
    links = FileLinks(gw, ":memory:")
    token = links.create("lachie@asmblr.com.au", "1001", "9001", "").rsplit("/", 1)[-1]

    async def run():
        return await anyio.gather(links.serve(_get_request(token)), links.serve(_get_request(token)))

    r1, r2 = anyio.run(run)
    assert {r1.status_code, r2.status_code} == {200, 410}


def test_download_link_rechecks_project_and_person_when_used():
    """HELD (Q4): a link minted while allowed stops working the moment the
    project is no longer approved (same for a removed person / off switch)."""
    fake = FakeAconex()
    policy_before = Policy(allowed_projects=frozenset({"1001"}),
                           allowed_emails=frozenset({"lachie@asmblr.com.au"}))
    gw = Gateway(fake.client(), policy_before, AuditLog(":memory:"))
    links = FileLinks(gw, ":memory:")
    token = links.create("lachie@asmblr.com.au", "1001", "9001", "").rsplit("/", 1)[-1]
    gw.policy = Policy(allowed_projects=frozenset())  # project un-approved after minting
    r = anyio.run(links.serve, _get_request(token))
    assert r.status_code == 403


def test_download_token_is_not_guessable():
    """HELD (Q4): link tokens are 256-bit URL-safe random (>=43 chars), so
    they can't be guessed or enumerated."""
    fake = FakeAconex()
    gw = Gateway(fake.client(), Policy(allowed_projects=frozenset({"1001"})), AuditLog(":memory:"))
    links = FileLinks(gw, ":memory:")
    token = links.create("p", "1001", "9001", "").rsplit("/", 1)[-1]
    assert len(token) >= 43


# ── Q5. Audit log integrity ─────────────────────────────────────────────────

def test_audit_arguments_cannot_forge_extra_log_lines():
    """HELD (Q5): newlines/JSON smuggled in a tool argument can't fabricate a
    second audit line - the record is json.dumps-escaped before it is logged."""
    audit = AuditLog(":memory:")
    audit.record(person="a@x.com", tool="search_register",
                 project="1001\n{\"audit\": {\"person\": \"admin@x.com\"",
                 arguments={"words": "line1\nline2\x00\x1b[31m"}, outcome="ok")
    row = audit.recent(1)[0]
    import json
    serialised = json.dumps({"audit": row})
    # One single log line: the smuggled newlines are escaped, not raw, so they
    # can't fabricate a second "audit" line in Fly's logs.
    assert "\n" not in serialised
    assert "line1" in serialised and "line2" in serialised
    assert '"person": "a@x.com"' in serialised  # the real person, not the smuggled one


# ── Q6. Cheap denial of service: client registrations ───────────────────────

def _register_as(client, ip: str):
    return client.post("/register", headers={"Fly-Client-IP": ip}, json={
        "redirect_uris": [CLAUDE_CALLBACK], "client_name": "x",
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"]})


def test_registration_is_limited_per_source_and_the_table_is_bounded(signin_env, monkeypatch):
    """WAS Finding 2 (now fixed): registration is limited PER SOURCE ADDRESS,
    not by one global bucket, so a flood from one address can't lock out a new
    user at another; and the clients table is capped (oldest evicted), so it
    can't grow without bound.

    Before the fix this test asserted the vulnerable behaviour (a single global
    30-per-10-min counter whose rows were never cleaned); it now guards the fix.
    """
    from gateway import signin as signin_mod
    monkeypatch.setattr(signin_mod, "MAX_CLIENTS", 5)  # tiny cap to show eviction
    google = FakeGoogle()
    with http(app(google)) as client:
        flood = [_register_as(client, "9.9.9.9").status_code for _ in range(31)]
        # One source is capped at 30, then refused with 429 (not a global lockout):
        assert flood[:30] == [201] * 30 and flood[30] == 429
        # A DIFFERENT source is NOT locked out by the first one's flood:
        assert _register_as(client, "8.8.8.8").status_code == 201

    # Despite ~31 successful registrations, the table stayed bounded at the cap:
    import os
    con = sqlite3.connect(os.environ["AUDIT_DB"])
    try:
        assert con.execute("SELECT COUNT(*) FROM clients").fetchone()[0] <= 5
    finally:
        con.close()


def test_per_person_tool_limit_is_in_memory_only():
    """FINDING (Q6, low): the 30-calls-per-minute-per-person limit lives in a
    process-local dict (PersonLimit), so it resets whenever the Fly machine
    restarts - and fly.toml sets min_machines_running = 0 with auto-stop, so the
    machine naps and resets the counter during quiet spells. It bounds a single
    runaway chat, not a determined caller across restarts.

    Suggested fix: note this limitation in docs/security.md, or persist the
    counter (the Aconex-side pacing in client.Pacer is the real backstop)."""
    a = PersonLimit(per_minute=3)
    assert [a.allow("p@x.com") for _ in range(4)] == [True, True, True, False]
    b = PersonLimit(per_minute=3)  # a "restart": fresh limiter, counter forgotten
    assert b.allow("p@x.com") is True
