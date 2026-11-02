"""Stage 2 tools: projects, people and companies. All read-only."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from gateway.aconex import seg
from gateway.aconex.parse import first, flatten, text
from gateway.tools import Gateway, clamp, read_tool


def register(server: MCPServer, gw: Gateway) -> None:
    aconex = gw.aconex

    @read_tool(server, gw, "List every Aconex project the gateway's account can see, with each "
                       "project's ID, name, code and whether IT has approved it for the gateway. "
                       "Only approved projects can be searched or opened. Start here to find a "
                       "project's ID.")
    async def list_projects() -> dict:
        root = await aconex.get_xml("/projects")
        projects = [
            {
                "project_id": text(p, "ProjectId"),
                "name": text(p, "ProjectName"),
                "code": first(p, "ProjectCode", "ProjectShortName"),
                "approved": gw.policy.project_allowed(text(p, "ProjectId")),
            }
            for p in root.iter("Project")
            if text(p, "ProjectId")
        ]
        projects.sort(key=lambda p: (not p["approved"], p["name"].casefold()))
        result: dict = {"projects": projects}
        if not any(p["approved"] for p in projects):
            result["note"] = "No projects are approved yet: ask IT to approve one."
        return result

    @read_tool(server, gw, "Search the people on one project by name, company or job title. "
                       "Matches any part of the text. Leave all filters empty to list everyone.")
    async def search_project_directory(project_id: str, name: str = "", company: str = "",
                                       job_title: str = "", limit: int = 50) -> dict:
        # The live directory takes no search parameters (UNEXPECTED_PARAMETER),
        # so it is fetched whole and filtered here.
        root = await aconex.get_xml(f"/projects/{seg(project_id, 'project ID')}/directory")
        people = []
        for d in root.iter("Directory"):
            row = {
                "user_id": text(d, "UserId"),
                "name": text(d, "UserName"),
                "company": first(d, "OrganizationName", "TradingName"),
                "job_title": text(d, "JobTitle"),
                "email": text(d, "Email"),
            }
            if not row["user_id"]:
                continue
            if all(want.casefold() in row[field].casefold()
                   for field, want in (("name", name), ("company", company),
                                       ("job_title", job_title)) if want):
                people.append(row)
        limit = clamp(limit, 1, 200)
        return {"people": people[:limit], "matched": len(people)}

    @read_tool(server, gw, "One person's contact and company details. Give project_id to look them "
                       "up on that project; leave it empty to use the Aconex-wide directory.")
    async def get_person(user_id: str, project_id: str = "") -> dict:
        uid = seg(user_id, "user ID")
        path = (f"/projects/{seg(project_id, 'project ID')}/users/{uid}" if project_id
                else f"/users/{uid}")
        return flatten(await aconex.get_xml(path))

    @read_tool(server, gw, "Which Aconex account the gateway is signed in as.")
    async def gateway_account() -> dict:
        return flatten(await aconex.get_xml("/user"))

    @read_tool(server, gw, "A project's mailing groups, with their members.")
    async def list_mailing_groups(project_id: str) -> dict:
        data = await aconex.get_json(f"/mailinggroups/{seg(project_id, 'project ID')}")
        return {"groups": data}

    @read_tool(server, gw, "Search people at any company across Aconex (not just one project). "
                       "Give at least one filter. Names match from the start; company, "
                       "job title and division match any part.")
    async def search_aconex_directory(company: str = "", given_name: str = "",
                                      family_name: str = "", job_title: str = "",
                                      division: str = "", email: str = "",
                                      limit: int = 50) -> dict:
        params = {key: value.strip() for key, value in (
            ("org_name", company), ("given_name", given_name), ("family_name", family_name),
            ("job_title", job_title), ("division", division), ("email", email),
        ) if value.strip()}
        if not params:
            raise ToolError("Give at least one filter, such as a company or a name.")
        root = await aconex.get_xml("/directory", params)
        people = [flatten(el) for el in root.iter() if el is not root and el.find("UserId") is not None]
        limit = clamp(limit, 1, 200)
        return {"people": people[:limit], "matched": len(people)}

    @read_tool(server, gw, "A company's details in Aconex, by its organisation ID.")
    async def get_company(organization_id: str) -> dict:
        return flatten(await aconex.get_xml(f"/organizations/{seg(organization_id, 'organisation ID')}"))

    @read_tool(server, gw, "The custom fields set up on a project (label, type, options, on or off).")
    async def list_project_fields(project_id: str) -> dict:
        root = await aconex.get_xml(f"/projects/{seg(project_id, 'project ID')}/projectField")
        return {"fields": [flatten(f) for f in root][:200]}
