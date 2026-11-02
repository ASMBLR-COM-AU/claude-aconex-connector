"""Attack tests. Each one tries a specific way to make the gateway do something
it mustn't, and checks it fails. Anything found in an attack review becomes a
test here, so it can never quietly come back.

The rule above all others: nothing can send mail."""

import json

import anyio
import httpx
import pytest
from mcp.client.client import Client

from gateway.aconex.client import AconexClient, Refused, Settings
from gateway.guard import AuditLog, Policy
from gateway.server import build_server
from gateway.tools import PersonLimit
from tests.fake_aconex import FakeAconex
from tests.fake_google import ATTACKER_KEY, FakeGoogle
from tests.test_stage4 import APPROVED, app, http, mcp, sign_in

API = "https://api.aconex.com/api"


# ── 1. Nothing can send mail: the outgoing check ────────────────────

class Recorder:
    """A fake Aconex that records anything that reaches it."""

    def __init__(self):
        self.seen: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "constructionandengineering.oraclecloud.com":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        self.seen.append(f"{request.method} {request.url}")
        return httpx.Response(200, content=b"<SendMailResult sendStatus='Drafted'>"
                                           b"<NewMailId>1</NewMailId></SendMailResult>")


def attempt(method: str, path: str, params=None):
    """Push a request straight through the gateway's Aconex connection,
    bypassing every tool, the way buggy or malicious new code might."""
    recorder = Recorder()
    client = AconexClient(Settings("id", "secret"), transport=httpx.MockTransport(recorder.handler))

    async def run():
        return await client._send(method, path, params, "application/xml", content=b"x")
    try:
        anyio.run(run)
        return "sent", recorder.seen
    except Refused:
        return "refused", recorder.seen


@pytest.mark.parametrize("method,path,params", [
    ("POST", "/projects/1001/mail", None),                                  # a real send
    ("POST", "/projects/1001/mail", {"is_draft": "false"}),
    ("POST", "/projects/1001/mail", {"is_draft": "TRUE"}),
    ("POST", "/projects/1001/mail", {"is_draft": ["true", "false"]}),
    ("POST", "/projects/1001/mail", {"is_draft": "true", "send": "true"}),
    ("POST", "/projects/1001/mail/m1/reply", None),                         # a real reply
    ("POST", "/projects/1001/mail/m1/forward", {"is_draft": "true"}),       # forward
    ("POST", "/projects/1001/mail/m1/send", {"is_draft": "true"}),
    ("PUT", "/projects/1001/mail/m1", {"is_draft": "true"}),                # edit a draft into sent
    ("POST", "/projects/1001/mail%2Fm1%2Freply", None),                     # encoded slashes
    ("POST", "/projects/1001/register", None),                              # register a document
    ("PUT", "/projects/1001/register/9001/metadata", None),
    ("DELETE", "/projects/1001/register/9001", None),
    ("POST", "/projects/1001/register/search", {"then": "write"}),
    ("PATCH", "/projects/1001/users/1", None),
    ("POST", "/projects/1001/workflows", None),
])
def test_writes_never_leave_the_gateway(method, path, params):
    outcome, seen = attempt(method, path, params)
    assert outcome == "refused" and seen == []


def test_unsent_draft_and_search_are_the_only_writes_allowed():
    for path in ("/projects/1001/mail", "/projects/1001/mail/m1/reply"):
        assert attempt("POST", path, {"is_draft": "true"})[0] == "sent"
    assert attempt("POST", "/projects/1001/register/search")[0] == "sent"
    assert attempt("GET", "/projects/1001/mail", {"mail_box": "Inbox"})[0] == "sent"


def test_requests_only_go_to_aconex():
    for url in ("https://evil.example/api/projects", "http://api.aconex.com/api/projects",
                "https://api.aconex.com.evil.example/api/projects", "https://api.aconex.com/other"):
        request = httpx.Request("GET", url)
        with pytest.raises(Refused):
            from gateway.aconex.client import check_outgoing
            check_outgoing(request, Settings("id", "secret"))


