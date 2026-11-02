"""Stage 8 tests: unsent drafts, the gateway's only write, previewed first."""

import json

import anyio
import pytest
from mcp.client.client import Client

import gateway.tools.drafts as drafts_module
from gateway.aconex import AconexError
from gateway.aconex.client import AconexClient
from gateway.guard import AuditLog, Policy
from gateway.server import build_server
from tests.fake_aconex import FakeAconex

APPROVED = Policy(allowed_projects=frozenset({"1001"}))
ME = "lachie@asmblr.com.au"


@pytest.fixture(autouse=True)
def shared_db(monkeypatch, tmp_path):
    monkeypatch.setenv("AUDIT_DB", str(tmp_path / "gateway.db"))
    monkeypatch.setattr(drafts_module, "current_person", lambda: ME)


def session(fake, steps, policy=APPROVED):
    """Run several tool calls on one gateway (so approval codes carry over)."""
    async def run():
        out = []
        async with Client(build_server(fake.client(), policy, AuditLog(":memory:"))) as c:
            for name, args in steps:
                r = await c.call_tool(name, args)
                out.append((True, r.content[0].text) if r.is_error
                           else (False, r.structured_content or json.loads(r.content[0].text)))
        return out
    return anyio.run(run)


DRAFT = {"project_id": "1001", "to": ["Sam Lee"], "cc": ["Jo Park"], "mail_type": "general",
         "subject": "Pour on Thursday", "message": "Hi Sam,\n\nWe'll pour Thursday.",
         "reason": "information"}


def posts(fake):
    return [c for c in fake.calls if c["method"] == "POST"]


# ── preview ─────────────────────────────────────────────────────────

def test_prepare_saves_nothing_and_previews_with_signature():
    fake = FakeAconex()
    [(err, preview)] = session(fake, [("prepare_draft", DRAFT)])
    assert not err and posts(fake) == []
    assert preview["status"].startswith("PREVIEW")
    assert preview["to"] == ["Sam Lee (Acme Engineers)"] and preview["cc"] == ["Jo Park (Builder Co)"]
    assert preview["mail_type"] == "General Correspondence"
    assert preview["reason_for_issue"] == "Issued for Information"
    assert preview["message"].endswith(
        "Regards,\nLachie Barnett\nDirector\nASMBLR\n0410 004 180\nlachie@asmblr.com.au")
    assert preview["approval_code"]


def test_ambiguous_or_unknown_recipient_is_explained():
    [(err, text)] = session(FakeAconex(), [("prepare_draft", {**DRAFT, "to": ["Sam"]})])
    assert err and "2 people match" in text and "Sam Ortiz" in text
    [(err, text)] = session(FakeAconex(), [("prepare_draft", {**DRAFT, "to": ["Nobody Here"]})])
    assert err and "nobody in this project's directory" in text


def test_documents_only_on_transmittals():
    [(err, text)] = session(FakeAconex(), [("prepare_draft", {**DRAFT, "attach_documents": ["S-1100"]})])
    assert err and "only attaches register documents to Transmittal" in text
    [(err, preview)] = session(FakeAconex(), [("prepare_draft", {**DRAFT, "mail_type": "Transmittal",
                                                                "attach_documents": ["S-1100"]})])
    assert not err and preview["attached_documents"] == ["S-1100 rev B: Level 1 slab plan"]


def test_reply_defaults_to_the_sender_and_RE_subject():
    [(err, preview)] = session(FakeAconex(), [("prepare_draft", {
        "project_id": "1001", "mail_type": "Transmittal", "message": "Thanks, received.",
        "reply_to_mail_number": "LSGP-TRANSMIT-000143"})])
    assert not err, preview
    assert preview["subject"] == "RE: Warrs Project Example"
    assert preview["reply_to"].startswith("Reply to LSGP-TRANSMIT-000143")


# ── save ────────────────────────────────────────────────────────────

def test_save_uses_the_approved_draft_exactly_and_only_as_a_draft():
    fake = FakeAconex()
    results = session(fake, [("prepare_draft", {**DRAFT, "mail_type": "Transmittal", "attach_documents": ["S-1100"]})])
    code = results[0][1]["approval_code"]
    # A fresh gateway on the same database, as after a restart: the code still works.
    [(err, saved)] = session(fake, [("save_draft", {"project_id": "1001", "approval_code": code})])
    assert not err, saved
    assert saved["draft_number"] == "DRAFT-000001" and "NOT been sent" in saved["saved"]
    [post] = posts(fake)
    assert post["path"] == "/projects/1001/mail" and post["params"] == {"is_draft": "true"}
    body = post["json"]
    assert "<ToUserId>501</ToUserId>" in body and "<CcUserId>502</CcUserId>" in body
    assert "<MailTypeId>23</MailTypeId>" in body and "<ReasonForIssue>4</ReasonForIssue>" in body
    assert "<AttachedDocId>9001</AttachedDocId>" in body and "<MailSubject>Pour on Thursday</MailSubject>" in body
    assert "Lachie Barnett<br/>Director" in body
    assert body.index("<AttachedDocId>") < body.index("<MailBody>") < body.index("<ToUserId>")  # schema order


