"""Stage 2 tools: the document register. All read-only. No file downloads
yet (stage 6)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from gateway.aconex import AconexError, seg
from gateway.aconex.parse import first, flatten, lucene_phrase, page_info, schema_values, text
from gateway.tools import Gateway, clamp, parse_when, read_tool

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


def empty_search_tips(searched_inside: bool, with_history: bool, filtered: bool) -> list[str]:
    """What to try next when a register search finds nothing."""
    tips = []
    if not with_history:
        tips.append("Superseded revisions are hidden: try include_old_revisions=true.")
    if filtered:
        tips.append("Filter values must match this project's own names exactly: check them "
                    "with register_fields, or drop a filter.")
    if not searched_inside:
        tips.append("For text printed on a drawing (door numbers, tags, grid lines), "
                    "try search_inside_files=true.")
    tips.append("Try fewer or shorter words: every word must match.")
    return tips


def register(server: MCPServer, gw: Gateway) -> None:
    aconex = gw.aconex
    schemas: dict[str, object] = {}

    async def schema(project: str):
        if project not in schemas:
            schemas[project] = await aconex.get_xml(f"/projects/{project}/register/schema")
        return schemas[project]

    async def status_id(project: str, status: str) -> str:
        if status.strip().isdigit():
            return status.strip()
        ids = {k.casefold(): v for k, v in schema_values(await schema(project), "statusid").items()}
        found = ids.get(status.strip().casefold())
        if not found:
            names = ", ".join(sorted(ids)) or "none listed"
            raise ToolError(f"No status called {status!r} on this project. Its statuses: {names}.")
        return found

    async def created_by_field(project: str) -> str:
        """The register field behind Aconex's "Created By" column. Its name
        isn't in Oracle's guides, so it's found in the project's register
        schema (to confirm live in stage 5)."""
        fields = []
        for field in (await schema(project)).iter():
            identifier = text(field, "Identifier")
            if not identifier:
                continue
            name = first(field, "Name", "FieldName", "Label")
            fields.append(name or identifier)
            squashed = (identifier + " " + name).casefold().replace(" ", "").replace("_", "")
            if "createdby" in squashed:
                return identifier
        raise ToolError("This project's register has no Created By field to search. "
                        "Its fields: " + (", ".join(fields) or "none listed") + ".")

    @read_tool(server, gw,
               "Search a project's document register, like the search bar in Aconex. "
               "words: free text, matched against document number and title. "
               "search_inside_files=true searches the text ON the documents and drawings: use it "
               "for anything printed on a drawing rather than in its title, such as a door "
               "number (1DG203), room, grid line, equipment tag or specification clause. "
               "include_old_revisions=true also returns superseded revisions (Aconex's 'show "
               "document history'); without it only current revisions come back. "
               "created_by: the company (or person) that created the document. "
               "Filters number, title, discipline, doc_type and status use each project's own "
               "names: copy them from a result row or register_fields. "
               "current_drawings_only limits it to the project's current drawing set. "
               "If nothing matches the number or title, the gateway also searches inside the "
               "files automatically and says so.")
    async def search_register(project_id: str, words: str = "", number: str = "", title: str = "",
                              discipline: str = "", doc_type: str = "", status: str = "",
                              created_by: str = "",
                              include_old_revisions: bool = False,
                              search_inside_files: bool = False,
                              current_drawings_only: bool = False,
                              sort_by: Literal["number", "date"] = "number",
                              limit: int = 25, page: int = 1) -> dict:
        project = seg(project_id, "project ID")
        filters = []
        if number:
            filters.append(f'docno:"{lucene_phrase(number)}"')
        filters += [f'title:"{lucene_phrase(w)}"' for w in title.split()]
        for field, value in (("discipline", discipline), ("doctype", doc_type)):
            if value:
                filters.append(f'{field}:"{lucene_phrase(value)}"')
        if status:
            filters.append(f'statusid:"{await status_id(project, status)}"')
        if created_by:
            filters.append(f'{await created_by_field(project)}:"{lucene_phrase(created_by)}"')

        limit = clamp(limit, 1, 100)
        sort_field, direction = SORTS[sort_by]
        where = "drawings" if current_drawings_only else "register"

        async def run(inside_files: bool):
            clauses = []
            for word in words.split():
                phrase = lucene_phrase(word)
                # Inside-file search takes plain words; otherwise match number or title (live).
                clauses.append(f'"{phrase}"' if inside_files
                               else f'(docno:"{phrase}" OR title:"{phrase}")')
            params = {
                "return_fields": RETURN_FIELDS,
                "search_type": "PAGED",
                "page_size": page_size(limit),
                "page_number": clamp(page, 1, 10_000),
                "sort_field": sort_field,
                "sort_direction": direction,
            }
            if clauses + filters:
                params["search_query"] = " AND ".join(clauses + filters)
            if include_old_revisions:
                params["show_document_history"] = "true"
            if inside_files:
                params["content_search"] = "true"
            root = await aconex.get_xml(f"/projects/{project}/{where}", params)
            return parse_documents(root)[:limit], page_info(root)

        documents, paging = await run(search_inside_files)
        result: dict = {}
        if not documents and words.strip() and not search_inside_files:
            documents, paging = await run(True)
            result["note"] = ("Nothing matched the document number or title, so the gateway "
                              "also searched the text inside the files.")
        result.update({"documents": documents, **paging})
        if not documents:
            result["tips"] = empty_search_tips(search_inside_files or bool(words.strip()),
                                               include_old_revisions, bool(filters))
        return result

    @read_tool(server, gw, "Every revision of one document, oldest first, by its document number.")
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

    @read_tool(server, gw, "Every field recorded against one document revision (author, status, "
                       "review source, file details...). Use a document_id from a search result.")
    async def document_details(project_id: str, document_id: str) -> dict:
        root = await aconex.get_xml(
            f"/projects/{seg(project_id, 'project ID')}/register/{seg(document_id, 'document ID')}/metadata")
        return flatten(root, limit=150)

    @read_tool(server, gw, "The register's fields on a project and their allowed values "
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

    @read_tool(server, gw, "The rule that decides which documents count as the project's current "
                       "drawing set (for example by type and status).")
    async def current_drawing_set_rule(project_id: str) -> dict:
        return flatten(await aconex.get_xml(f"/projects/{seg(project_id, 'project ID')}/currentSet"))

    @read_tool(server, gw, "A document's history across all its revisions: registered, viewed, "
                       "downloaded, sent on a transmittal, and so on.")
    async def document_event_log(project_id: str, document_id: str, limit: int = 50) -> dict:
        root = await aconex.get_xml(
            f"/projects/{seg(project_id, 'project ID')}/register/{seg(document_id, 'document ID')}/eventlog")
        return {"events": leaf_rows(root, clamp(limit, 1, 200))}

    @read_tool(server, gw, "Which transmittals a document went out on, by document number.")
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

    @read_tool(server, gw, "The saved register searches people have set up on a project, with their "
                       "filters. Run one by passing its filters to search_register.")
    async def saved_register_searches(project_id: str) -> dict:
        root = await aconex.get_xml(f"/projects/{seg(project_id, 'project ID')}/documents/savedSearch")
        return {"saved_searches": [flatten(s) for s in root][:100]}

    @read_tool(server, gw, "Documents that changed (or had something happen to them) since a date, "
                       "to answer questions like 'what's new this week'. Aconex works to the hour.")
    async def documents_changed_since(project_id: str, since: str, limit: int = 200) -> dict:
        moment = parse_when(since, "since")
        root = await aconex.get_xml(f"/projects/{seg(project_id, 'project ID')}/register/integrity", {
            "everythingsince": moment.strftime("%Y-%m-%dT%H:00:00.000Z"),
        })
        return {"since": moment.isoformat(), "changes": leaf_rows(root, clamp(limit, 1, 500))}

    @read_tool(server, gw, "Links between related documents that were added or removed in a date range. "
                       "Aconex has no way to list every document related to one document.")
    async def related_document_changes(project_id: str, since: str, until: str = "") -> dict:
        start = parse_when(since, "since")
        end = parse_when(until, "until") if until else datetime.now(timezone.utc)
        params = {"from": start.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                  "to": end.strftime("%Y-%m-%dT%H:%M:%S.000Z"), "page": 1}
        data = await aconex.get_json(
            f"/document-relationships/projects/{seg(project_id, 'project ID')}/transactions", params)
        return {"changes": data}
