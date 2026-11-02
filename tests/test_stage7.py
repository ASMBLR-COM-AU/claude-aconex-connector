"""Stage 7 tests: project mail, across the whole project, read-only."""

import json
from urllib.parse import urlsplit

import anyio
import pytest
from mcp.client.client import Client
from starlette.testclient import TestClient

from gateway.guard import AuditLog, Policy
from gateway.server import build_app, build_server
from tests.fake_aconex import PDF, FakeAconex

APPROVED = Policy(allowed_projects=frozenset({"1001"}))


@pytest.fixture(autouse=True)
def shared_db(monkeypatch, tmp_path):
    monkeypatch.setenv("AUDIT_DB", str(tmp_path / "gateway.db"))
    monkeypatch.setenv("PUBLIC_HOST", "testserver")


def call(fake, name, args):
    async def run():
        async with Client(build_server(fake.client(), APPROVED, AuditLog(":memory:"))) as c:
            return await c.call_tool(name, args)
    result = anyio.run(run)
    if result.is_error:
        return True, result.content[0].text
    return False, result.structured_content or json.loads(result.content[0].text)


def queries(fake):
    return [(c["params"].get("mail_box"), c["params"].get("search_query")) for c in fake.calls
            if c["path"] == "/projects/1001/mail"]


# ── search ──────────────────────────────────────────────────────────

def test_all_combines_received_and_sent_newest_first_each_mail_once():
    fake = FakeAconex()
    _, data = call(fake, "search_mail", {"project_id": "1001"})
    numbers = [m["number"] for m in data["mails"]]
    assert numbers == ["asmblr-TRANSMIT-000008", "asmblr-TRANSMIT-000007",
                       "LSGP-TRANSMIT-000146", "LSGP-TRANSMIT-000143"]
    assert data["mails"][0]["box"] == "received and sent"
    assert data["total_matching"] == {"received": 3, "sent": 2}
    assert [b for b, _ in queries(fake)] == ["Inbox", "Sentbox"]


def test_received_only_searches_one_box():
    fake = FakeAconex()
    call(fake, "search_mail", {"project_id": "1001", "box": "received"})
    assert [b for b, _ in queries(fake)] == ["Inbox"]


def test_filters_build_the_live_query():
    fake = FakeAconex()
    call(fake, "search_mail", {
        "project_id": "1001", "box": "received", "words": "precast C124", "from_company": "LVL",
        "from_person": "Baysinger", "to_person": "Lachie Barnett", "mail_type": "transmittal",
        "status": "Outstanding", "since": "2026-03-01", "until": "2026-04-01"})
    query = queries(fake)[-1][1]
    assert query == ('precast AND C124 AND fromtradingname:"LVL" AND fromuserfullname:"Baysinger" '
                     'AND touserfullname:"Lachie Barnett" AND corrtypeid:"23" AND tostatusid:"2" '
                     'AND sentdate:[20260301 TO 20260401]')


def test_open_ended_dates_and_special_characters():
    fake = FakeAconex()
    call(fake, "search_mail", {"project_id": "1001", "box": "sent", "words": "RFI-012 (urgent)",
                               "since": "2026-05-01"})
    query = queries(fake)[-1][1]
    assert query.startswith("RFI\\-012 AND \\(urgent\\) AND sentdate:[20260501 TO ")


def test_unknown_mail_type_lists_the_real_ones():
    is_error, text = call(FakeAconex(), "search_mail", {"project_id": "1001", "mail_type": "RFI"})
    assert is_error and "transmittal" in text


def test_nothing_found_gives_tips():
    _, data = call(FakeAconex(), "search_mail", {"project_id": "1001", "words": "NOMATCH"})
    assert data["mails"] == [] and any("from_company" in t for t in data["tips"])


def test_unapproved_project_never_reaches_aconex():
    fake = FakeAconex()
    is_error, text = call(fake, "search_mail", {"project_id": "1002"})
    assert is_error and "isn't switched on" in text and fake.calls == []


# ── reading ─────────────────────────────────────────────────────────

def test_read_mail_by_number():
    fake = FakeAconex()
    _, mail = call(fake, "read_mail", {"project_id": "1001", "mail_number": "LSGP-TRANSMIT-000143"})
    assert mail["mail_id"] == "m1" and mail["subject"] == "Warrs Project Example"
    assert mail["from"] == "Michael Baysinger (LVL Structures Group Pty Ltd)"
    assert [p["name"] for p in mail["to"]] == ["Lachie Barnett (ASMBLR)"]
    assert [p["name"] for p in mail["cc"]] == ["Rev Radar (ASMBLR)"]
    assert mail["body"] == "Hi Lachie,\n\nPrecast drawings attached. Thanks"
    kinds = [(a["kind"], a["attachment_id"], a["document_id"]) for a in mail["attachments"]]
    assert kinds == [("register document", "a9", "9001"), ("file", "a1", "")]


def test_read_mail_needs_one_way_to_find_it():
    assert call(FakeAconex(), "read_mail", {"project_id": "1001"})[0]
    is_error, text = call(FakeAconex(), "read_mail", {"project_id": "1001", "mail_number": "NOPE-1"})
    assert is_error and "No mail numbered NOPE-1" in text


def test_thread_uses_the_mails_thread_id():
    fake = FakeAconex()
    _, data = call(fake, "mail_thread", {"project_id": "1001", "mail_id": "m1"})
    assert data["thread_id"] == "t1"
    assert [m["mail_no"] for m in data["mails"]] == ["LSGP-TRANSMIT-000143", "LSGP-TRANSMIT-000146"]


def test_mail_fields_and_saved_searches():
    _, fields = call(FakeAconex(), "mail_fields", {"project_id": "1001"})
    assert fields["mail_types"] == ["Transmittal"] and fields["statuses"] == ["Outstanding", "Closed-Out"]
    assert "From Organization Name" in fields["searchable_fields"]
    _, saved = call(FakeAconex(), "saved_mail_searches", {"project_id": "1001"})
    assert saved["saved_searches"][0]["name"] == "Approved"


# ── attachments ─────────────────────────────────────────────────────

def test_mail_attachment_comes_as_a_real_file():
    fake = FakeAconex()
    _, data = call(fake, "get_mail_attachment", {"project_id": "1001", "mail_id": "m1", "attachment_id": "a1"})
    path = urlsplit(data["download_url"]).path
    with TestClient(build_app(fake.client(), APPROVED, AuditLog(":memory:")), base_url="https://testserver") as http:
        response = http.get(path)
    assert response.status_code == 200 and response.content == PDF
    assert fake.calls[-1]["path"] == "/projects/1001/mail/m1/attachments/a1"


def test_marked_up_attachment_path():
    fake = FakeAconex()
    _, data = call(fake, "get_mail_attachment", {"project_id": "1001", "mail_id": "m1",
                                                 "attachment_id": "a1", "marked_up": True})
    with TestClient(build_app(fake.client(), APPROVED, AuditLog(":memory:")), base_url="https://testserver") as http:
        http.get(urlsplit(data["download_url"]).path)
    assert fake.calls[-1]["path"] == "/projects/1001/mail/m1/attachments/a1/markedup"


def test_bad_attachment_id_never_reaches_aconex():
    fake = FakeAconex()
    is_error, text = call(fake, "get_mail_attachment", {"project_id": "1001", "mail_id": "m1",
                                                        "attachment_id": "../../register/9001"})
    assert is_error and "valid Aconex attachment ID" in text