def test_reply_draft_goes_to_the_reply_address():
    fake = FakeAconex()
    [(_, p)] = session(fake, [("prepare_draft", {"project_id": "1001", "mail_type": "Transmittal",
                                                 "message": "Received.", "reply_to_mail_number": "LSGP-TRANSMIT-000143"})])
    session(fake, [("save_draft", {"project_id": "1001", "approval_code": p["approval_code"]})])
    assert posts(fake)[0]["path"] == "/projects/1001/mail/m1/reply"


def test_replacing_a_draft_sends_its_id():
    fake = FakeAconex()
    [(_, p)] = session(fake, [("prepare_draft", {**DRAFT, "replace_draft_number": "DRAFT-000009"})])
    assert p["replaces_draft"] == "DRAFT-000009"
    session(fake, [("save_draft", {"project_id": "1001", "approval_code": p["approval_code"]})])
    assert "<ExistingMailId>d9</ExistingMailId>" in posts(fake)[0]["json"]


def test_code_works_once():
    fake = FakeAconex()
    [(_, p)] = session(fake, [("prepare_draft", DRAFT)])
    first, second = session(fake, [("save_draft", {"project_id": "1001", "approval_code": p["approval_code"]})] * 2)
    assert not first[0] and second[0] and "isn't valid" in second[1]
    assert len(posts(fake)) == 1


def test_made_up_code_saves_nothing():
    fake = FakeAconex()
    [(err, text)] = session(fake, [("save_draft", {"project_id": "1001", "approval_code": "made-up"})])
    assert err and posts(fake) == []


def test_someone_else_cannot_use_my_code(monkeypatch):
    fake = FakeAconex()
    [(_, p)] = session(fake, [("prepare_draft", DRAFT)])
    monkeypatch.setattr(drafts_module, "current_person", lambda: "someone@asmblr.com.au")
    [(err, text)] = session(fake, [("save_draft", {"project_id": "1001", "approval_code": p["approval_code"]})])
    assert err and "someone else's draft" in text and posts(fake) == []


def test_off_switch_stops_saving():
    fake = FakeAconex()
    [(_, p)] = session(fake, [("prepare_draft", DRAFT)])
    [(err, text)] = session(fake, [("save_draft", {"project_id": "1001", "approval_code": p["approval_code"]})],
                            policy=Policy(allowed_projects=frozenset({"1001"}), switched_off=True))
    assert err and "switched off" in text and posts(fake) == []


def test_there_is_no_way_to_send():
    from gateway.aconex.client import AconexClient
    names = [n for n in dir(AconexClient) if not n.startswith("_")]
    assert not any(word in n for n in names for word in ("send", "forward", "register_mail", "delete"))


def test_busy_aconex_never_saves_twice():
    import httpx
    from gateway.aconex import Settings
    attempts = []

    def handler(request):
        if request.url.host.endswith("oraclecloud.com"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        attempts.append(1)
        return httpx.Response(503, text="busy")

    client = AconexClient(Settings("id", "s", throttle_waits=(0, 0)), transport=httpx.MockTransport(handler))
    with pytest.raises(AconexError):
        anyio.run(client.save_draft, "1001", b"x", "b")
    assert len(attempts) == 1


# ── "open in Aconex" links (added 2 Nov 2026) ───────────────────────

def test_saved_draft_comes_with_a_link_to_open_it():
    fake = FakeAconex()
    [(_, p)] = session(fake, [("prepare_draft", {"project_id": "1001", "mail_type": "Transmittal",
                                                 "message": "Received.", "reply_to_mail_number": "LSGP-TRANSMIT-000143"})])
    assert p["original_in_aconex"] == "https://au1.aconex.com/ViewCorrespondence?Correspondence_ID=m1"
    [(_, saved)] = session(fake, [("save_draft", {"project_id": "1001", "approval_code": p["approval_code"]})])
    assert saved["open_in_aconex"] == "https://au1.aconex.com/ViewCorrespondence?Correspondence_ID=d1"


def test_mail_links_follow_the_company_aconex_site(monkeypatch):
    monkeypatch.setenv("ACONEX_WEB_URL", "https://uk1.aconex.co.uk/")
    [(_, found)] = session(FakeAconex(), [("search_mail", {"project_id": "1001", "box": "sent"})])
    assert found["mails"][0]["open_in_aconex"] == "https://uk1.aconex.co.uk/ViewCorrespondence?Correspondence_ID=m8"
    [(_, mail)] = session(FakeAconex(), [("read_mail", {"project_id": "1001", "mail_id": "m1"})])
    assert mail["open_in_aconex"].endswith("Correspondence_ID=m1")
