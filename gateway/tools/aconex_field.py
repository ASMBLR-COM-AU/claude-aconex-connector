"""Aconex Field: defects and other site issues, read-only.

Only on the menu when the company switches Field on (ENABLE_FIELD), because
many projects don't use it. Four items: the project's areas, a search of
issues, counts of issues by company (trade), type, status or area (and
crossed, e.g. type by company), and one issue in full.

Field is a separate JSON API beside the main one, at /field-management/api on
the same host (Oracle's Field API 2.6.0 specification, checked 17 Nov 2026).
The outgoing check only lets GETs through to it.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from gateway.aconex import seg
from gateway.tools import Gateway, clamp, read_tool

PAGE = 200                 # Field's largest page
MAX_COUNTED = 5000         # issues read for counts; more are reported, not read
STATUSES = ("Open", "InDispute", "ReadyToInspect", "WorkDone", "Closed")
GROUPS = Literal["company", "type", "status", "area", "raised_by"]


def flatten_areas(nodes: list, parents: tuple = ()) -> list:
    """The area tree as rows: id, name and full path ("Building A > Level 2 > Unit 201")."""
    rows = []
    for n in nodes or []:
        path = parents + (n.get("name", ""),)
        rows.append({"area_id": str(n.get("id", "")), "name": n.get("name", ""), "path": " > ".join(path),
                     "depth": len(parents)})
        rows += flatten_areas(n.get("children") or [], path)
    return rows


def _org(assignment) -> str:
    org = (assignment or {}).get("organization") or {}
    return org.get("trading_name") or org.get("name") or ""


def _person(user) -> str:
    user = user or {}
    return " ".join(p for p in (user.get("first_name"), user.get("last_name")) if p)


def parse_issue(i: dict) -> dict:
    area = i.get("area") or {}
    path = " > ".join(a.get("name", "") for a in area.get("path") or []) or area.get("name", "")
    meta = i.get("meta_data") or {}
    return {
        "issue_id": i.get("issue_id", ""),
        "number": i.get("issue_number", ""),
        "type": (i.get("issue_type") or {}).get("name", ""),
        "status": i.get("status", ""),
        "description": i.get("description", ""),
        "area": path,
        "area_id": str(area.get("id", "")),
        "location": i.get("location_detail", ""),
        "company": _org(i.get("assigned_to")) or "(not assigned)",
        "raised_by": _person(meta.get("created_by")),
        "raised": (meta.get("created_at") or "")[:10],
        "due": (i.get("due_date") or "")[:10],
        "closed": (i.get("closed_at") or "")[:10],
    }


def _day(value: str, what: str) -> str:
    try:
        return datetime.fromisoformat(value.strip()).strftime("%Y%m%d")
    except ValueError:
        raise ToolError(f"{what} should be a date like 2026-11-01, not {value!r}.") from None


def register(server: MCPServer, gw: Gateway) -> None:
    aconex = gw.aconex

    async def areas(project: str) -> tuple[list, list]:
        data = await aconex.get_field_json(f"/projects/{project}/areas")
        tree = data.get("areas") or []
        return tree, flatten_areas(tree)

    async def scope(project: str, area: str) -> list:
        """The area ids to search: the named area, or every top-level area."""
        tree, flat = await areas(project)
        if not area.strip():
            return [str(n.get("id")) for n in tree]
        wanted = area.strip().casefold()
        hits = [a for a in flat if a["area_id"] == area.strip() or wanted in a["path"].casefold()]
        if not hits:
            raise ToolError(f"No area matching {area!r}. Use field_areas to see the project's areas.")
        hits.sort(key=lambda a: a["depth"])  # the shallowest match covers the deeper ones
        return [hits[0]["area_id"]]

    async def type_ids(project: str, names: str) -> str:
        if not names.strip():
            return ""
        data = await aconex.get_field_json(f"/projects/{project}/issue_types")
        known = {t.get("name", "").casefold(): str(t.get("id")) for t in data.get("issue_types") or []}
        ids = []
        for name in (n.strip() for n in names.split(",") if n.strip()):
            if name.casefold() not in known:
                raise ToolError(f"No issue type called {name!r}. This project's types: "
                                + ", ".join(sorted(t.get("name", "") for t in data.get("issue_types") or [])) + ".")
            ids.append(known[name.casefold()])
        return ",".join(ids)

    def filters(status: str, types: str, raised_from: str, raised_to: str) -> dict:
        params: dict = {"include_child_areas": "true"}
        if status.strip():
            wanted = [s.strip() for s in status.split(",") if s.strip()]
            fixed = [next((k for k in STATUSES if k.casefold() == w.replace(" ", "").casefold()), None) for w in wanted]
            if None in fixed:
                raise ToolError(f"Status must be one of: {', '.join(STATUSES)}.")
            params["status"] = ",".join(fixed)
        if types:
            params["issue_type"] = types
        if raised_from or raised_to:
            params["captured_on"] = (_day(raised_from, "raised_from") if raised_from else "") + "-" + \
                                    (_day(raised_to, "raised_to") if raised_to else "")
        return params

    async def issues(project: str, area_ids: list, params: dict, cap: int) -> tuple[list, int]:
        found, total = [], 0
        for area_id in area_ids:
            page = 1
            while len(found) < cap:
                data = await aconex.get_field_json(
                    f"/projects/{project}/areas/{seg(area_id, 'area ID')}/issues",
                    {**params, "page_size": PAGE, "page_number": page, "sort_by": "issue_number", "sort_order": "desc"})
                found += [parse_issue(i) for i in data.get("issues") or []]
                if page == 1:
                    total += int(data.get("total_results") or 0)
                if page >= int(data.get("total_pages") or 1):
                    break
                page += 1
        return found[:cap], total

    @read_tool(server, gw,
               "Aconex Field: the project's areas (buildings, levels, units) as a list with full paths. "
               "Use an area's name or ID to narrow the other Field items.")
    async def field_areas(project_id: str) -> dict:
        _, flat = await areas(seg(project_id, "project ID"))
        return {"areas": [{k: a[k] for k in ("area_id", "path")} for a in flat[:500]], "count": len(flat)}

    @read_tool(server, gw,
               "Aconex Field: search issues (defects, observations and other site issues). Filters: "
               "status (Open, InDispute, ReadyToInspect, WorkDone, Closed; comma-separate several), "
               "issue_type (this project's type names, e.g. Defect), company (the company it's assigned to, "
               "e.g. the trade; part of a name), area (an area name or path, e.g. 'Level 2'), raised_from and "
               "raised_to (dates). Newest first. Each issue shows its number, type, status, description, "
               "area, location, assigned company, who raised it and the dates.")
    async def search_field_issues(project_id: str, status: str = "", issue_type: str = "", company: str = "",
                                  area: str = "", raised_from: str = "", raised_to: str = "",
                                  limit: int = 50) -> dict:
        project = seg(project_id, "project ID")
        limit = clamp(limit, 1, 500)
        params = filters(status, await type_ids(project, issue_type), raised_from, raised_to)
        cap = limit if not company.strip() else MAX_COUNTED
        found, total = await issues(project, await scope(project, area), params, cap)
        if company.strip():
            found = [i for i in found if company.strip().casefold() in i["company"].casefold()]
        result = {"issues": found[:limit], "matching": len(found) if company.strip() else total}
        if not found:
            result["tip"] = "Nothing matched. Try fewer filters, or field_issue_counts to see what's there."
        return result

    @read_tool(server, gw,
               "Aconex Field: count issues by company (the trade it's assigned to), type, status, area or "
               "raised_by, optionally crossed with a second grouping (then_by), e.g. by='company', "
               "then_by='type' for the most common defect types per trade. Same filters as "
               "search_field_issues. Counts up to 5,000 issues and says if there are more.")
    async def field_issue_counts(project_id: str, by: GROUPS = "company", then_by: GROUPS | None = None,
                                 status: str = "", issue_type: str = "", area: str = "",
                                 raised_from: str = "", raised_to: str = "") -> dict:
        project = seg(project_id, "project ID")
        params = filters(status, await type_ids(project, issue_type), raised_from, raised_to)
        found, total = await issues(project, await scope(project, area), params, MAX_COUNTED)
        key = {"company": "company", "type": "type", "status": "status", "area": "area", "raised_by": "raised_by"}
        if then_by:
            table: dict = defaultdict(Counter)
            for i in found:
                table[i[key[by]] or "(none)"][i[key[then_by]] or "(none)"] += 1
            counts = [{by: k, "total": sum(c.values()),
                       then_by: [{"name": n, "count": v} for n, v in c.most_common()]}
                      for k, c in sorted(table.items(), key=lambda kv: -sum(kv[1].values()))]
        else:
            c = Counter(i[key[by]] or "(none)" for i in found)
            counts = [{by: k, "count": v} for k, v in c.most_common()]
        result = {"counted": len(found), "counts": counts}
        if total > len(found):
            result["not_counted"] = f"{total - len(found)} more issues weren't counted: narrow with filters."
        return result

    @read_tool(server, gw,
               "Aconex Field: one issue in full, by its number (or issue_id and area_id from a search): "
               "description, type, status, area and location, assigned company and person, who raised and "
               "closed it, dates, custom fields and attachment names.")
    async def field_issue_details(project_id: str, number: str = "", issue_id: str = "",
                                  area_id: str = "") -> dict:
        project = seg(project_id, "project ID")
        if not (issue_id and area_id):
            if not number.strip():
                raise ToolError("Give the issue number, or issue_id and area_id from a search.")
            tree, _ = await areas(project)
            for root in tree:
                data = await aconex.get_field_json(
                    f"/projects/{project}/areas/{seg(str(root.get('id')), 'area ID')}/issues",
                    {"include_child_areas": "true", "issue_number": number.strip(), "page_size": 5})
                hit = (data.get("issues") or [None])[0]
                if hit:
                    issue_id, area_id = hit.get("issue_id", ""), str((hit.get("area") or {}).get("id", ""))
                    break
            else:
                raise ToolError(f"No issue number {number} on this project.")
        i = await aconex.get_field_json(
            f"/projects/{project}/areas/{seg(area_id, 'area ID')}/issues/{seg(issue_id, 'issue ID')}")
        row = parse_issue(i)
        row.update({
            "assigned_person": _person((i.get("assigned_to") or {}).get("user")),
            "assigned_by": _org(i.get("assigned_by")),
            "closed_by": _person(i.get("closed_by")),
            "custom_fields": [{"field": c.get("family_id") or c.get("id"), "value": c.get("value")}
                              for c in i.get("custom_fields") or []],
            "attachments": [a.get("file_name") or a.get("url", "").rsplit("/", 1)[-1]
                            for a in i.get("attachments") or []],
            "listed_in": [f"{x.get('record_type', '')} {x.get('number', '')} {x.get('title', '')}".strip()
                          for x in i.get("issue_listings") or []],
        })
        return row
