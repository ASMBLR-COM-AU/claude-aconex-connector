"""Stage 2 tools: the document register. All read-only. No file downloads
yet (stage 6)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from gateway.aconex import AconexClient, AconexError, seg
from gateway.aconex.parse import first, flatten, lucene_phrase, page_info, schema_values, text
from gateway.tools import clamp, parse_when, read_tool

RETURN_FIELDS = "docno,title,revision,statusid,doctype,discipline,revisiondate,filename"
SORTS = {"number": ("docno", "asc"), "date": ("revisiondate", "desc")}
PAGE_STEP, PAGE_MAX = 25, 500  # live: page sizes must be multiples of 25, up to 500


def page_size(wanted: int) -> int:
    return min(PAGE_MAX, max(PAGE_STEP, -(-wanted // PAGE_STEP) * PAGE_STEP))


def parse_documents(root) -> list:
    """Register rows (live element names, with mail-attachment fallbacks)."""
    return [
        {
            "document_id": (d.get("DocumentId") or text(d, "DocumentId")).strip(),
            "number": first(d, "DocumentNumber", "DocumentNo"),
            "revision": text(d, "Revision"),
            "title": text(d, "Title"),
            "status": first(d, "DocumentStatus", "StatusId", "Status"),
            "date": text(d, "RevisionDate"),
            "discipline": text(d, "Discipline"),
            "type": first(d, "DocumentType", "DocType"),
            "file": first(d, "Filename", "FileName"),
        }
        for d in root.iter("Document")
    ]


def leaf_rows(root, limit: int) -> list:
    """Rows of a list response whose element names aren't confirmed: every
    element that holds only plain values, flattened."""
    rows = []
    for el in root.iter():
        kids = list(el)
        if el is not root and kids and all(len(list(k)) == 0 for k in kids):
            rows.append(flatten(el))
            if len(rows) >= limit:
                break
    return rows


def register(server: MCPServer, aconex: AconexClient) -> None:
    status_ids: dict[str, dict] = {}

    async def status_id(project: str, status: str) -> str:
        if status.strip().isdigit():
            return status.strip()
        if project not in status_ids:
            schema = await aconex.get_xml(f"/projects/{project}/register/schema")
            status_ids[project] = {k.casefold(): v for k, v in schema_values(schema, "statusid").items()}
        found = status_ids[project].get(status.strip().casefold())
        if not found:
            names = ", ".join(sorted(status_ids[project])) or "none listed"
            raise ToolError(f"No status called {status!r} on this project. Its statuses: {names}.")
        return found

    @read_tool(server,
               "Search a project's document register. Free words match the document number or "
               "title. Filters: number, title, discipline, doc_type, status (copy values from a "
               "result row: each project names them differently). Current revisions only unless "
               "include_old_revisions. search_inside_files searches the text inside the files. "
               "current_drawings_only limits it to the project's current drawing set.")
    async def search_register(project_id: str, words: str = "", number: str = "", title: str = "",
                              discipline: str = "", doc_type: str = "", status: str = "",
                              include_old_revisions: bool = False,
                              search_inside_files: bool = False,
                              current_drawings_only: bool = False,
                              sort_by: Literal["number", "date"] = "number",
                              limit: int = 25, page: int = 1) -> dict:
        project = seg(project_id, "project ID")
        clauses = []
        for word in words.split():
            phrase = lucene_phrase(word)
            # Inside-file search takes plain words; otherwise match number or title (live).
            clauses.append(f'"{phrase}"' if search_inside_files
                           else f'(docno:"{phrase}" OR title:"{phrase}")')
        if number:
            clauses.append(f'docno:"{lucene_phrase(number)}"')
        clauses += [f'title:"{lucene_phrase(w)}"' for w in title.split()]
        for field, value in (("discipline", discipline), ("doctype", doc_type)):
            if value:
                clauses.append(f'{field}:"{lucene_phrase(value)}"')
        if status:
            clauses.append(f'statusid:"{await status_id(project, status)}"')

        limit = clamp(limit, 1, 100)
        sort_field, direction = SORTS[sort_by]
        params = {
            "return_fields": RETURN_FIELDS,
            "search_type": "PAGED",
            "page_size": page_size(limit),
            "page_number": clamp(page, 1, 10_000),
            "sort_field": sort_field,
            "sort_direction": direction,
        }
        if clauses:
            params["search_query"] = " AND ".join(clauses)
        if include_old_revisions:
            params["show_document_history"] = "true"
        if search_inside_files:
            params["content_search"] = "true"
        where = "drawings" if current_drawings_only else "register"
        root = await aconex.get_xml(f"/projects/{project}/{where}", params)
        return {"documents": parse_documents(root)[:limit], **page_info(root)}

    @read_tool(server, "Every revision of one document, oldest first, by its document number.")
    async def revision_history(project_id: str, document_number: str) -> dict:
        project = seg(project_id, "project ID")
        root = await aconex.get_xml(f"/projects/{project}/register", {
            "search_query": f'docno:"{lucene_phrase(document_number)}"',
            "return_fields": RETURN_FIELDS,
            "search_type": "PAGED", "page_size": 100, "page_number": 1,
            "show_document_history": "true",
            "sort_field": "revisiondate", "sort_direction": "asc",
        })
        # docno matching is loose; keep only this exact number.
        wanted = document_number.strip().casefold()
        rows = [d for d in parse_documents(root) if d["number"].casefold() == wanted]
        rows.sort(key=lambda d: d["date"])
        return {"document_number": document_number, "revisions": rows}

    @read_tool(server, "Every field recorded against one document revision (author, status, "
                       "review source, file details...). Use a document_id from a search result.")
    async def document_details(project_id: str, document_id: str) -> dict:
        root = await aconex.get_xml(
            f"/projects/{seg(project_id, 'project ID')}/register/{seg(document_id, 'document ID')}/metadata")
        return flatten(root, limit=150)

    @read_tool(server, "The register's fields on a project and their allowed values "
                       "(disciplines, types, statuses...). Use it to search with exact values.")
    async def register_fields(project_id: str) -> dict:
        root = await aconex.get_xml(f"/projects/{seg(project_id, 'project ID')}/register/schema")
        fields = []
        for field in root.iter():
            identifier = text(field, "Identifier")
            if not identifier:
                continue
            values = [text(v, "Value") for v in field.iter("SchemaValue") if text(v, "Value")]
            fields.append({
                "field": identifier,
                "name": first(field, "Name", "FieldName", "Label"),
                **({"values": values[:60], "more_values": max(0, len(values) - 60)} if values else {}),
            })
        return {"fields": fields}

    @read_tool(server, "The rule that decides which documents count as the project's current "
                       "drawing set (for example by type and status).")
    async def current_drawing_set_rule(project_id: str) -> dict:
        return flatten(await aconex.get_xml(f"/projects/{seg(project_id, 'project ID')}/currentSet"))

    @read_tool(server, "A document's history across all its revisions: registered, viewed, "
                       "downloaded, sent on a transmittal, and so on.")
    async def document_event_log(project_id: str, document_id: str, limit: int = 50) -> dict:
        root = await aconex.get_xml(
            f"/projects/{seg(project_id, 'project ID')}/register/{seg(document_id, 'document ID')}/eventlog")
        return {"events": leaf_rows(root, clamp(limit, 1, 200))}

    @read_tool(server, "Which transmittals a document went out on, by document number.")
    async def document_transmittals(project_id: str, document_number: str) -> dict:
        project = seg(project_id, "project ID")
        me = await aconex.get_xml("/user")
        org_id, user_id = text(me, ".//OrganizationId"), text(me, ".//UserId")
        if not (org_id and user_id):
            raise AconexError("Couldn't work out the gateway's own Aconex user and company IDs.")
        response = await aconex.search_post(f"/projects/{project}/register/search", {
            "orgId": org_id,
            "userId": user_id,
            "searchQuery": document_number,
            "returnTransmittalInfo": True,
            "returnTransmittalIds": True,
            "resultSize": 25,
        })
        try:
            return {"results": response.json()}
        except ValueError:
            raise AconexError("Aconex sent back something unexpected for this search.") from None

    @read_tool(server, "The saved register searches people have set up on a project, with their "
                       "filters. Run one by passing its filters to search_register.")
    async def saved_register_searches(project_id: str) -> dict:
        root = await aconex.get_xml(f"/projects/{seg(project_id, 'project ID')}/documents/savedSearch")
        return {"saved_searches": [flatten(s) for s in root][:100]}

    @read_tool(server, "Documents that changed (or had something happen to them) since a date, "
                       "to answer questions like 'what's new this week'. Aconex works to the hour.")
    async def documents_changed_since(project_id: str, since: str, limit: int = 200) -> dict:
        moment = parse_when(since, "since")
        root = await aconex.get_xml(f"/projects/{seg(project_id, 'project ID')}/register/integrity", {
            "everythingsince": moment.strftime("%Y-%m-%dT%H:00:00.000Z"),
        })
        return {"since": moment.isoformat(), "changes": leaf_rows(root, clamp(limit, 1, 500))}

    @read_tool(server, "Links between related documents that were added or removed in a date range. "
                       "Aconex has no way to list every document related to one document.")
    async def related_document_changes(project_id: str, since: str, until: str = "") -> dict:
        start = parse_when(since, "since")
        end = parse_when(until, "until") if until else datetime.now(timezone.utc)
        params = {"from": start.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                  "to": end.strftime("%Y-%m-%dT%H:%M:%S.000Z"), "page": 1}
        data = await aconex.get_json(
            f"/document-relationships/projects/{seg(project_id, 'project ID')}/transactions", params)
        return {"changes": data}
