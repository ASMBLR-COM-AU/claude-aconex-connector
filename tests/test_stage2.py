"""Stage 2 tests: the read-only menu for projects, people and the register,
run against the fake Aconex."""

import json

import anyio
import pytest
from mcp.client.client import Client

from gateway.aconex import AconexError, seg
from gateway.server import build_server
from tests.fake_aconex import FakeAconex

STAGE2_TOOLS = {
    "ping",
    # projects and people
    "list_projects", "search_project_directory", "get_person", "gateway_account",
    "list_mailing_groups", "search_aconex_directory", "get_company",
    "list_project_fields", "get_logo",
    # register
    "search_register", "revision_history", "document_details", "register_fields",
    "current_drawing_set_rule", "document_event_log", "document_transmittals",
    "saved_register_searches", "documents_changed_since", "related_document_changes",
}


def call(fake: FakeAconex, name: str, args: dict | None = None):
    """Call one tool the way Claude would. Returns (is_error, data)."""
    async def run():
        async with Client(build_server(fake.client())) as client:
            return await client.call_tool(name, args or {})

    result = anyio.run(run)
    if result.is_error:
        return True, result.content[0].text
    if result.structured_content is not None:
        return False, result.structured_content
    first = result.content[0]
    return False, json.loads(first.text) if getattr(first, "text", None) else first


def tools():
    async def run():
        async with Client(build_server(FakeAconex().client())) as client:
            return (await client.list_tools()).tools
    return anyio.run(run)


# ── the menu ────────────────────────────────────────────────────────

def test_menu_is_exactly_stage2():
    assert {t.name for t in tools()} == STAGE2_TOOLS


def test_every_aconex_tool_is_marked_read_only():
    for t in tools():
        if t.name == "ping":
            continue
        assert t.annotations and t.annotations.read_only_hint is True, t.name
        assert t.annotations.destructive_hint is False, t.name


def test_no_catch_all_or_writing_tools():
    for t in tools():
        for word in ("api", "call", "send", "delete", "upload", "create", "update", "raw"):
            assert word not in t.name.split("_"), t.name


# ── the Aconex connection's own guard rails ─────────────────────────

@pytest.mark.parametrize("bad", ["../1001", "1001/mail", "1001?x=1", "", "a" * 65, "10 01"])
def test_ids_cannot_change_the_endpoint(bad):
    with pytest.raises(AconexError):
        seg(bad)


def test_post_is_refused_except_search():
    client = FakeAconex().client()
    with pytest.raises(AconexError, match="doesn't allow POST"):
        anyio.run(client.search_post, "/projects/1001/mail", {})


def test_only_reads_reach_aconex():
    fake = FakeAconex()
    for name, args in [
        ("list_projects", {}),
        ("search_register", {"project_id": "1001", "status": "For Review"}),
        ("document_transmittals", {"project_id": "1001", "document_number": "S-1100"}),
        ("documents_changed_since", {"project_id": "1001", "since": "2026-10-01"}),
    ]:
        assert call(fake, name, args)[0] is False, name
    for c in fake.calls:
        assert c["method"] == "GET" or c["path"].endswith("/register/search"), c


def test_not_connected_is_a_plain_message():
    fake = FakeAconex()

    async def run():
        async with Client(build_server(fake.client(connected=False))) as client:
            return await client.call_tool("list_projects", {})

    result = anyio.run(run)
    assert result.is_error
    assert "isn't connected to Aconex yet" in result.content[0].text


def test_logs_in_again_once_when_the_token_expires():
    fake = FakeAconex()
    fake.reject_next_token = True
    is_error, data = call(fake, "list_projects")
    assert not is_error and fake.logins == 2


def test_unknown_document_is_a_plain_message():
    is_error, text = call(FakeAconex(), "document_details", {"project_id": "1001", "document_id": "4040"})
    assert is_error and "not found" in text


def test_bad_id_never_reaches_aconex():
    fake = FakeAconex()
    is_error, text = call(fake, "document_details", {"project_id": "1001", "document_id": "../../users"})
    assert is_error and "valid Aconex document ID" in text
    assert fake.calls == []


# ── projects and people ─────────────────────────────────────────────

def test_list_projects():
    _, data = call(FakeAconex(), "list_projects")
    assert data["projects"] == [
        {"project_id": "1001", "name": "Harbour St Tower", "code": "HST", "approved": True},
        {"project_id": "1002", "name": "Riverside Depot", "code": "RSD", "approved": True},
    ]


def test_directory_filters_locally():
    fake = FakeAconex()
    _, data = call(fake, "search_project_directory", {"project_id": "1001", "name": "sam", "company": "builder"})
    assert [p["name"] for p in data["people"]] == ["Sam Ortiz"]
    assert fake.calls[-1]["params"] == {}  # the live directory rejects search parameters


def test_get_person_on_project_and_globally():
    fake = FakeAconex()
    _, on_project = call(fake, "get_person", {"user_id": "501", "project_id": "1001"})
    _, globally = call(fake, "get_person", {"user_id": "501"})
    assert on_project["first_name"] == "Sam" == globally["first_name"]
    assert [c["path"] for c in fake.calls] == ["/projects/1001/users/501", "/users/501"]


