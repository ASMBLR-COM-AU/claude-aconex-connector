"""Builder reports: read-only checks across a whole project.

subbies_on_old_drawings: for every drawing the company has transmitted out,
did each receiving company get the CURRENT revision? Answers "which subbies
are working off old drawings?" from the builder's side, where the builder's
own register is the source of truth.

Only reads: the register and the company's sent mail.
"""

from __future__ import annotations

from collections import defaultdict

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from gateway.aconex import AconexError, seg
from gateway.aconex.parse import page_info, text
from gateway.tools import Gateway, clamp, read_tool
from gateway.tools.mail import ACCEPT_MAIL, parse_attachment, parse_mail_list
from gateway.tools.register import RETURN_FIELDS, parse_documents

MAX_REGISTER_PAGES = 40       # 500 a page: up to 20,000 current documents
MAX_LISTED = 200              # rows of detail returned; the summary covers everything


def _org(el) -> str:
    return (text(el, "OrganizationName") or text(el, "TradingName") or "").strip()


def outdated_holdings(current: dict, sent: list) -> list:
    """One row per (company, document) the company was sent at some revision but
    never at the current one. `current`: {doc number: register row}; `sent`:
    [{"company", "doc", "rev", "mail", "date"}]. A transmittal can carry old
    revisions alongside the current one (bulk issues often include history), so
    a company is up to date if it was EVER sent the current revision."""
    got: dict = defaultdict(lambda: {"revs": set(), "mails": [], "last": ""})
    for s in sent:
        g = got[(s["company"], s["doc"])]
        g["revs"].add(s["rev"])
        g["mails"].append((s["date"], s["mail"]))
        g["last"] = max(g["last"], s["date"])
    rows = []
    for (company, doc), g in got.items():
        cur = current.get(doc)
        status = "current" if cur and cur["revision"] in g["revs"] else ("out of date" if cur else "not in register")
        rows.append({
            "company": company, "document": doc, "title": (cur or {}).get("title", ""),
            "discipline": (cur or {}).get("discipline", ""), "current_revision": (cur or {}).get("revision", ""),
            "revisions_sent": sorted(g["revs"]), "last_sent": g["last"][:10],
            "last_sent_in": max(g["mails"])[1], "status": status,
        })
    return rows


def register(server: MCPServer, gw: Gateway) -> None:
    aconex = gw.aconex

    @read_tool(server, gw,
               "Builder check: which companies (subbies, consultants) are working off OLD drawings? Compares "
               "every drawing your company has transmitted out with the current revision in your register, "
               "and lists each company that was sent a drawing but never its current revision. Covers "
               "drawings your company sent; drawings others never sent you can't be checked from here. "
               "Optional filters: discipline (e.g. Structural) and company (part of a name). Scans your "
               "most recent transmittals (up to max_transmittals, default 200) and says how many it "
               "checked. Takes up to a few minutes on a big project.")
    async def subbies_on_old_drawings(project_id: str, discipline: str = "", company: str = "",
                                      max_transmittals: int = 200) -> dict:
        project = seg(project_id, "project ID")
        max_transmittals = clamp(max_transmittals, 1, 1000)

        current: dict = {}
        page = 1
        while page <= MAX_REGISTER_PAGES:
            root = await aconex.get_xml(f"/projects/{project}/register", {
                "return_fields": RETURN_FIELDS, "search_type": "PAGED", "page_size": 500,
                "page_number": page, "sort_field": "docno", "sort_direction": "asc"})
            for d in parse_documents(root):
                if d["number"]:
                    current[d["number"]] = d
            if page >= int(page_info(root).get("pages") or 1):
                break
            page += 1

        mails: list = []
        total_sent = 0
        page = 1
        while len(mails) < max_transmittals:
            root = await aconex.get_xml(f"/projects/{project}/mail", {
                "mail_box": "Sentbox", "return_fields": "docno,subject,sentdate,corrtypeid",
                "search_type": "PAGED", "page_size": 100, "page_number": page}, ACCEPT_MAIL)
            info = page_info(root)
            total_sent = int(info.get("total") or 0)
            mails += parse_mail_list(root, "sent", project)
            if page >= int(info.get("pages") or 1):
                break
            page += 1
        mails = sorted(mails, key=lambda m: m.get("sent", ""), reverse=True)[:max_transmittals]

        sent, skipped, transmittals = [], [], 0
        for m in mails:
            try:
                root = await aconex.get_xml(f"/projects/{project}/mail/{seg(m['mail_id'], 'mail ID')}",
                                            accept=ACCEPT_MAIL)
            except AconexError as err:
                skipped.append(f"{m.get('number') or m['mail_id']}: {err}")
                continue
            docs = [parse_attachment(a) for a in root.findall(".//Attachments/*")]
            docs = [d for d in docs if d["number"]]
            if not docs:
                continue
            transmittals += 1
            ours = _org(root.find(".//FromUserDetails"))
            to = {_org(r) for parent in ("ToUsers", "CcUsers") for r in root.findall(f".//{parent}/*")}
            for org in to - {ours, ""}:
                for d in docs:
                    sent.append({"company": org, "doc": d["number"], "rev": d["revision"],
                                 "mail": text(root, ".//MailNo"), "date": text(root, ".//SentDate")})

        rows = outdated_holdings(current, sent)
        if discipline.strip():
            rows = [r for r in rows if discipline.strip().casefold() in r["discipline"].casefold()]
        if company.strip():
            rows = [r for r in rows if company.strip().casefold() in r["company"].casefold()]

        summary: dict = defaultdict(lambda: {"current": 0, "out_of_date": 0})
        for r in rows:
            if r["status"] in ("current", "out of date"):
                summary[(r["company"], r["discipline"] or "(none)")]["out_of_date" if r["status"] == "out of date" else "current"] += 1
        old = sorted((r for r in rows if r["status"] == "out of date"),
                     key=lambda r: (r["company"], r["discipline"], r["document"]))
        result = {
            "checked": {"register_documents": len(current), "sent_mails_total": total_sent,
                        "sent_mails_checked": len(mails), "transmittals_with_drawings": transmittals},
            "companies_on_old_drawings": sorted({r["company"] for r in old}),
            "summary": [{"company": c, "discipline": d, **v} for (c, d), v in sorted(summary.items())],
            "out_of_date": old[:MAX_LISTED],
            "how_to_read": "out_of_date = the company was sent this drawing, but never its current "
                           "revision. Only drawings your company transmitted are checked.",
        }
        if len(old) > MAX_LISTED:
            result["more"] = f"{len(old) - MAX_LISTED} more out-of-date rows: filter by company or discipline."
        if len(mails) < total_sent:
            result["not_checked"] = (f"Only the {len(mails)} most recent of {total_sent} sent mails were checked; "
                                     "raise max_transmittals to check more.")
        if skipped:
            result["skipped"] = skipped[:20]
        if not sent:
            result["note"] = "No transmittals with drawings were found in your company's sent mail."
        return result