def test_no_tool_can_reach_a_send_even_with_crafted_arguments():
    """Every tool, called with hostile values in every text argument, never
    gets a write past the outgoing check (the fake Aconex fails the test if
    one does)."""
    fake = FakeAconex()
    hostile = "1001/mail?is_draft=false#"

    async def run():
        async with Client(build_server(fake.client(), Policy(allowed_projects=frozenset({"1001"})),
                                       AuditLog(":memory:"))) as c:
            for tool in (await c.list_tools()).tools:
                args = {name: hostile for name, spec in tool.input_schema.get("properties", {}).items()
                        if spec.get("type") == "string" or "anyOf" in spec}
                if "project_id" in args:
                    args["project_id"] = "1001"
                await c.call_tool(tool.name, args)
    anyio.run(run)
    assert not [c for c in fake.calls if c["method"] != "GET" and "/register/search" not in c["path"]]


# ── 2. One person can't use up the company's Aconex limit ───────────

def test_per_person_limit():
    limit = PersonLimit(per_minute=3)
    assert [limit.allow("a@x.com") for _ in range(4)] == [True, True, True, False]
    assert limit.allow("b@x.com")  # someone else is unaffected


def test_per_person_limit_blocks_the_tool_and_is_logged(monkeypatch):
    monkeypatch.setenv("PERSON_CALLS_PER_MINUTE", "2")
    audit = AuditLog(":memory:")

    async def run():
        async with Client(build_server(FakeAconex().client(), Policy(allowed_projects=frozenset({"1001"})),
                                       audit)) as c:
            return [await c.call_tool("register_fields", {"project_id": "1001"}) for _ in range(3)]
    results = anyio.run(run)
    assert [r.is_error for r in results] == [False, False, True]
    assert "Wait a minute" in results[2].content[0].text
    assert audit.recent(1)[0]["detail"] == "over the per-person limit"


# ── 3. Sign-in can't be forged ──────────────────────────────────────

@pytest.fixture
def signin(monkeypatch, tmp_path):
    monkeypatch.delenv("GATEWAY_NO_SIGNIN", raising=False)
    monkeypatch.setenv("PUBLIC_HOST", "testserver")
    monkeypatch.setenv("AUDIT_DB", str(tmp_path / "gateway.db"))


pytestmark_signin = pytest.mark.usefixtures("signin")


def refused(google: FakeGoogle) -> str:
    with http(app(google)) as client:
        _, response = sign_in(client, google)
    assert response.status_code in (400, 403), response.text
    return response.text


@pytestmark_signin
def test_forged_signature_is_refused():
    google = FakeGoogle()
    google.signing_key = ATTACKER_KEY
    assert "wasn't signed" in refused(google)


@pytestmark_signin
def test_unsigned_identity_is_refused():
    google = FakeGoogle()
    google.algorithm = "none"
    assert "wasn't signed" in refused(google) or "unreadable" in refused(google)


@pytestmark_signin
def test_key_confusion_trick_is_refused():
    google = FakeGoogle()
    google.algorithm = "HS256"
    refused(google)


@pytestmark_signin
def test_identity_tampered_after_signing_is_refused():
    google = FakeGoogle(email="someone@else.com")
    good = google.id_token
    google.raw_id_token = None

    def tampered():
        header, payload, signature = good().split(".")
        import base64
        claims = json.loads(base64.urlsafe_b64decode(payload + "=="))
        claims["email"] = "lachie@asmblr.com.au"
        claims["hd"] = "asmblr.com.au"
        forged = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
        return f"{header}.{forged}.{signature}"
    google.id_token = tampered
    assert "wasn't signed" in refused(google)


@pytestmark_signin
def test_identity_for_another_app_is_refused():
    google = FakeGoogle()
    google.claims_override = {"aud": "someone-elses-app"}
    assert "wrong sign-in service" in refused(google)


@pytestmark_signin
def test_expired_identity_is_refused():
    google = FakeGoogle()
    google.claims_override = {"exp": 1_000_000_000}
    assert "expired" in refused(google)


@pytestmark_signin
def test_personal_google_account_with_a_work_email_is_refused():
    google = FakeGoogle()
    google.claims_override = {"hd": None}  # not a Google Workspace account
    assert "isn't managed by asmblr.com.au" in refused(google)


@pytestmark_signin
def test_google_email_must_be_verified():
    google = FakeGoogle()
    google.claims_override = {"email_verified": None}
    assert "isn't verified" in refused(google)


