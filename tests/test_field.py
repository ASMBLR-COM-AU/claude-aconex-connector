"""Aconex Field: the read-only defects items, and the switch that puts them on the menu.

Field's answers are shaped like Oracle's Field API 2.6.0 specification
(checked 17 Nov 2026); not yet checked against a live Field project.
"""

import json

import anyio
import httpx
import pytest
from mcp.client.client import Client

from gateway.aconex import AconexClient, Settings
from gateway.aconex.client import Refused, check_outgoing
from gateway.guard import AuditLog, Policy
from gateway.server import build_server

APPROVED = Policy(allowed_projects=frozenset({"1001"}))
FIELD = "/field-management/api"

AREAS = {"areas": [
    {"id": 10, "parentId": None, "name": "Building A", "children": [
        {"id": 11, "parentId": 10, "name": "Level 1", "children": []},
        {"id": 12, "parentId": 10, "name": "Level 2", "children": [
            {"id": 13, "parentId": 12, "name": "Unit 201", "children": []}]}]},
    {"id": 20, "parentId": None, "name": "Carpark", "children": []},
]}
TYPES = {"issue_types": [{"id": "t1", "name": "Defect", "enabled": True},
                         {"id": "t2", "name": "Safety", "enabled": True}]}


def issue(n, kind, company, status="Open", area=(10, "Building A")):
    return {"issue_id": f"i{n}", "issue_number": n, "description": f"Issue {n}", "status": status,
            "issue_type": {"id": "t1" if kind == "Defect" else "t2", "name": kind},
            "assigned_to": {"organization": {"id": company, "name": f"{company} Pty Ltd", "trading_name": company},
                            "user": {"first_name": "Pat", "last_name": "Quinn"}} if company else None,
            "area": {"id": area[0], "name": area[1], "path": [{"id": 10, "name": "Building A"}]
                     + ([{"id": area[0], "name": area[1]}] if area[0] != 10 else [])},
            "location_detail": "Near lift", "meta_data": {"created_by": {"first_name": "Jo", "last_name": "Park"},
                                                          "created_at": "2026-11-01T02:00:00Z"},
            "due_date": "2026-11-20", "attachments": [{"id": "a1", "file_name": "photo.jpg", "url": "x"}]}


ISSUES = {
    "10": [issue(1, "Defect", "Sparkies"), issue(2, "Defect", "Sparkies"), issue(3, "Safety", "Sparkies"),
           issue(4, "Defect", "Plumbers", area=(13, "Unit 201")), issue(5, "Defect", None, status="Closed")],
    "20": [issue(6, "Defect", "Plumbers", area=(20, "Carpark"))],
}


