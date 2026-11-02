"""Stage 3 tests: off switch, approved projects, audit log, request pacing."""

import asyncio
import json
import time

import anyio
import httpx
from mcp.client.client import Client
from starlette.testclient import TestClient

from gateway.aconex import AconexClient, AconexError, Settings
from gateway.guard import AuditLog, Policy
from gateway.server import build_app, build_server
from tests.fake_aconex import FakeAconex


def run_tool(fake, name, args=None, policy=None, audit=None):
    audit = audit or AuditLog(":memory:")

    async def run():
        async with Client(build_server(fake.client(), policy, audit)) as client:
            return await client.call_tool(name, args or {})

    return anyio.run(run), audit


def data(result) -> dict:
    return result.structured_content or json.loads(result.content[0].text)


# ── off switch ──────────────────────────────────────────────────────

def test_off_switch_stops_every_aconex_tool(monkeypatch):
    monkeypatch.setenv("GATEWAY_OFF", "1")
    fake = FakeAconex()
    for name, args in [("list_projects", {}),
                       ("search_register", {"project_id": "1001"}),
                       ("search_aconex_directory", {"company": "Acme"})]:
        result, audit = run_tool(fake, name, args)
        assert result.is_error and "switched off by IT" in result.content[0].text
        assert audit.recent(1)[0]["outcome"] == "blocked"
    assert fake.calls == [] and fake.logins == 0


def test_ping_and_health_still_answer_when_off(monkeypatch):
    monkeypatch.setenv("GATEWAY_OFF", "true")
    result, _ = run_tool(FakeAconex(), "ping")
    assert not result.is_error
    with TestClient(build_app(FakeAconex().client())) as http:
        assert http.get("/health").json()["switched_off"] is True


def test_off_switch_values():
    for value, off in [("1", True), ("yes", True), ("ON", True), ("", False), ("0", False), ("no", False)]:
        import os
        os.environ["GATEWAY_OFF"] = value
        assert Policy.from_env().switched_off is off, value
    del os.environ["GATEWAY_OFF"]


# ── approved projects ───────────────────────────────────────────────

def test_unapproved_project_never_reaches_aconex():
    fake = FakeAconex()
    policy = Policy(allowed_projects=frozenset({"1001"}))
    result, audit = run_tool(fake, "search_register", {"project_id": "1002"}, policy)
    assert result.is_error and "isn't switched on" in result.content[0].text
    assert fake.calls == []
    row = audit.recent(1)[0]
    assert (row["outcome"], row["project"], row["detail"]) == ("blocked", "1002", "project not approved")


def test_list_projects_only_shows_approved_ones():
    result, _ = run_tool(FakeAconex(), "list_projects", policy=Policy(frozenset({"1002"})))
    assert [p["project_id"] for p in data(result)["projects"]] == ["1002"]


def test_no_approved_projects_means_none(monkeypatch):
    monkeypatch.setenv("ALLOWED_PROJECTS", "")
    result, _ = run_tool(FakeAconex(), "list_projects")
    assert data(result)["projects"] == []


def test_approved_list_tolerates_spaces(monkeypatch):
    monkeypatch.setenv("ALLOWED_PROJECTS", " 1001 , 1002,,")
    assert Policy.from_env().allowed_projects == {"1001", "1002"}


# ── audit log ───────────────────────────────────────────────────────

def test_every_call_is_logged_with_its_outcome():
    audit = AuditLog(":memory:")
    fake = FakeAconex()
    run_tool(fake, "search_register", {"project_id": "1001", "words": "slab"}, audit=audit)
    run_tool(fake, "document_details", {"project_id": "1001", "document_id": "4040"}, audit=audit)
    newest, older = audit.recent(2)
    assert older["tool"] == "search_register" and older["outcome"] == "ok"
    assert '"words": "slab"' in older["arguments"] and older["project"] == "1001"
    assert newest["tool"] == "document_details" and newest["outcome"] == "error"
    assert "not found" in newest["detail"]
    assert newest["person"] == "not signed in (local test)"  # sign-in is off in these tests


def test_audit_log_survives_a_restart(tmp_path):
    path = str(tmp_path / "audit.db")
    run_tool(FakeAconex(), "list_projects", audit=AuditLog(path))
    assert AuditLog(path).recent(5)[0]["tool"] == "list_projects"


# ── pacing requests to Aconex ───────────────────────────────────────

def paced_client(handler, per_second=20.0, at_once=2, waits=(0, 0)):
    async def token_or(request):
        if request.url.host.endswith("oraclecloud.com"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        return await handler(request)

    settings = Settings("id", "secret", per_second=per_second, at_once=at_once, throttle_waits=waits)
    return AconexClient(settings, transport=httpx.MockTransport(token_or))


def test_requests_are_spaced_and_capped():
    live, most = 0, 0

    async def slow(request):
        nonlocal live, most
        live += 1
        most = max(most, live)
        await asyncio.sleep(0.05)
        live -= 1
        return httpx.Response(200, content=b"<ok/>")

    client = paced_client(slow, per_second=20.0, at_once=2)

    async def burst():
        started = time.monotonic()
        async with anyio.create_task_group() as tg:
            for _ in range(6):
                tg.start_soon(client.get_xml, "/projects")
        return time.monotonic() - started

    elapsed = anyio.run(burst)
    assert most <= 2           # never more than `at_once` in flight
    assert elapsed >= 0.25     # 6 starts at 20 a second: at least 5 gaps of 0.05 s


def test_busy_aconex_is_retried_then_succeeds():
    answers = [503, 503, 200]

    async def busy(request):
        return httpx.Response(answers.pop(0), content=b"<ok/>")

    root = anyio.run(paced_client(busy).get_xml, "/projects")
    assert root.tag == "ok" and answers == []


def test_busy_aconex_gives_up_with_a_plain_message():
    async def busy(request):
        return httpx.Response(503, text="MAX_FREQUENCY_THROTTLE_LIMIT_REACHED")

    try:
        anyio.run(paced_client(busy).get_xml, "/projects")
    except AconexError as err:
        assert "busy" in str(err)
    else:
        raise AssertionError("expected an error")