def test_gateway_account():
    _, data = call(FakeAconex(), "gateway_account")
    assert data["user_name"] == "aconex-gateway"


def test_mailing_groups():
    _, data = call(FakeAconex(), "list_mailing_groups", {"project_id": "1001"})
    assert data["groups"][0]["groupName"] == "Structural team"


def test_aconex_directory_needs_a_filter_and_maps_names():
    fake = FakeAconex()
    is_error, _ = call(fake, "search_aconex_directory", {})
    assert is_error and fake.calls == []
    _, data = call(fake, "search_aconex_directory", {"company": "Steel", "given_name": "Al"})
    assert fake.calls[-1]["params"] == {"org_name": "Steel", "given_name": "Al"}
    assert data["people"][0]["last_name"] == "Ng"


def test_company_and_project_fields():
    fake = FakeAconex()
    _, company = call(fake, "get_company", {"organization_id": "88"})
    assert company["organization_name"] == "Acme Engineers"
    assert company["address.city"] == "Sydney"
    _, fields = call(fake, "list_project_fields", {"project_id": "1001"})
    assert [f["label"] for f in fields["fields"]] == ["Building", "Level"]


def test_logo_needs_exactly_one_target():
    fake = FakeAconex()
    assert call(fake, "get_logo", {})[0] is True
    assert call(fake, "get_logo", {"project_id": "1001", "organization_id": "88"})[0] is True

    async def run():
        async with Client(build_server(fake.client())) as client:
            return await client.call_tool("get_logo", {"project_id": "1001"})

    result = anyio.run(run)
    assert not result.is_error and result.content[0].type == "image"
    assert fake.calls[-1]["params"] == {"projectid": "1001"}


# ── register ────────────────────────────────────────────────────────

def test_search_register_builds_the_live_query():
    fake = FakeAconex()
    _, data = call(fake, "search_register", {
        "project_id": "1001", "words": "slab", "discipline": "Structural", "status": "for review",
        "limit": 30,
    })
    search = fake.calls[-1]
    assert search["path"] == "/projects/1001/register"
    assert search["params"]["search_query"] == (
        '(docno:"slab" OR title:"slab") AND discipline:"Structural" AND statusid:"358"')
    assert search["params"]["page_size"] == "50"  # next multiple of 25
    assert search["params"]["search_type"] == "PAGED"
    assert "show_document_history" not in search["params"]
    assert data["documents"][0] == {
        "document_id": "9001", "number": "S-1100", "revision": "B", "title": "Level 1 slab plan",
        "status": "For Construction", "date": "2026-10-20T00:00:00.000Z",
        "discipline": "Structural", "type": "Drawing", "file": "S-1100_B.pdf",
    }
    assert data["total"] == 2


def test_search_register_options():
    fake = FakeAconex()
    call(fake, "search_register", {"project_id": "1001", "words": "footing", "search_inside_files": True,
                                   "include_old_revisions": True, "current_drawings_only": True,
                                   "sort_by": "date"})
    search = fake.calls[-1]
    assert search["path"] == "/projects/1001/drawings"
    assert search["params"]["search_query"] == '"footing"'
    assert search["params"]["content_search"] == "true"
    assert search["params"]["show_document_history"] == "true"
    assert search["params"]["sort_field"] == "revisiondate"


def test_unknown_status_lists_the_real_ones():
    is_error, text = call(FakeAconex(), "search_register", {"project_id": "1001", "status": "Approved"})
    assert is_error and "for construction" in text and "for review" in text


def test_quotes_in_search_words_are_escaped():
    fake = FakeAconex()
    call(fake, "search_register", {"project_id": "1001", "number": 'S"1100'})
    assert fake.calls[-1]["params"]["search_query"] == 'docno:"S\\"1100"'


def test_revision_history_keeps_only_the_exact_number_oldest_first():
    _, data = call(FakeAconex(), "revision_history", {"project_id": "1001", "document_number": "s-1100"})
    assert [r["revision"] for r in data["revisions"]] == ["A", "B"]


def test_document_details():
    _, data = call(FakeAconex(), "document_details", {"project_id": "1001", "document_id": "9001"})
    assert data["review_source"] == "WF-000020" and data["document_id"] == "9001"


def test_register_fields():
    _, data = call(FakeAconex(), "register_fields", {"project_id": "1001"})
    status = next(f for f in data["fields"] if f["field"] == "statusid")
    assert status["values"] == ["For Review", "For Construction"]
    assert next(f for f in data["fields"] if f["field"] == "title") == {"field": "title", "name": "Title"}
    # Each field once, the searchable (lower-case) version (live shape).
    created_by = [f for f in data["fields"] if f["name"] == "Created By"]
    assert created_by == [{"field": "author", "name": "Created By"}]


def test_current_drawing_set_rule():
    _, data = call(FakeAconex(), "current_drawing_set_rule", {"project_id": "1001"})
    assert data["document_types.document_type"] == "Drawing"


