"""Test run: real questions through the real gateway against the real Aconex,
with a pass/fail report. Read-only.

Run on a temporary Fly machine (scripts/test-run.sh), never on the live one.
It starts its own copy of the gateway in reads-only mode (the outgoing check
then refuses even unsent drafts), calls each tool the way Claude does (over
MCP, through the same HTTP app), and checks the answers make sense. It also
checks the live site from the outside.

    python -m gateway.testrun

The project, the people and documents it looks for are on the test project
(41 Warrs Road). For another company, copy CHECKS and change the facts.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

PROJECT = os.environ.get("TESTRUN_PROJECT", "2013297249")
LIVE = os.environ.get("TESTRUN_LIVE_URL", "https://aconex-gateway.fly.dev")
FACTS = {
    "drawing": "EL-CSH12",           # a drawing with a PDF
    "drawing_title_word": "precast",
    "words_inside_files": "1DG203",  # a door number only found inside drawings
    "person": "Baysinger",           # someone in the project directory
    "company": "ASMBLR",             # the gateway's own company
}


def setup_environment() -> None:
    os.environ["GATEWAY_NO_SIGNIN"] = "1"      # this copy is only reachable in-process
    os.environ["ACONEX_READS_ONLY"] = "1"      # refuse even unsent drafts
    os.environ.setdefault("ALLOWED_PROJECTS", PROJECT)
    os.environ.setdefault("AUDIT_DB", "/tmp/testrun.db")
    os.environ.setdefault("PERSON_CALLS_PER_MINUTE", "1000")


class Run:
    def __init__(self, http):
        self.http = http
        self.results: list[dict] = []
        self.found: dict = {}

    def tool(self, name: str, args: dict | None = None) -> tuple[bool, object]:
        response = self.http.post("/mcp", headers={
            "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-06-18",
        }, json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                 "params": {"name": name, "arguments": args or {}}})
        result = response.json().get("result", {})
        content = result.get("content") or [{}]
        text = content[0].get("text", "")
        if result.get("isError"):
            return False, text
        data = result.get("structuredContent")
        if data is None:
            try:
                data = json.loads(text)
            except ValueError:
                data = text
        return True, data

    def check(self, group: str, name: str, fn) -> None:
        started = time.monotonic()
        try:
            detail = fn() or ""
            outcome = "PASS"
        except Exception as err:  # noqa: BLE001 - every failure goes in the report
            outcome, detail = "FAIL", f"{type(err).__name__}: {err}"[:300]
        seconds = time.monotonic() - started
        if outcome == "PASS" and seconds > 20:
            outcome, detail = "SLOW", f"{detail} (took {seconds:.0f}s)"
        self.results.append({"group": group, "check": name, "outcome": outcome,
                             "seconds": round(seconds, 1), "detail": str(detail)[:300]})
        print(f"{outcome:4}  {group:9} {name} ({seconds:.1f}s) {detail}", flush=True)


def must(condition, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def rows(data, key: str) -> list:
    must(isinstance(data, dict), f"unexpected answer: {str(data)[:200]}")
    return data.get(key) or []


def checks(run: Run) -> None:
    p, f = PROJECT, FACTS

    def ok(name, args=None):
        good, data = run.tool(name, args)
        must(good, f"{name} refused: {str(data)[:200]}")
        return data

    # ── basics
    def ping():
        data = ok("ping")
        must("running" in str(data), str(data))
        return str(data)
    run.check("basics", "gateway answers", ping)

    def projects():
        data = ok("list_projects")
        mine = [x for x in rows(data, "projects") if str(x.get("project_id")) == p]
        must(mine and mine[0].get("approved"), f"project {p} not listed as approved")
        others = [x for x in rows(data, "projects") if not x.get("approved")]
        if others:
            run.found["other_project"] = str(others[0].get("project_id"))
        return f"{mine[0].get('name', '')}; {len(others)} other projects not approved"
    run.check("basics", "test project is listed and approved", projects)

    def account():
        data = ok("gateway_account")
        must(data, "empty")
        return "Aconex account found"
    run.check("basics", "gateway's Aconex account", account)

    # ── people
    def person():
        found = rows(ok("search_project_directory", {"project_id": p, "name": f["person"]}), "people")
        must(found, f"no {f['person']} in the directory")
        return f"{len(found)} found"
    run.check("people", f"find {f['person']} in the project directory", person)

    def company():
        found = rows(ok("search_project_directory", {"project_id": p, "company": f["company"]}), "people")
        must(found, f"nobody from {f['company']}")
        return f"{len(found)} people"
    run.check("people", f"find people from {f['company']}", company)

    # ── register
    def drawing():
        found = rows(ok("search_register", {"project_id": p, "number": f["drawing"]}), "documents")
        must(found, f"{f['drawing']} not found")
        doc = found[0]
        must(f["drawing_title_word"] in doc.get("title", "").lower(), f"title was {doc.get('title')!r}")
        run.found["document_id"] = doc.get("document_id")
        return f"{doc.get('number')} rev {doc.get('revision')}: {doc.get('title')}"
    run.check("register", f"find drawing {f['drawing']} by number", drawing)

    def history():
        data = ok("revision_history", {"project_id": p, "document_number": f["drawing"]})
        revisions = rows(data, "revisions")
        must(revisions, "no revisions")
        return f"{len(revisions)} revisions"
    run.check("register", "its revision history", history)

    def details():
        must(run.found.get("document_id"), "needs the drawing found above")
        data = ok("document_details", {"project_id": p, "document_id": run.found["document_id"]})
        must(isinstance(data, dict) and len(json.dumps(data)) > 100, "almost empty")
        return "details returned"
    run.check("register", "its details", details)

    def inside_files():
        data = ok("search_register", {"project_id": p, "words": f["words_inside_files"],
                                      "search_inside_files": True})
        found = rows(data, "documents")
        must(found, f"no drawing mentions {f['words_inside_files']}")
        return f"{len(found)} drawings mention it"
    run.check("register", f"search inside drawings for {f['words_inside_files']}", inside_files)

    def fields():
        data = ok("register_fields", {"project_id": p})
        must(isinstance(data, dict) and data, "empty")
        return ", ".join(list(data)[:6])
    run.check("register", "register fields", fields)

    def changed():
        since = (datetime.now(timezone.utc) - timedelta(days=90)).date().isoformat()
        ok("documents_changed_since", {"project_id": p, "since": since})
        return f"since {since}"
    run.check("register", "documents changed in the last 90 days", changed)

    # ── files
    def pdf():
        data = ok("get_document_file", {"project_id": p, "document_number": f["drawing"]})
        path = urlsplit(data["download_url"]).path
        first = run.http.get(path)
        must(first.status_code == 200, f"download gave HTTP {first.status_code}")
        must(first.content[:5] == b"%PDF-", "not a PDF")
        again = run.http.get(path)
        must(again.status_code == 410, f"second download gave HTTP {again.status_code}, expected refused")
        return f"real PDF, {len(first.content) // 1024} KB; second download refused"
    run.check("files", f"get the PDF of {f['drawing']} (link works once)", pdf)

    # ── mail
    def all_mail():
        data = ok("search_mail", {"project_id": p, "box": "all"})
        mails = rows(data, "mails")
        must(mails, "no mail found")
        run.found["mail_number"] = mails[0].get("number")
        return f"{len(mails)} mails; totals {data.get('total_matching')}"
    run.check("mail", "search all project mail", all_mail)

    def from_person():
        mails = rows(ok("search_mail", {"project_id": p, "from_person": f["person"]}), "mails")
        must(mails, f"no mail from {f['person']}")
        return f"{len(mails)} mails"
    run.check("mail", f"mail from {f['person']}", from_person)

    def from_company():
        mails = rows(ok("search_mail", {"project_id": p, "from_company": f["company"]}), "mails")
        must(mails, f"no mail from {f['company']}")
        return f"{len(mails)} mails"
    run.check("mail", f"mail from {f['company']}", from_company)

    def read():
        must(run.found.get("mail_number"), "needs a mail found above")
        data = ok("read_mail", {"project_id": p, "mail_number": run.found["mail_number"]})
        must(data.get("subject"), "no subject")
        link = data.get("open_in_aconex", "")
        must(link.startswith("https://") and "ViewCorrespondence" in link, f"link was {link!r}")
        return f"{run.found['mail_number']}: {data['subject'][:60]}"
    run.check("mail", "open a mail, with its Aconex link", read)

    def thread():
        data = ok("mail_thread", {"project_id": p, "mail_number": run.found.get("mail_number", "")})
        must(isinstance(data, dict) and data, "empty")
        return "thread returned"
    run.check("mail", "its thread", thread)

    def mail_types():
        data = ok("mail_fields", {"project_id": p})
        must(any("transmittal" in str(t).lower() for t in data.get("mail_types", [])), "no Transmittal type")
        return f"{len(data.get('mail_types', []))} mail types"
    run.check("mail", "mail types", mail_types)

    # ── drafts (preview only: nothing is saved)
    def preview():
        data = ok("prepare_draft", {"project_id": p, "to": [f["person"]], "mail_type": "General",
                                    "subject": "Test run preview (never saved)",
                                    "message": "Automated test run. This draft is never saved."})
        must(data.get("preview_code"), "no preview code")
        return f"to {data.get('to')}; preview only"
    run.check("drafts", "preview a draft (nothing saved)", preview)

    # ── safety
    def unapproved():
        other = run.found.get("other_project", "1")
        good, data = run.tool("register_fields", {"project_id": other})
        must(not good and "isn't switched on" in str(data), f"project {other} wasn't refused: {str(data)[:120]}")
        return f"project {other} refused"
    run.check("safety", "a project that isn't approved is refused", unapproved)

    def no_save():
        good, data = run.tool("save_draft", {"project_id": p, "preview_code": "made-up"})
        must(not good, "save_draft accepted a made-up code")
        return "refused"
    run.check("safety", "save_draft refuses a made-up code", no_save)

    def outgoing():
        import httpx

        from gateway.aconex.client import Refused, Settings, check_outgoing
        settings = Settings.from_env()
        for method, path in (("POST", f"/projects/{p}/mail"), ("POST", f"/projects/{p}/mail?is_draft=true"),
                             ("DELETE", f"/projects/{p}/register/1")):
            try:
                check_outgoing(httpx.Request(method, settings.api_url + path), settings)
            except Refused:
                continue
            raise AssertionError(f"{method} {path} was allowed")
        return "send, draft (in test mode) and delete all refused before leaving"
    run.check("safety", "the outgoing check refuses writes", outgoing)

    # ── the live site, from outside
    def live():
        import httpx
        health = httpx.get(LIVE + "/health", timeout=20)
        must(health.json() == {"status": "ok"}, f"health said {health.text[:100]}")
        for header in ("strict-transport-security", "x-content-type-options", "content-security-policy"):
            must(header in health.headers, f"missing {header}")
        mcp = httpx.post(LIVE + "/mcp", json={}, timeout=20)
        must(mcp.status_code == 401, f"/mcp without sign-in gave HTTP {mcp.status_code}")
        return "health says only ok; security headers present; /mcp needs sign-in"
    run.check("live site", "outside view", live)


def report(results: list[dict]) -> str:
    passed = sum(r["outcome"] == "PASS" for r in results)
    when = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"# Test run {when}", "",
             f"**{passed} of {len(results)} passed.** Project {PROJECT}, reads-only.", "",
             "| | Area | Check | Seconds | Result |", "|---|---|---|---|---|"]
    mark = {"PASS": "✅", "FAIL": "❌", "SLOW": "🐢"}
    for r in results:
        detail = r["detail"].replace("|", "/").replace("\n", " ")
        lines.append(f"| {mark[r['outcome']]} | {r['group']} | {r['check']} | {r['seconds']} | {detail} |")
    return "\n".join(lines)


def main() -> int:
    setup_environment()
    import logging
    logging.disable(logging.WARNING)  # keep the report readable
    from starlette.testclient import TestClient

    import gateway.tools.drafts as drafts
    from gateway.server import build_app

    # Drafts are previewed as the first approved person, so their signature is used.
    email = os.environ.get("ALLOWED_EMAILS", "").split(",")[0].strip()
    if email:
        drafts.current_person = lambda: email

    with TestClient(build_app(), base_url="http://localhost:8080") as http:
        run = Run(http)
        checks(run)
    text = report(run.results)
    print("\n=====REPORT=====\n" + text + "\n=====END=====", flush=True)
    failed = [r for r in run.results if r["outcome"] == "FAIL"]
    print(f"TEST RUN: {len(run.results) - len(failed)}/{len(run.results)} passed", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
