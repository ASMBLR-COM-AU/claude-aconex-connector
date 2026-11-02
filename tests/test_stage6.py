"""Stage 6 tests: the real file to Claude on command, by a short-lived link."""

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


def call(fake, args, policy=APPROVED):
    async def run():
        async with Client(build_server(fake.client(), policy, AuditLog(":memory:"))) as c:
            return await c.call_tool("get_document_file", args)
    result = anyio.run(run)
    if result.is_error:
        return True, result.content[0].text
    return False, result.structured_content or json.loads(result.content[0].text)


def app(fake, policy=APPROVED, audit=None):
    return TestClient(build_app(fake.client(), policy, audit or AuditLog(":memory:")),
                      base_url="https://testserver")


def test_by_document_number_gets_the_current_revision():
    fake = FakeAconex()
    _, data = call(fake, {"project_id": "1001", "document_number": "s-1100"})
    assert (data["document_number"], data["revision"], data["file_name"]) == ("S-1100", "B", "S-1100_B.pdf")
    assert data["download_url"].startswith("https://testserver/files/")
    assert "give the person the file" in data["next_step"]
    search = fake.calls[-1]
    assert search["params"]["search_query"] == 'docno:"s-1100"' and "show_document_history" not in search["params"]


def test_by_document_number_and_older_revision():
    fake = FakeAconex()
    _, data = call(fake, {"project_id": "1001", "document_number": "S-1100", "revision": "a"})
    assert (data["revision"], urlsplit(data["download_url"]).path.startswith("/files/")) == ("A", True)
    assert fake.calls[-1]["params"]["show_document_history"] == "true"


def test_unknown_number_or_revision_is_explained():
    is_error, text = call(FakeAconex(), {"project_id": "1001", "document_number": "S-1100", "revision": "Z"})
    assert is_error and "No document S-1100 revision Z" in text


def test_needs_exactly_one_of_number_or_id():
    fake = FakeAconex()
    assert call(fake, {"project_id": "1001"})[0]
    assert call(fake, {"project_id": "1001", "document_number": "S-1100", "document_id": "9001"})[0]
    assert fake.calls == []


def test_unapproved_project_gets_no_link():
    fake = FakeAconex()
    is_error, text = call(fake, {"project_id": "1002", "document_id": "9001"})
    assert is_error and "isn't switched on" in text and fake.calls == []


def link_path(fake, **extra):
    _, data = call(fake, {"project_id": "1001", "document_id": "9001", **extra})
    return urlsplit(data["download_url"]).path


def test_link_downloads_the_real_pdf_with_its_name():
    fake = FakeAconex()
    path = link_path(fake)
    audit = AuditLog(":memory:")
    with app(fake, audit=audit) as http:
        response = http.get(path)
    assert response.status_code == 200 and response.content == PDF
    assert response.headers["content-type"] == "application/pdf"
    assert "S-1100%20Rev%20B.pdf" in response.headers["content-disposition"]
    assert audit.recent(1)[0]["tool"] == "file downloaded" and audit.recent(1)[0]["outcome"] == "ok"


def test_choosing_another_file_of_the_document():
    fake = FakeAconex()
    path = link_path(fake, file_name="S-1100.dwg")
    with app(fake) as http:
        http.get(path)
    assert fake.calls[-1]["params"] == {"fileName": "S-1100.dwg"}


def test_link_works_once_then_stops():
    fake = FakeAconex()
    path = link_path(fake)
    with app(fake) as http:
        codes = [http.get(path).status_code for _ in range(3)]
    assert codes == [200, 410, 410]


def test_link_checker_doesnt_use_up_the_link():
    fake = FakeAconex()
    path = link_path(fake)
    with app(fake) as http:
        assert http.head(path).status_code == 200
        assert http.get(path).status_code == 200


def test_made_up_link_is_refused():
    with app(FakeAconex()) as http:
        assert http.get("/files/not-a-real-link").status_code == 410


def test_link_rechecks_the_off_switch_and_project_when_used():
    fake = FakeAconex()
    for later in (Policy(allowed_projects=frozenset({"1001"}), switched_off=True), Policy()):
        path = link_path(fake)
        audit = AuditLog(":memory:")
        with app(fake, later, audit) as http:
            assert http.get(path).status_code == 403
        assert audit.recent(1)[0]["outcome"] == "blocked"


def test_link_is_only_stored_scrambled(tmp_path):
    path = link_path(FakeAconex())
    raw = (tmp_path / "gateway.db").read_bytes()
    assert path.rsplit("/", 1)[-1].encode() not in raw
