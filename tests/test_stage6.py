"""Stage 6 (experiment) tests: a real PDF to Claude, in the reply or by link."""

import base64
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


def call(fake, name, args, policy=APPROVED, audit=None):
    async def run():
        async with Client(build_server(fake.client(), policy, audit or AuditLog(":memory:"))) as c:
            return await c.call_tool(name, args)
    return anyio.run(run)


def test_pdf_comes_back_inside_the_reply():
    fake = FakeAconex()
    result = call(fake, "test_pdf_in_reply", {"project_id": "1001", "document_id": "9001"})
    assert not result.is_error
    text, resource = result.content
    assert "S-1100 Rev B.pdf" in text.text
    assert resource.type == "resource"
    assert resource.resource.mime_type == "application/pdf"
    assert base64.b64decode(resource.resource.blob) == PDF
    assert fake.calls[-1]["method"] == "GET" and fake.calls[-1]["path"] == "/projects/1001/register/9001"


def test_choosing_a_file_of_a_multi_file_document():
    fake = FakeAconex()
    call(fake, "test_pdf_in_reply", {"project_id": "1001", "document_id": "9001", "file_name": "S-1100.dwg"})
    assert fake.calls[-1]["params"] == {"fileName": "S-1100.dwg"}


def link_for(fake, policy=APPROVED):
    result = call(fake, "test_pdf_download_link", {"project_id": "1001", "document_id": "9001"}, policy)
    data = result.structured_content or json.loads(result.content[0].text)
    return urlsplit(data["download_url"]).path


def test_link_downloads_the_real_pdf_with_its_name():
    fake = FakeAconex()
    path = link_for(fake)
    with TestClient(build_app(fake.client(), APPROVED, AuditLog(":memory:")), base_url="https://testserver") as http:
        response = http.get(path)
    assert response.status_code == 200 and response.content == PDF
    assert response.headers["content-type"] == "application/pdf"
    assert "S-1100%20Rev%20B.pdf" in response.headers["content-disposition"]


def test_link_works_five_times_then_stops():
    fake = FakeAconex()
    path = link_for(fake)
    with TestClient(build_app(fake.client(), APPROVED, AuditLog(":memory:")), base_url="https://testserver") as http:
        codes = [http.get(path).status_code for _ in range(6)]
    assert codes == [200] * 5 + [410]


def test_made_up_link_is_refused():
    with TestClient(build_app(FakeAconex().client(), APPROVED, AuditLog(":memory:")),
                    base_url="https://testserver") as http:
        assert http.get("/files/not-a-real-link").status_code == 410


def test_link_rechecks_the_off_switch_and_project_when_used():
    fake = FakeAconex()
    path = link_for(fake)
    for later in (Policy(allowed_projects=frozenset({"1001"}), switched_off=True), Policy()):
        audit = AuditLog(":memory:")
        with TestClient(build_app(fake.client(), later, audit), base_url="https://testserver") as http:
            assert http.get(path).status_code == 403
        assert audit.recent(1)[0]["outcome"] == "blocked"


def test_link_is_only_stored_scrambled(tmp_path):
    path = link_for(FakeAconex())
    token = path.rsplit("/", 1)[-1]
    raw = (tmp_path / "gateway.db").read_bytes()
    assert token.encode() not in raw
