"""Builder reports: which subbies are working off old drawings?"""

import json

import anyio
import httpx
from mcp.client.client import Client

from gateway.aconex.client import AconexClient, Settings
from gateway.guard import AuditLog, Policy
from gateway.server import build_server
from gateway.tools.reports import outdated_holdings

TOKEN_HOST = "constructionandengineering.oraclecloud.com"

REGISTER = b"""<RegisterSearch TotalResults="3" CurrentPage="1" TotalPages="1"><SearchResults>
  <Document DocumentId="1"><DocumentNumber>S-101</DocumentNumber><Revision>C</Revision><Title>Level 1 slab</Title><Discipline>Structural</Discipline></Document>
  <Document DocumentId="2"><DocumentNumber>S-102</DocumentNumber><Revision>B</Revision><Title>Level 2 slab</Title><Discipline>Structural</Discipline></Document>
  <Document DocumentId="3"><DocumentNumber>A-201</DocumentNumber><Revision>2</Revision><Title>Level 2 plan</Title><Discipline>Architectural</Discipline></Document>
</SearchResults></RegisterSearch>"""


def row(mail_id, number, sent):
    return (f'<Mail MailId="{mail_id}"><MailNo>{number}</MailNo><SentDate>{sent}</SentDate>'
            f'<CorrespondenceType>Transmittal</CorrespondenceType></Mail>')


SENTBOX = ('<MailSearch TotalResults="4" CurrentPage="1" TotalPages="1"><SearchResults>'
           + row("t1", "BLD-TRANSMIT-000001", "2026-01-10T00:00:00Z")
           + row("t2", "BLD-TRANSMIT-000002", "2026-02-10T00:00:00Z")
           + row("t3", "BLD-TRANSMIT-000003", "2026-03-10T00:00:00Z")
           + row("t4", "BLD-TRANSMIT-000004", "2026-04-10T00:00:00Z")
           + "</SearchResults></MailSearch>").encode()


def detail(number, sent, to_orgs, docs):
    recips = "".join(f"<Recipient><DistributionType>TO</DistributionType><Name>X</Name>"
                     f"<OrganizationName>{o}</OrganizationName></Recipient>" for o in to_orgs)
    atts = "".join(f'<RegisteredDocumentAttachment attachmentId="a{i}"><DocumentNo>{n}</DocumentNo>'
                   f'<Revision>{r}</Revision></RegisteredDocumentAttachment>' for i, (n, r) in enumerate(docs))
    return (f'<Mail><MailNo>{number}</MailNo><SentDate>{sent}</SentDate>'
            f'<FromUserDetails><Name>Site Manager</Name><OrganizationName>Builder Co</OrganizationName></FromUserDetails>'
            f'<ToUsers>{recips}</ToUsers><Attachments>{atts}</Attachments></Mail>').encode()


DETAILS = {
    # January: both subbies get S-101 at revision B (now superseded).
    "t1": detail("BLD-TRANSMIT-000001", "2026-01-10T00:00:00Z", ["Steel Co", "Formwork Co"], [("S-101", "B")]),
    # February: a bulk issue to Steel Co carrying history AND the current revision C.
    "t2": detail("BLD-TRANSMIT-000002", "2026-02-10T00:00:00Z", ["Steel Co"], [("S-101", "B"), ("S-101", "C")]),
    # March: Formwork Co gets the current architectural plan; the builder copied itself.
    "t3": detail("BLD-TRANSMIT-000003", "2026-03-10T00:00:00Z", ["Formwork Co", "Builder Co"], [("A-201", "2")]),
}