@pytestmark_signin
def test_microsoft_shared_sign_in_address_is_refused():
    google = FakeGoogle()
    shared = "https://login.microsoftonline.com/common/v2.0"
    application = __import__("gateway.server", fromlist=["build_app"]).build_app(
        FakeAconex().client(), APPROVED, AuditLog(":memory:"),
        idp=google.provider("https://testserver/auth/callback", issuer=shared))
    with http(application) as client:
        _, response = sign_in_expecting_failure(client)
    from urllib.parse import unquote_plus
    assert "own tenant address" in unquote_plus(response)


def sign_in_expecting_failure(client):
    from tests.test_stage4 import register, CLAUDE_CALLBACK, MCP
    client_id = register(client).json()["client_id"]
    response = client.get("/authorize", params={
        "response_type": "code", "client_id": client_id, "redirect_uri": CLAUDE_CALLBACK,
        "code_challenge": "x" * 43, "code_challenge_method": "S256", "state": "s", "resource": MCP})
    return client_id, response.headers.get("location", "") + response.text


@pytestmark_signin
def test_a_proper_sign_in_still_works():
    google = FakeGoogle()
    with http(app(google)) as client:
        _, response = sign_in(client, google)
        assert response.status_code == 200, response.text
        token = response.json()["access_token"]
        assert mcp(client, token, "tools/list").status_code == 200


# ── 4. Found by the independent review, 2 Nov 2026 ──────────────────

# (Raw control characters like ESC aren't allowed in XML at all; they're
# tested in JSON and HTML entities below.)
HIDDEN = "\u202e\u2066\u200b\u200d\ufeff\u2028\u2029\U000e0041\U000e0042"


def test_hidden_characters_are_removed_from_aconex_xml():
    from gateway.aconex.client import parse_xml
    xml = (f'<Doc Title="Head{HIDDEN} Contractor"><Name>Sam{HIDDEN} Lee</Name>'
           f'<Body>line one\nline\ttwo{HIDDEN}</Body></Doc>').encode()
    root = parse_xml(xml)
    assert root.get("Title") == "Head Contractor"
    assert root.findtext("Name") == "Sam Lee"
    assert root.findtext("Body") == "line one\nline\ttwo"  # new lines and tabs kept


def test_hidden_characters_in_html_entities_are_removed_from_mail_bodies():
    from gateway.aconex.parse import html_to_text
    assert html_to_text("<p>Pay&#8238;fdp.exe &#917569;&#917570;now</p>") == "Payfdp.exe now"


def test_hidden_characters_are_removed_from_json_and_file_names():
    from gateway.aconex.client import file_name
    from gateway.aconex.parse import clean_value
    assert clean_value({f"k{HIDDEN}": [f"v{HIDDEN}\x1b[31m\x07", 1]}) == {"k": ["v[31m", 1]}
    assert file_name("attachment; filename*=UTF-8''report%E2%80%AEfdp.exe") == "reportfdp.exe"


def test_ordinary_text_in_other_languages_is_kept():
    from gateway.aconex.parse import clean_text
    for value in ("Café Ünïcödé", "日本語の図面", "Ελληνικά", "שלום"):
        assert clean_text(value) == value


def test_public_health_page_reveals_nothing():
    from starlette.testclient import TestClient
    from gateway.server import build_app
    with TestClient(build_app(FakeAconex().client())) as client:
        response = client.get("/health")
    assert response.json() == {"status": "ok"}
    assert response.headers["strict-transport-security"].startswith("max-age=31536000")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


@pytestmark_signin
def test_sign_in_registrations_are_limited():
    from tests.test_stage4 import register
    with http(app(FakeGoogle())) as client:
        codes = [register(client).status_code for _ in range(32)]
    assert codes[:30] == [201] * 30 and set(codes[30:]) == {400}


def test_no_hidden_characters_in_the_gateways_own_files():
    import pathlib
    import unicodedata
    root = pathlib.Path(__file__).resolve().parent.parent
    for path in root.rglob("*"):
        if path.suffix not in (".py", ".md", ".toml", ".yml", ".txt", ".ini") or ".git" in path.parts:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            hidden = [hex(ord(c)) for c in line if unicodedata.category(c) in ("Cf", "Zl", "Zp")]
            assert not hidden, f"{path.relative_to(root)}:{number} has hidden characters {hidden}"
