"""Stage 6 (experiment): getting a real PDF from Aconex to Claude.

Two ways are being tried, as two temporary tools, to see which Claude
surfaces (claude.ai chat, Desktop, Cowork, Claude Code) accept:

1. `test_pdf_in_reply`: the PDF itself, inside the tool's reply (an MCP
   embedded resource). Claude Code saves it as a file and reads it; claude.ai
   chat has been reported to reject it.
2. `test_pdf_download_link`: a short-lived link to the PDF. Claude Code and
   Cowork can fetch it themselves; in claude.ai the person clicks it.
3. `test_pdf_page_image`: a picture of one page (or a quarter of it, in more
   detail), since claude.ai accepts images in tool replies but not PDFs.

Whichever works becomes the real tool and these are removed.

Links: each is random, stored as a hash, tied to one document and the person
who asked, works for 15 minutes and at most 5 downloads, and re-checks the
off switch, the approved project and the approved person when used.
"""

from __future__ import annotations

import base64
import hashlib
import io
import mimetypes
import os
import secrets
import sqlite3
import threading
import time
from urllib.parse import quote

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import BlobResourceContents, CallToolResult, EmbeddedResource, ImageContent, TextContent
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response

from gateway.aconex import AconexError, seg
from gateway.guard import public_url
from gateway.tools import Gateway, current_person, read_tool

LINK_TTL_S = 15 * 60
LINK_MAX_USES = 5

IMAGE_EDGE_PX = 2000          # longest side of the picture sent to Claude
PNG_LIMIT_BYTES = 1_500_000   # above this, send a JPEG instead
PARTS = ("whole", "top-left", "top-right", "bottom-left", "bottom-right")


def page_picture(pdf: bytes, page_number: int, part: str) -> tuple[bytes, str, str]:
    """Render one page (or a quarter of it) as a picture. Returns (image,
    mime type, description). A quarter is rendered at twice the detail."""
    import pypdfium2 as pdfium

    try:
        document = pdfium.PdfDocument(pdf)
    except pdfium.PdfiumError:
        raise ToolError("That file isn't a PDF the gateway can draw.") from None
    pages = len(document)
    if not 1 <= page_number <= pages:
        raise ToolError(f"That document has {pages} page(s); ask for page 1 to {pages}.")
    page = document[page_number - 1]
    width, height = page.get_size()
    edge = IMAGE_EDGE_PX * (1 if part == "whole" else 2)
    image = page.render(scale=edge / max(width, height), grayscale=True).to_pil()
    if part != "whole":
        w, h = image.size
        left = 0 if part.endswith("left") else w // 2
        top = 0 if part.startswith("top") else h // 2
        image = image.crop((left, top, left + w // 2 + w % 2, top + h // 2 + h % 2))
    out = io.BytesIO()
    image.save(out, "PNG", optimize=True)
    kind = "image/png"
    if out.tell() > PNG_LIMIT_BYTES:
        out = io.BytesIO()
        image.convert("L").save(out, "JPEG", quality=80)
        kind = "image/jpeg"
    data = out.getvalue()
    return data, kind, (f"page {page_number} of {pages}, {part}, {image.size[0]}x{image.size[1]} px, "
                        f"{kind.split('/')[1].upper()} {len(data) // 1024} KB")


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
        self._run("DELETE FROM file_links WHERE expires < ?", (time.time(),))
        token = secrets.token_urlsafe(32)
        self._run("INSERT INTO file_links VALUES (?, ?, ?, ?, ?, ?, 0)",
                  (_hash(token), person, project, document, file_name, time.time() + LINK_TTL_S))
        return f"{public_url()}/files/{token}"

    async def serve(self, request: Request) -> Response:
        """GET /files/{token}: the person (or Claude, for them) downloads the file."""
        token = request.path_params.get("token", "")
        rows = self._run("SELECT person, project, document, file_name, expires, uses FROM file_links "
                         "WHERE hash = ?", (_hash(token),))
        if not rows or rows[0][4] < time.time() or rows[0][5] >= LINK_MAX_USES:
            return PlainTextResponse("This download link has expired. Ask Claude for a new one.", 410)
        person, project, document, file_name, _, _ = rows[0]

        def audit(outcome: str, detail: str = "") -> None:
            self.gw.audit.record(person=person, tool="download link used", project=project,
                                 arguments={"document_id": document}, outcome=outcome, detail=detail)

        policy = self.gw.policy
        if policy.switched_off or not policy.project_allowed(project) or (
                "@" in person and not policy.person_allowed(person)):
            audit("blocked", "switched off, project or person no longer approved")
            return PlainTextResponse("This download isn't allowed any more.", 403)
        self._run("UPDATE file_links SET uses = uses + 1 WHERE hash = ?", (_hash(token),))
        try:
            content, name = await self.gw.aconex.get_file(
                document_path(project, document), {"fileName": file_name} if file_name else None)
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

    @read_tool(server, gw,
               "TEST (stage 6 experiment): get a register document's actual file (e.g. the PDF) "
               "inside this reply. Use a document_id from search_register. file_name picks one "
               "file of a multi-file document (e.g. the DWG); leave empty for the main file.")
    async def test_pdf_in_reply(project_id: str, document_id: str, file_name: str = "") -> CallToolResult:
        project, document = seg(project_id, "project ID"), seg(document_id, "document ID")
        content, name = await gw.aconex.get_file(
            document_path(project, document), {"fileName": file_name} if file_name else None)
        return CallToolResult(content=[
            TextContent(type="text", text=f"{name} ({len(content) // 1024} KB) from Aconex."),
            EmbeddedResource(type="resource", resource=BlobResourceContents(
                uri=f"aconex://projects/{project}/documents/{document}/{quote(name)}",
                mime_type=mime_type(name),
                blob=base64.b64encode(content).decode(),
            )),
        ])

    @read_tool(server, gw,
               "TEST (stage 6 experiment): a picture of one page of a register document's PDF, so "
               "you can look at a drawing. part: whole (the full sheet) or top-left, top-right, "
               "bottom-left, bottom-right (that quarter, in twice the detail: use it to read small "
               "text, dimensions and details).")
    async def test_pdf_page_image(project_id: str, document_id: str, page: int = 1,
                                  part: str = "whole") -> CallToolResult:
        if part not in PARTS:
            raise ToolError("part must be one of: " + ", ".join(PARTS) + ".")
        project, document = seg(project_id, "project ID"), seg(document_id, "document ID")
        content, name = await gw.aconex.get_file(document_path(project, document))
        image, kind, about = page_picture(content, page, part)
        return CallToolResult(content=[
            TextContent(type="text", text=f"{name}: {about}."),
            ImageContent(type="image", data=base64.b64encode(image).decode(), mime_type=kind),
        ])

    @read_tool(server, gw,
               "TEST (stage 6 experiment): a link to download a register document's actual file "
               "(e.g. the PDF). Works for 15 minutes. If you can fetch web addresses, download it "
               "and open it; otherwise give the link to the person.")
    async def test_pdf_download_link(project_id: str, document_id: str, file_name: str = "") -> dict:
        project, document = seg(project_id, "project ID"), seg(document_id, "document ID")
        url = links.create(current_person(), project, document, file_name.strip())
        return {"download_url": url, "expires_in_minutes": LINK_TTL_S // 60,
                "note": "The link downloads the original file from Aconex. It stops working after "
                        "15 minutes or 5 downloads."}

    return links