def transport(calls):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == TOKEN_HOST:
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        path = request.url.path.removeprefix("/api")
        calls.append((request.method, path))
        if path == "/projects/1001/register":
            return httpx.Response(200, content=REGISTER)
        if path == "/projects/1001/mail" and request.url.params.get("mail_box") == "Sentbox":
            return httpx.Response(200, content=SENTBOX)
        mail_id = path.rsplit("/", 1)[-1]
        if mail_id in DETAILS:
            return httpx.Response(200, content=DETAILS[mail_id])
        if mail_id == "t4":
            return httpx.Response(500, text="too big")
        return httpx.Response(404)
    return httpx.MockTransport(handler)


def run(args):
    calls = []
    client = AconexClient(Settings("id", "secret", throttle_waits=()), transport=transport(calls))

    async def go():
        async with Client(build_server(client, Policy(allowed_projects=frozenset({"1001"})),
                                       AuditLog(":memory:"))) as c:
            return await c.call_tool("subbies_on_old_drawings", args)
    result = anyio.run(go)
    assert not result.is_error, result.content[0].text
    return result.structured_content or json.loads(result.content[0].text), calls


def test_finds_the_subbie_on_an_old_drawing():
    data, _ = run({"project_id": "1001"})
    assert data["companies_on_old_drawings"] == ["Formwork Co"]
    [old] = data["out_of_date"]
    assert (old["company"], old["document"], old["current_revision"], old["revisions_sent"]) == \
        ("Formwork Co", "S-101", "C", ["B"])
    assert old["last_sent_in"] == "BLD-TRANSMIT-000001"


def test_a_bulk_issue_with_history_counts_as_current_if_it_carried_the_current_revision():
    data, _ = run({"project_id": "1001"})
    steel = [s for s in data["summary"] if s["company"] == "Steel Co"]
    assert steel == [{"company": "Steel Co", "discipline": "Structural", "current": 1, "out_of_date": 0}]


def test_own_company_and_unsent_drawings_are_left_out():
    data, _ = run({"project_id": "1001"})
    assert all(s["company"] != "Builder Co" for s in data["summary"])
    assert all(r["document"] != "S-102" for r in data["out_of_date"])


def test_filters_by_discipline_and_company():
    data, _ = run({"project_id": "1001", "discipline": "architect"})
    assert data["out_of_date"] == [] and data["summary"] == [
        {"company": "Formwork Co", "discipline": "Architectural", "current": 1, "out_of_date": 0}]
    data, _ = run({"project_id": "1001", "company": "steel"})
    assert data["companies_on_old_drawings"] == []


def test_a_transmittal_that_fails_is_skipped_and_named():
    data, _ = run({"project_id": "1001"})
    assert data["checked"]["sent_mails_checked"] == 4 and data["checked"]["transmittals_with_drawings"] == 3
    assert data["skipped"] and data["skipped"][0].startswith("BLD-TRANSMIT-000004")


def test_it_only_reads():
    _, calls = run({"project_id": "1001"})
    assert calls and all(method == "GET" for method, _ in calls)


def test_newest_transmittals_are_checked_first_when_capped():
    data, calls = run({"project_id": "1001", "max_transmittals": 1})
    assert data["checked"]["sent_mails_checked"] == 1 and "not_checked" in data
    assert ("GET", "/projects/1001/mail/t4") in calls and ("GET", "/projects/1001/mail/t1") not in calls


def test_outdated_holdings_logic_directly():
    current = {"X-1": {"revision": "3", "title": "", "discipline": "Civil"}}
    sent = [{"company": "A", "doc": "X-1", "rev": "1", "mail": "m1", "date": "2026-01-01"},
            {"company": "A", "doc": "X-1", "rev": "2", "mail": "m2", "date": "2026-02-01"},
            {"company": "B", "doc": "X-1", "rev": "3", "mail": "m3", "date": "2026-03-01"},
            {"company": "C", "doc": "GONE", "rev": "1", "mail": "m4", "date": "2026-03-01"}]
    status = {(r["company"], r["document"]): r["status"] for r in outdated_holdings(current, sent)}
    assert status == {("A", "X-1"): "out of date", ("B", "X-1"): "current", ("C", "GONE"): "not in register"}
