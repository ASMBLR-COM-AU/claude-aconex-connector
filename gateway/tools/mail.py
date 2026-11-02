"""Stage 7 tools: project mail. All read-only.

Scope (decided 2 Nov 2026): the whole project, not just the signed-in
person's mail. Found live: the gateway account's mailboxes are company-wide,
so "received" is all mail sent to the company on the project and "sent" is
all mail the company sent. "All" combines the two. Confidential mail stays
hidden (the account has no permission to see it).

Search fields confirmed against the live API (2 Nov 2026): fromtradingname
(sender's company, partial match), fromuserfullname (sender, partial),
touserfullname (recipient), subject, docno (mail number), plain words,
sentdate as [YYYYMMDD TO YYYYMMDD], and corrtypeid / tostatusid /
reasonforissueid by ID (names are looked up in the mail search schema).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from gateway.aconex import AconexError, seg
from gateway.aconex.parse import first, html_to_text, lucene_phrase, page_info, person, text
from gateway.guard import mail_link
from gateway.tools import Gateway, clamp, current_person, parse_when, read_tool
from gateway.tools.files import LINK_TTL_S, FileLinks
from gateway.tools.register import leaf_rows, page_size, parse_saved_searches

ACCEPT_MAIL = "application/vnd.aconex.mail.v2+xml"
RETURN_FIELDS = "docno,subject,sentdate,corrtypeid,fromUserDetails"
BOXES = {"received": ("Inbox",), "sent": ("Sentbox",), "all": ("Inbox", "Sentbox")}
MAX_BODY_CHARS = 20_000
ATTACHMENTS_PER_PAGE = 50  # live: one transmittal had thousands of attachments
ATTACHMENT_KINDS = {
    "RegisteredDocumentAttachment": "register document",
    "LocalFileAttachment": "file",
    "FileAttachment": "file",
    "MailAttachment": "mail",
}
# Lucene characters that would change a plain word into syntax.
_LUCENE_SPECIAL = re.compile(r'([+\-!(){}\[\]^"~*?:\\/&|])')


def plain_word(word: str) -> str:
    return _LUCENE_SPECIAL.sub(r"\\\1", word)


def day_stamp(moment: datetime) -> str:
    return moment.strftime("%Y%m%d")  # live: sentdate ranges only match YYYYMMDD


def parse_mail_list(root, box: str) -> list:
    mails = []
    for m in root.findall(".//SearchResults/Mail"):
        mail_id = (m.get("MailId") or text(m, "MailId")).strip()
        if mail_id:
            mails.append({
                "mail_id": mail_id,
                "number": text(m, "MailNo"),
                "sent": text(m, "SentDate"),
                "type": first(m, "CorrespondenceType", "CorrespondenceTypeId"),
                "from": person(m.find("FromUserDetails")),
                "subject": text(m, "Subject"),
                "box": box,
                "open_in_aconex": mail_link(mail_id),
            })
    return mails


def parse_recipients(root) -> dict:
    """Every recipient is under <ToUsers>, tagged TO, CC or BCC (live)."""
    out: dict = {"TO": [], "CC": [], "BCC": []}
    for parent, default in (("ToUsers", "TO"), ("CcUsers", "CC"), ("BccUsers", "BCC")):
        for r in root.findall(f".//{parent}/*"):
            kind = text(r, "DistributionType").upper() or default
            name = person(r)
            if name:
                out.setdefault(kind, []).append({"name": name, "user_id": text(r, "UserId")})
    return out


def parse_attachment(a) -> dict:
    return {
        "attachment_id": (a.get("attachmentId") or a.get("AttachmentId") or text(a, "AttachmentId")).strip(),
        "kind": ATTACHMENT_KINDS.get(a.tag, a.tag),
        "number": text(a, "DocumentNo"),
        "revision": text(a, "Revision"),
        "title": text(a, "Title"),
        "file": text(a, "FileName"),
        "size_bytes": text(a, "FileSize"),
        "document_id": text(a, "DocumentId"),
    }


def _own(root, *names: str) -> str:
    """A field of the mail itself, not of something inside it (live: a
    `.//Status` search picked up an attachment's document status)."""
    for el in (root, root.find("Mail")):
        if el is not None:
            value = first(el, *names)
            if value:
                return value
    return ""


def parse_mail(root, mail_id: str, attachments_page: int = 1) -> dict:
    body = root.find(".//MailData")
    body_text = html_to_text("".join(body.itertext())) if body is not None else ""
    recipients = parse_recipients(root)
    mail = {
        "mail_id": mail_id,
        "open_in_aconex": mail_link(mail_id),
        "number": text(root, ".//MailNo"),
        "type": text(root, ".//CorrespondenceType"),
        "subject": text(root, ".//Subject"),
        "sent": text(root, ".//SentDate"),
        "from": person(root.find(".//FromUserDetails")),
        "from_user_id": text(root, ".//FromUserDetails/UserId"),
        "to": recipients["TO"],
        "cc": recipients["CC"],
        "bcc": recipients["BCC"],
        "reason": text(root, ".//ReasonForIssue"),
        "status": _own(root, "MailStatus", "Status"),
        "thread_id": text(root, ".//ThreadId"),
        "body": body_text[:MAX_BODY_CHARS],
    }
    reply_to = _own(root, "InRefToMailNo")
    if reply_to and reply_to != mail["number"]:
        mail["in_reply_to"] = reply_to
    attachments = root.findall(".//Attachments/*")
    start = (max(1, attachments_page) - 1) * ATTACHMENTS_PER_PAGE
    mail["attachment_count"] = len(attachments)
    mail["attachments"] = [parse_attachment(a) for a in attachments[start:start + ATTACHMENTS_PER_PAGE]]
    if len(attachments) > start + ATTACHMENTS_PER_PAGE:
        mail["more_attachments"] = (f"Showing {start + 1}-{start + ATTACHMENTS_PER_PAGE} of "
                                    f"{len(attachments)}: ask for attachments_page "
                                    f"{max(1, attachments_page) + 1} for the next {ATTACHMENTS_PER_PAGE}.")
    if len(body_text) > MAX_BODY_CHARS:
        mail["body_cut_short"] = f"{len(body_text) - MAX_BODY_CHARS} more characters not shown"
    return mail


def register(server: MCPServer, gw: Gateway, links: FileLinks) -> None:
    aconex = gw.aconex
    schemas: dict[str, object] = {}

    async def schema(project: str):
        if project not in schemas:
            schemas[project] = await aconex.get_xml(f"/projects/{project}/mail/schema/search",
                                                    accept=ACCEPT_MAIL)
        return schemas[project]

    async def value_id(project: str, identifier: str, label: str, wanted: str) -> str:
        if wanted.strip().isdigit():
            return wanted.strip()
        values = {}
        for field in (await schema(project)).iter():
            if text(field, "Identifier") == identifier:
                values.update({text(v, "Value").casefold(): text(v, "Id")
                               for v in field.iter("SchemaValue") if text(v, "Value")})
        found = values.get(wanted.strip().casefold())
        if not found:
            raise ToolError(f"No {label} called {wanted!r} on this project. Its {label}s: "
                            + (", ".join(sorted(values)) or "none listed") + ".")
        return found

    async def find_mail_id(project: str, number: str) -> str:
        for box in BOXES["all"]:
            root = await aconex.get_xml(f"/projects/{project}/mail", {
                "mail_box": box, "search_query": f'docno:"{lucene_phrase(number)}"',
                "return_fields": RETURN_FIELDS, "search_type": "PAGED", "page_size": 25,
                "page_number": 1}, ACCEPT_MAIL)
            for mail in parse_mail_list(root, box):
                if mail["number"].casefold() == number.strip().casefold():
                    return mail["mail_id"]
        raise ToolError(f"No mail numbered {number} on this project.")

    async def mail_id_from(project: str, mail_id: str, mail_number: str) -> str:
        if bool(mail_id.strip()) == bool(mail_number.strip()):
            raise ToolError("Give either mail_number (e.g. LSGP-TRANSMIT-000143) or mail_id.")
        return seg(mail_id, "mail ID") if mail_id.strip() else await find_mail_id(project, mail_number)

    @read_tool(server, gw,
               "Search a project's mail, like Aconex's mail search. Covers all mail the company "
               "received (box 'received') and sent ('sent'), or both ('all', the default), newest "
               "first. Narrow it down the way people do in Aconex: from_company (the sender's "
               "company, part of the name is enough, e.g. 'LVL'), from_person (the sender, e.g. a "
               "surname), to_person (a recipient), mail_type (e.g. Transmittal, RFI), status "
               "(e.g. Outstanding), mail_number, since/until (dates), and words (free text, like "
               "the main search bar). To trace the history of an issue, search its key words "
               "with box 'all' and read the results oldest to newest.")
    async def search_mail(project_id: str, box: Literal["all", "received", "sent"] = "all",
                          words: str = "", from_company: str = "", from_person: str = "",
                          to_person: str = "", mail_type: str = "", status: str = "",
                          mail_number: str = "", since: str = "", until: str = "",
                          limit: int = 25, page: int = 1) -> dict:
        project = seg(project_id, "project ID")
        clauses = [plain_word(w) for w in words.split()]
        for field, value in (("fromtradingname", from_company), ("fromuserfullname", from_person),
                             ("touserfullname", to_person), ("docno", mail_number)):
            if value.strip():
                clauses.append(f'{field}:"{lucene_phrase(value.strip())}"')
        if mail_type:
            clauses.append(f'corrtypeid:"{await value_id(project, "corrtypeid", "mail type", mail_type)}"')
        if status:
            clauses.append(f'tostatusid:"{await value_id(project, "tostatusid", "status", status)}"')
        if since or until:
            start = day_stamp(parse_when(since, "since")) if since else "19000101"
            end = day_stamp(parse_when(until, "until")) if until else day_stamp(datetime.now(timezone.utc))
            clauses.append(f"sentdate:[{start} TO {end}]")

        limit = clamp(limit, 1, 100)
        mails, totals = [], {}
        for aconex_box in BOXES[box]:
            params = {"mail_box": aconex_box, "return_fields": RETURN_FIELDS, "search_type": "PAGED",
                      "page_size": page_size(limit), "page_number": clamp(page, 1, 10_000),
                      "sort_field": "sentdate", "sort_direction": "DESC"}
            if clauses:
                params["search_query"] = " AND ".join(clauses)
            root = await aconex.get_xml(f"/projects/{project}/mail", params, ACCEPT_MAIL)
            label = "received" if aconex_box == "Inbox" else "sent"
            totals[label] = page_info(root).get("total", 0)
            mails += parse_mail_list(root, label)
        # The company's own mail can sit in both boxes; show each mail once.
        merged: dict[str, dict] = {}
        for mail in mails:
            if mail["mail_id"] in merged:
                merged[mail["mail_id"]]["box"] = "received and sent"
            else:
                merged[mail["mail_id"]] = mail
        rows = sorted(merged.values(), key=lambda m: m["sent"], reverse=True)[:limit]
        result: dict = {"mails": rows, "total_matching": totals}
        if not rows:
            result["tips"] = [
                "Try fewer words, or part of a name (from_company 'LVL' rather than the full name).",
                "Mail types and statuses use this project's own names: see mail_fields.",
                "Try box 'all' if you searched only received or sent mail.",
            ]
        return result

    @read_tool(server, gw,
               "Read one mail in full: sender, To/Cc/Bcc, type, subject, date, status, the message "
               "text, its attachments (with attachment IDs for get_mail_attachment), 50 "
               "attachments at a time "
               "(attachments_page for more). Give mail_number (e.g. LSGP-TRANSMIT-000143) or a "
               "mail_id from search_mail. A transmittal with thousands of attachments can take "
               "a minute to load. Give the person the open_in_aconex link so they can open it.")
    async def read_mail(project_id: str, mail_number: str = "", mail_id: str = "",
                        attachments_page: int = 1) -> dict:
        project = seg(project_id, "project ID")
        found = await mail_id_from(project, mail_id, mail_number)
        root = await aconex.get_xml(f"/projects/{project}/mail/{found}", accept=ACCEPT_MAIL)
        return parse_mail(root, found, attachments_page)

    @read_tool(server, gw,
               "The conversation a mail belongs to: the chain of replies and forwards, so you can "
               "follow an issue from first mail to last. Give mail_number or mail_id.")
    async def mail_thread(project_id: str, mail_number: str = "", mail_id: str = "") -> dict:
        project = seg(project_id, "project ID")
        found = await mail_id_from(project, mail_id, mail_number)
        # Ask for the thread by the mail's own ID first: reading the whole mail
        # to find its thread ID can take a minute on a big transmittal (live).
        try:
            root = await aconex.get_xml(f"/projects/{project}/mail/{found}/thread", accept=ACCEPT_MAIL)
            thread_id = found
        except AconexError as err:
            if "HTTP 404" not in str(err):
                raise
            detail = await aconex.get_xml(f"/projects/{project}/mail/{found}", accept=ACCEPT_MAIL)
            thread_id = seg(text(detail, ".//ThreadId") or found, "thread ID")
            root = await aconex.get_xml(f"/projects/{project}/mail/{thread_id}/thread", accept=ACCEPT_MAIL)
        return {"thread_id": thread_id, "mails": leaf_rows(root, 100)}

    @read_tool(server, gw,
               "A project's mail types, statuses and reasons for issue, and which mail fields can be "
               "searched. Use the names here with search_mail's mail_type and status.")
    async def mail_fields(project_id: str) -> dict:
        root = await schema(seg(project_id, "project ID"))
        fields, lists = [], {}
        for field in root.iter():
            identifier = text(field, "Identifier")
            if not identifier:
                continue
            fields.append(first(field, "Name", "FieldName") or identifier)
            values = [text(v, "Value") for v in field.iter("SchemaValue") if text(v, "Value")]
            label = {"corrtypeid": "mail_types", "tostatusid": "statuses",
                     "reasonforissueid": "reasons_for_issue"}.get(identifier)
            if label and values:
                lists[label] = values
        return {**lists, "searchable_fields": fields}

    @read_tool(server, gw, "The saved mail searches people have set up on a project, with their filters.")
    async def saved_mail_searches(project_id: str) -> dict:
        root = await aconex.get_xml(f"/projects/{seg(project_id, 'project ID')}/mail/savedSearches",
                                    accept=ACCEPT_MAIL)
        return {"saved_searches": parse_saved_searches(root)[:100]}

    @read_tool(server, gw,
               "Get the actual file attached to a mail: any attachment, including attached drawings "
               "and register documents (some come from another company's register and have no "
               "document_id). Use the attachment_id from read_mail. marked_up=true gives the "
               "version with markups, as a PDF. Returns a "
               "download link valid for 15 minutes: download it into your workspace and give the "
               "person the file in the chat; if you can't reach it, give them the link.")
    async def get_mail_attachment(project_id: str, attachment_id: str, mail_number: str = "",
                                  mail_id: str = "", marked_up: bool = False) -> dict:
        project = seg(project_id, "project ID")
        found = await mail_id_from(project, mail_id, mail_number)
        path = f"/projects/{project}/mail/{found}/attachments/{seg(attachment_id, 'attachment ID')}"
        if marked_up:
            path += "/markedup"
        url = links.create(current_person(), project, path, "")
        return {"download_url": url, "expires_in_minutes": LINK_TTL_S // 60,
                "next_step": "Download download_url into your workspace and give the person the "
                             "file in the chat. If you can't reach it, give them the link."}
