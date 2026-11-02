# Security: what the gateway can and can't do

The short version: **the Aconex key never reaches Claude. Claude orders off a
fixed menu, and the gateway checks every order.** This page lists each promise,
the code that enforces it, and the test that proves it. It also lists the
limits honestly, because a claim without its limits isn't worth much.

## The promises

| # | Promise | Enforced by | Proved by |
|---|---|---|---|
| 1 | **Nothing can send mail**, change a document, or write anything to Aconex except an unsent draft | `check_outgoing` in `gateway/aconex/client.py`, run inside the HTTP client on every request just before it leaves. It allows only: the Aconex login, reads (GET), one search endpoint, and saving a draft with exactly `is_draft=true`. It sits below every tool, so a bug in a tool can't get past it | `tests/test_security.py` (16 send/write attempts, including encoded paths and doubled settings); the fake Aconex fails *every* test if a write ever reaches it; switching the check off makes 17 tests fail (tried 2 Nov 2026) |
| 2 | Claude never sees the Aconex key | The key is a Fly secret, read only by the running gateway. No tool returns it; the log records only its length | Code review; key appears nowhere in tool replies or the audit log |
| 3 | No "call any API" tool | The menu is fixed in code (`gateway/tools/`). Every tool takes typed arguments; IDs are checked against `^[A-Za-z0-9_-]{1,64}$` so they can't change which endpoint is called | `test_no_catch_all_or_writing_tools`, `test_no_tool_can_reach_a_send_even_with_crafted_arguments` |
| 4 | Only approved people get in | Sign-in through the company's Google Workspace or Microsoft Entra ID; the email must be on the approved list; checked again on every request | `tests/test_stage4.py` |
| 5 | Sign-in can't be forged | The identity's digital signature is checked against Google's or Microsoft's published keys, plus issuer, audience, expiry and a one-time value. Google: the account must be managed by the company's Workspace (blocks a personal Google account made with a work email). Microsoft: only the company's own tenant (blocks the "nOAuth" trick) | `tests/test_security.py`: forged signature, unsigned, key-confusion trick, tampered email, wrong app, expired, personal account, unverified email, shared Microsoft address |
| 6 | Only approved projects | `ALLOWED_PROJECTS`, checked before every tool and every download | `tests/test_stage3.py` |
| 7 | Everything is logged with a name on it | Every tool call, refusal, sign-in and download goes in the audit log (person, tool, project, arguments, outcome) | `tests/test_stage3.py` |
| 8 | One off switch stops everything | `GATEWAY_OFF=1` | `tests/test_stage3.py` |
| 9 | One person can't use up the company's Aconex limit | 30 requests a minute per person; the gateway as a whole stays under Aconex's limit | `tests/test_security.py` |
| 11 | Hidden characters can't be smuggled to Claude | Everything Aconex sends back is cleaned first (`clean_tree`, `clean_value`, `html_to_text` in `gateway/aconex/parse.py`): invisible "tag" characters that can hide instructions an AI reads but a person can't see, right-to-left overrides that make "fdp.exe" look like "exe.pdf", zero-width characters and control characters | `tests/test_security.py` section 4 |
| 12 | Outsiders learn nothing useful | The public `/health` page says only "ok". Every response tells browsers to use HTTPS only and not to run scripts or frame the pages. Sign-in registrations are limited to 30 in 10 minutes | `tests/test_security.py` section 4 |
| 10 | Passes and links can't be reused from a stolen database | Passes, codes and links are stored only as hashes; passes last an hour and renewals retire the old one | `tests/test_stage4.py`, `tests/test_stage6.py` |

## Honest limits

- **Whoever controls the server controls the key.** Anyone who can deploy to
  the Fly app, or push to `main` on GitHub (which deploys automatically), can
  read the Aconex key and use it directly, outside the gateway's rules. Today
  that includes the Claude build environment. Before a company uses this:
  take Fly access out of the build environment, require approval on `main`,
  and use a plain Aconex account with only the permissions the gateway needs
  (currently a testing admin account). These are listed in `PLAN.md`.
- **Booby-trapped content.** Mail and documents can contain text written to
  trick an AI. The gateway gives that text nothing to act on in Aconex (no
  send, no changes). But if the company's Claude can also reach the open web
  or other tools, a trick could try to copy what Claude read *out* through
  those. That's controlled in Claude's organisation settings (allowed domains,
  other connectors); see the runbook's "Recommended Claude settings".
- **Draft approval is Claude's job, not proof.** `prepare_draft` returns a
  preview code that guarantees the saved draft matches the preview word for
  word. Claude receives the code, so "ask the person first" relies on Claude
  following instructions, or on Claude's per-tool approval setting. The hard
  stop is that drafts are never sent: a person presses Send in Aconex.
- **Download links are bearer links.** A link works once, within 10 minutes,
  for one file. Whoever holds it in that window can use it; it isn't tied to
  a login, because Claude's workspace can't sign in.
- **Whole-project mail.** Any approved person can search all project mail the
  gateway's Aconex account can see (a deliberate choice, for tracing issues).
  Confidential mail stays hidden by Aconex. Every search and mail opened is
  logged under the person.
- **Aconex-wide people and companies.** The approved-projects list limits the
  document register and mail, but the directory and company lookups
  (`search_aconex_directory`, `get_company`, and `get_person` without a
  project) are not limited to approved projects: any approved person can look
  up any company or person the gateway's Aconex account can see across Aconex.
  That's the same reach Aconex itself gives that account, and every lookup is
  logged under the person. Flagged in the 2 Nov 2026 independent review; left
  open on purpose for now (it can be put behind a switch if a company wants it
  restricted).
- **The audit log is on the same server.** Someone with server access could
  change it. Shipping it somewhere the server can't edit is on the list.
- **Not yet tested live:** Microsoft sign-in, Claude Enterprise, a refused
  sign-in, and the booby-trapped email test. Not yet tested by an independent
  security firm.

## How to report a problem

Tell Lachie directly; don't post it publicly until it's fixed.

## Attack log

Each attack review, what it tried, what it found and what changed.

| Date | Who | Found | Fixed |
|---|---|---|---|
| 2 Nov 2026 | Independent review (separate Claude session; reviewed the skill's code by mistake, the live gateway from outside only) | Live gateway: `/health` showed version and off-switch state; no HTTPS-only (HSTS) or other security headers; open sign-in registration not limited. From the skill, applied to the gateway: hidden Unicode characters passed through to Claude | All fixed in 0.9.1. A full review of the gateway's own code is still to do |
| 2 Nov 2026 | Self-review | Draft code described as "approval"; links reusable 5 times and a race between two downloads; no per-person limit; sign-in signature unchecked; personal Google accounts and Microsoft shared addresses not refused; no library vulnerability check | All fixed in 0.9.0 (this page) |
| 2 Nov 2026 | Independent review (gateway code, offline against the fakes; live site not reachable from the review environment) | Aconex-wide directory/company lookups aren't limited to approved projects; sign-in registration was one global limit whose rows were never cleaned (lock-out + unbounded growth); failed sign-ins weren't logged; the JWT/crypto libraries weren't pinned. Full report: `docs/attacks/2026-11-02-gateway-review.md` | Registration now limited per source address with a bounded table; failed sign-ins logged; crypto libraries pinned; Aconex-wide reach documented above. Directory/company scoping left as a product decision |
