"""Stage 6: the real file (the PDF, or a DWG on multi-file documents) from
Aconex to Claude, on command.

Why a download link (tested 2 Nov 2026, see docs/stages/06-files.md):
claude.ai refuses a PDF inside a tool's reply ("application/pdf not
supported"), and pictures of pages lose too much (drawing notes are often
drawn as lines, not stored as text). A short-lived link lets Claude's own
workspace download the original file, show it in the chat and open it. That
works in claude.ai (once the gateway's address is on the organisation's
allowed domains, see the runbook), Claude Code and Cowork. Anywhere else, the
person can click the link.

Links: each is random (256 bits), stored as a hash, tied to one file, works
ONCE and for at most 10 minutes, and re-checks the off switch, the approved
project and the approved person when used. A link is a "bearer" link: whoever
holds it in those minutes can download that one file once, so it's handed only
to Claude's own workspace, and every download is in the audit log.
"""

from __future__ import annotations

import hashlib
import mimetypes
import os
import secrets
import sqlite3
import threading
import time
from urllib.parse import quote

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response

from gateway.aconex import AconexError, seg
from gateway.aconex.parse import lucene_phrase
from gateway.guard import public_url
from gateway.tools import Gateway, current_person, read_tool
from gateway.tools.register import RETURN_FIELDS, parse_documents

LINK_TTL_S = 10 * 60
LINK_MAX_USES = 1


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def document_path(project: str, document: str) -> str:
    return f"/projects/{project}/register/{document}"


def mime_type(name: str) -> str:
    return mimetypes.guess_type(name)[0] or "application/octet-stream"


class FileLinks:
    def __init__(self, gw: Gateway, path: str):
        self.gw = gw
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock, self._db:
            self._db.execute("""CREATE TABLE IF NOT EXISTS file_links (
                hash TEXT PRIMARY KEY, person TEXT NOT NULL, project TEXT NOT NULL,
                document TEXT NOT NULL, file_name TEXT NOT NULL,
                expires REAL NOT NULL, uses INTEGER NOT NULL DEFAULT 0)""")

    def _run(self, sql: str, args: tuple = ()) -> list:
        with self._lock, self._db:
            return self._db.execute(sql, args).fetchall()

    def create(self, person: str, project: str, document: str, file_name: str) -> str:
        """`document` is a register document ID, or the full Aconex path of
        another file (e.g. a mail attachment), starting with "/"."""
        self._run("DELETE FROM file_links WHERE expires < ?", (time.time(),))
        token = secrets.token_urlsafe(32)
        self._run("INSERT INTO file_links VALUES (?, ?, ?, ?, ?, ?, 0)",
                  (_hash(token), person, project, document, file_name, time.time() + LINK_TTL_S))
        return f"{public_url()}/files/{token}"

    async def serve(self, request: Request) -> Response:
        """GET /files/{token}: Claude's workspace (or the person) downloads the file."""
        token = request.path_params.get("token", "")
        if request.method == "HEAD":  # a link checker: answer without using up the link
            return Response(status_code=200, headers={"Cache-Control": "no-store"})
        # Claim the link in one step, so two downloads at the same moment can't
        # both get through.
        with self._lock, self._db:
            claimed = self._db.execute(
                "UPDATE file_links SET uses = uses + 1 WHERE hash = ? AND uses < ? AND expires >= ?",
                (_hash(token), LINK_MAX_USES, time.time())).rowcount
            rows = self._db.execute("SELECT person, project, document, file_name FROM file_links "
                                    "WHERE hash = ?", (_hash(token),)).fetchall()
        if not claimed or not rows:
            return PlainTextResponse("This download link has been used or has expired. "
                                     "Ask Claude for a new one.", 410)
        person, project, document, file_name = rows[0]

        def audit(outcome: str, detail: str = "") -> None:
            self.gw.audit.record(person=person, tool="file downloaded", project=project,
                                 arguments={"document_id": document, "file_name": file_name},
                                 outcome=outcome, detail=detail)

        policy = self.gw.policy
        if policy.switched_off or not policy.project_allowed(project) or (
                "@" in person and not policy.person_allowed(person)):
            audit("blocked", "switched off, project or person no longer approved")
            return PlainTextResponse("This download isn't allowed any more.", 403)
        try:
            path = document if document.startswith("/") else document_path(project, document)
            content, name = await self.gw.aconex.get_file(
                path, {"fileName": file_name} if file_name else None)
        except AconexError as err:
            audit("error", str(err))
            return PlainTextResponse(f"Couldn't get the file from Aconex: {err}", 502)
        audit("ok")
        return Response(content, media_type=mime_type(name), headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}",
            "Cache-Control": "no-store",
        })


def register(server: MCPServer, gw: Gateway) -> FileLinks:
    links = FileLinks(gw, os.environ.get("AUDIT_DB", "audit.db"))

    async def find_document(project: str, number: str, revision: str) -> dict:
        """The register row for a document number: the current revision, or
        the named one."""
        params = {
            "search_query": f'docno:"{lucene_phrase(number)}"',
            "return_fields": RETURN_FIELDS,
            "search_type": "PAGED", "page_size": 100, "page_number": 1,
            "sort_field": "revisiondate", "sort_direction": "desc",
        }
        if revision:
            params["show_document_history"] = "true"
        root = await gw.aconex.get_xml(f"/projects/{project}/register", params)
        wanted = number.strip().casefold()
        rows = [d for d in parse_documents(root) if d["number"].casefold() == wanted]
        if revision:
            rows = [d for d in rows if d["revision"].casefold() == revision.strip().casefold()]
        if not rows:
            what = f"{number} revision {revision}" if revision else number
            raise ToolError(f"No document {what} on this project. Check the number with "
                            "search_register (or revision_history for its revisions).")
        return rows[0]

    @read_tool(server, gw,
               "Get the actual file of a register document (the PDF, or e.g. the DWG with "
               "file_name) when the person asks for a document, a drawing or 'the PDF', or when you "
               "need to read a drawing properly. Give document_number (e.g. EL-CSH12) for the "
               "current revision, plus revision for an older one; or a document_id from a search. "
               "Returns a download link that works once, within 10 minutes. Then: download the link "
               "into your workspace (e.g. curl -L -o \"<file_name>\" \"<download_url>\") and give the "
               "person the file in the chat; to read it, open the downloaded file and look at it at "
               "high resolution, since drawing notes are often drawn as lines rather than stored as "
               "text. If your workspace can't reach the link, give the person the link to click.")
    async def get_document_file(project_id: str, document_number: str = "", document_id: str = "",
                                revision: str = "", file_name: str = "") -> dict:
        project = seg(project_id, "project ID")
        if bool(document_number.strip()) == bool(document_id.strip()):
            raise ToolError("Give either document_number or document_id.")
        if document_id:
            document = {"document_id": seg(document_id, "document ID"), "number": "", "revision": "",
                        "title": "", "file": ""}
        else:
            document = await find_document(project, document_number, revision)
            seg(document["document_id"], "document ID")
        url = links.create(current_person(), project, document["document_id"], file_name.strip())
        name = file_name.strip() or document["file"]
        return {
            "document_number": document["number"],
            "revision": document["revision"],
            "title": document["title"],
            "file_name": name or "(named when downloaded)",
            "download_url": url,
            "expires_in_minutes": LINK_TTL_S // 60,
            "next_step": "Download download_url into your workspace and give the person the file "
                         "in the chat. If you can't reach it, give them the link to click.",
        }

    return links