class FakeField:
    def __init__(self):
        self.calls = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.host.startswith("constructionandengineering"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        assert request.method == "GET", f"A write reached Aconex: {request.method} {request.url}"
        path = request.url.path
        assert path.startswith(FIELD), path
        path = path.removeprefix(FIELD)
        params = dict(request.url.params)
        self.calls.append((path, params))
        if path == "/projects/1001/areas":
            return httpx.Response(200, json=AREAS)
        if path == "/projects/1001/issue_types":
            return httpx.Response(200, json=TYPES)
        parts = path.split("/")
        if len(parts) == 6 and parts[5] == "issues":
            area = parts[4]
            found = ISSUES.get(area, []) if area in ISSUES else [i for v in ISSUES.values() for i in v
                                                                 if str(i["area"]["id"]) == area]
            if "status" in params:
                found = [i for i in found if i["status"] in params["status"].split(",")]
            if "issue_type" in params:
                found = [i for i in found if i["issue_type"]["id"] in params["issue_type"].split(",")]
            if "issue_number" in params:
                found = [i for i in found if str(i["issue_number"]) == params["issue_number"]]
            size, page = int(params.get("page_size", 25)), int(params.get("page_number", 1))
            pages = max(1, -(-len(found) // size))
            return httpx.Response(200, json={"issues": found[(page - 1) * size: page * size],
                                             "total_results": len(found), "total_pages": pages})
        if len(parts) == 7 and parts[5] == "issues":
            hit = [i for v in ISSUES.values() for i in v if i["issue_id"] == parts[6]]
            return httpx.Response(200, json=hit[0]) if hit else httpx.Response(404, json={})
        return httpx.Response(404, json={})

    def client(self):
        return AconexClient(Settings("id", "secret"), transport=httpx.MockTransport(self.handler))


def call(fake, name, args):
    async def run():
        async with Client(build_server(fake.client(), APPROVED, AuditLog(":memory:"))) as c:
            r = await c.call_tool(name, args)
            return (True, r.content[0].text) if r.is_error else (False, r.structured_content or
                                                                  json.loads(r.content[0].text))
    return anyio.run(run)


def menu():
    async def run():
        async with Client(build_server(FakeField().client(), APPROVED, AuditLog(":memory:"))) as c:
            return {t.name for t in (await c.list_tools()).tools}
    return anyio.run(run)


@pytest.fixture
def field_on(monkeypatch):
    monkeypatch.setenv("ENABLE_FIELD", "1")


# ── the switch ──────────────────────────────────────────────────────

FIELD_ITEMS = {"field_areas", "search_field_issues", "field_issue_counts", "field_issue_details"}


def test_field_is_off_unless_switched_on(monkeypatch):
    monkeypatch.delenv("ENABLE_FIELD", raising=False)
    assert not FIELD_ITEMS & menu()


def test_field_items_appear_when_switched_on(field_on):
    assert FIELD_ITEMS <= menu()


# ── the outgoing check ──────────────────────────────────────────────

@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_field_writes_are_refused(method):
    s = Settings("id", "secret")
    with pytest.raises(Refused, match="only reads Aconex Field"):
        check_outgoing(httpx.Request(method, "https://api.aconex.com/field-management/api/projects/1/areas/2/issues"), s)


def test_field_reads_are_allowed_and_follow_the_site():
    check_outgoing(httpx.Request("GET", "https://api.aconex.com/field-management/api/projects/1/areas"),
                   Settings("id", "secret"))
    ea = Settings("id", "secret", api_url="https://ea1.aconex.com/api")
    assert ea.field_base == "https://ea1.aconex.com/field-management/api"
    check_outgoing(httpx.Request("GET", "https://ea1.aconex.com/field-management/api/projects/1/areas"), ea)
    with pytest.raises(Refused):
        check_outgoing(httpx.Request("POST", "https://ea1.aconex.com/field-management/api/projects/1/areas"), ea)


# ── the items ───────────────────────────────────────────────────────

def test_areas_are_flattened_with_paths(field_on):
    err, out = call(FakeField(), "field_areas", {"project_id": "1001"})
    assert not err and out["count"] == 5
    assert {"area_id": "13", "path": "Building A > Level 2 > Unit 201"} in out["areas"]


def test_unapproved_project_is_refused(field_on):
    fake = FakeField()
    err, text = call(fake, "field_areas", {"project_id": "9999"})
    assert err and fake.calls == []


def test_search_across_all_areas_with_type_and_status(field_on):
    fake = FakeField()
    err, out = call(fake, "search_field_issues", {"project_id": "1001", "issue_type": "defect", "status": "open"})
    assert not err
    assert sorted(i["number"] for i in out["issues"]) == [1, 2, 4, 6]
    sent = [p for path, p in fake.calls if path.endswith("/issues")]
    assert all(p["status"] == "Open" and p["issue_type"] == "t1" and p["include_child_areas"] == "true" for p in sent)
    first = next(i for i in out["issues"] if i["number"] == 4)
    assert first["company"] == "Plumbers" and first["area"] == "Building A > Unit 201" and first["raised_by"] == "Jo Park"


def test_search_by_company_and_area(field_on):
    err, out = call(FakeField(), "search_field_issues", {"project_id": "1001", "company": "spark"})
    assert not err and sorted(i["number"] for i in out["issues"]) == [1, 2, 3] and out["matching"] == 3
    fake = FakeField()
    err, out = call(fake, "search_field_issues", {"project_id": "1001", "area": "carpark"})
    assert not err and [i["number"] for i in out["issues"]] == [6]


def test_bad_filters_are_explained(field_on):
    err, text = call(FakeField(), "search_field_issues", {"project_id": "1001", "issue_type": "Termites"})
    assert err and "Defect" in text and "Safety" in text
    err, text = call(FakeField(), "search_field_issues", {"project_id": "1001", "status": "Lost"})
    assert err and "Open" in text
    err, text = call(FakeField(), "search_field_issues", {"project_id": "1001", "area": "Level 9"})
    assert err and "field_areas" in text
    err, text = call(FakeField(), "search_field_issues", {"project_id": "1001", "raised_from": "last week"})
    assert err and "2026-11-01" in text


def test_counts_by_company_then_type(field_on):
    err, out = call(FakeField(), "field_issue_counts", {"project_id": "1001", "by": "company", "then_by": "type"})
    assert not err and out["counted"] == 6
    sparkies = out["counts"][0]
    assert sparkies["company"] == "Sparkies" and sparkies["total"] == 3
    assert sparkies["type"] == [{"name": "Defect", "count": 2}, {"name": "Safety", "count": 1}]
    assert {"company": "(not assigned)", "total": 1, "type": [{"name": "Defect", "count": 1}]} in out["counts"]


def test_counts_simple(field_on):
    err, out = call(FakeField(), "field_issue_counts", {"project_id": "1001", "by": "status"})
    assert not err and out["counts"] == [{"status": "Open", "count": 5}, {"status": "Closed", "count": 1}]


def test_details_by_number(field_on):
    err, out = call(FakeField(), "field_issue_details", {"project_id": "1001", "number": "4"})
    assert not err and out["issue_id"] == "i4" and out["assigned_person"] == "Pat Quinn"
    assert out["attachments"] == ["photo.jpg"]
    err, text = call(FakeField(), "field_issue_details", {"project_id": "1001", "number": "99"})
    assert err and "No issue number 99" in text