def test_event_log():
    _, data = call(FakeAconex(), "document_event_log", {"project_id": "1001", "document_id": "9001"})
    assert [e["type"] for e in data["events"]] == ["Registered", "Transmitted"]


def test_transmittals_uses_the_gateway_account_ids():
    fake = FakeAconex()
    _, data = call(fake, "document_transmittals", {"project_id": "1001", "document_number": "S-1100"})
    body = fake.calls[-1]["json"]
    assert body["orgId"] == "77" and body["userId"] == "900"
    assert body["returnTransmittalInfo"] is True
    detail = data["results"]["searchResults"][0]["transmittalDetails"][0]
    assert detail["recvTransmittalNum"] == "TRANS-000042"
    assert detail["recvTransmittalDate"] == "2026-03-15T23:07:44+00:00"


def test_saved_searches():
    _, data = call(FakeAconex(), "saved_register_searches", {"project_id": "1001"})
    assert data["saved_searches"] == [{"group": "Standard Searches", "name": "Approved", "id": "1",
                                       "filters": {"doc_status_id": "1", "registered": "true"}}]


def test_documents_changed_since_rounds_to_the_hour():
    fake = FakeAconex()
    _, data = call(fake, "documents_changed_since", {"project_id": "1001", "since": "2026-10-01T09:45"})
    assert fake.calls[-1]["params"]["everythingsince"] == "2026-10-01T09:00:00.000Z"
    assert [c["document_id"] for c in data["changes"]] == ["9001", "9002"]  # child or attribute form


def test_unreadable_changes_reply_reports_its_shape_not_its_data():
    fake = FakeAconex()
    fake.routes[("GET", "/projects/1001/register/integrity")] = (
        b"<Integrity><Batch>secret-ish</Batch></Integrity>",)
    _, data = call(fake, "documents_changed_since", {"project_id": "1001", "since": "2026-10-01"})
    assert data["changes"] == []
    assert "/Integrity/Batch" in data["unread_reply_shape"]
    assert "secret-ish" not in str(data)


def test_bad_date_is_a_plain_message():
    fake = FakeAconex()
    is_error, text = call(fake, "documents_changed_since", {"project_id": "1001", "since": "last week"})
    assert is_error and "2026-11-01" in text and fake.calls == []


def test_related_document_changes():
    fake = FakeAconex()
    _, data = call(fake, "related_document_changes",
                   {"project_id": "1001", "since": "2026-10-01", "until": "2026-10-31"})
    params = fake.calls[-1]["params"]
    assert params["from"] == "2026-10-01T00:00:00.000Z" and params["to"] == "2026-10-31T00:00:00.000Z"
    assert data["changes"][0]["action"] == "CREATED"


# ── search know-how (docs/search-know-how.md) ───────────────────────

def test_door_number_is_found_on_the_drawing_automatically():
    """A door number isn't in any title, so the plain search finds nothing and
    the gateway searches the text on the drawings by itself."""
    fake = FakeAconex()
    _, data = call(fake, "search_register", {"project_id": "1001", "words": "1DG203"})
    first, second = fake.calls[-2:]
    assert "content_search" not in first["params"]
    assert second["params"]["content_search"] == "true"
    assert second["params"]["search_query"] == '"1DG203"'
    assert data["documents"][0]["number"] == "A-2201"
    assert "inside the files" in data["note"]


def test_asking_for_inside_files_directly_searches_once():
    fake = FakeAconex()
    _, data = call(fake, "search_register",
                   {"project_id": "1001", "words": "1DG203", "search_inside_files": True})
    assert len(fake.calls) == 1 and "note" not in data
    assert data["documents"][0]["number"] == "A-2201"


def test_empty_search_explains_what_to_try():
    _, data = call(FakeAconex(), "search_register", {"project_id": "1001", "words": "NOTHINGHERE"})
    assert data["documents"] == []
    assert any("include_old_revisions" in t for t in data["tips"])
    assert "inside the files" in data["note"]


def test_no_automatic_retry_without_words():
    fake = FakeAconex()
    call(fake, "search_register", {"project_id": "1001", "number": "NOTHINGHERE"})
    assert len(fake.calls) == 1


def test_created_by_uses_the_projects_own_field():
    fake = FakeAconex()
    call(fake, "search_register", {"project_id": "1001", "created_by": "Acme Engineers"})
    assert fake.calls[-1]["params"]["search_query"] == 'author:"Acme Engineers"'


def test_created_by_explains_when_a_project_has_no_such_field():
    fake = FakeAconex()
    fake.routes[("GET", "/projects/1001/register/schema")] = (
        b"<RegisterSchema><SchemaField><Identifier>title</Identifier><Name>Title</Name></SchemaField></RegisterSchema>",)
    is_error, text = call(fake, "search_register", {"project_id": "1001", "created_by": "Acme"})
    assert is_error and "no Created By field" in text and "Title" in text


def test_search_tool_description_teaches_the_tricks():
    description = next(t.description for t in tools() if t.name == "search_register")
    for phrase in ("door number", "search_inside_files", "include_old_revisions", "created_by"):
        assert phrase in description
