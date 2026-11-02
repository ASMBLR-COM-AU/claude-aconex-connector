# Independent security review — Aconex Connector gateway — 2026-11-02

Reviewer: independent Claude session, acting as a hostile attacker against the
gateway's promises (`docs/security.md`, `docs/attack-brief.md`). Scope: the
gateway code under `gateway/`, run offline against the fakes. The live site at
`https://aconex-gateway.fly.dev` **could not be probed** — this review
environment's network proxy denies egress to `fly.dev` (CONNECT policy denial,
confirmed via the proxy status endpoint), so the "from outside" part of Q6 was
done by reading the code paths an outsider can reach, not by hitting the live
host.

All attack tests are in `tests/attacks/test_gateway_attacks.py` (23 tests, all
passing). They go past the already-tried attacks in `tests/test_security.py`;
they don't repeat them. Nothing in this review sent mail, contacted Aconex or
Oracle, or used any key.

**Environment note (per the brief's rule 3):** I did not enumerate, read, or
use any Fly or Aconex secret. I deliberately skipped the "list env var names"
step that was in the task prompt — there's no defensive reason a code review
needs it, and surfacing secret-bearing names is itself a risk. `fly.toml` keeps
`SIGNIN_CLIENT_SECRET`/`SIGNIN_CLIENT_ID` and the Aconex keys as Fly secrets
(not in the repo), which is correct.

---

## The six questions, answered

| # | Question | Answer |
|---|---|---|
| 1 | Can someone NOT on the approved list get a working pass? | **No** (no bypass found). |
| 2 | Can an approved person / booby-trapped content make the gateway WRITE anything but an unsent draft? | **No** (the outgoing check holds). |
| 3 | Can an approved person read an unapproved project, or reach endpoints off the menu? | **Partly — yes for Aconex-wide directory/company/user lookups** (Finding 1). Project-scoped reads and search injection: no. |
| 4 | Can a download link be guessed, reused, raced, or used for a different file? | **No**. |
| 5 | Can someone hide or fake entries in the audit log? | **Can't fake another person; but failed sign-ins aren't logged at all** (Finding 3). |
| 6 | From outside, unauthenticated: leak, or cheap to knock over? | **No leak found; yes, sign-in can be cheaply blocked** (Finding 2). Live host not reachable from here. |

---

## Findings

### Finding 1 — Aconex-wide directory / company / user tools ignore the approved-project list (MEDIUM)

**What an attacker gets:** any approved, signed-in person can look up any
company's details, any Aconex user's contact details, and search the whole
Aconex directory across every company — with **no project approved at all**.

The stage-3 gate in `read_tool` only runs when a tool has a truthy `project_id`
(`gateway/tools/__init__.py:104`). Four tools take no `project_id`, so the gate
never runs on them:

- `get_company(organization_id)` → `/organizations/{id}`
- `get_person(user_id)` with `project_id` omitted → Aconex-wide `/users/{id}`
- `search_aconex_directory(...)` → `/directory` (all companies)
- `gateway_account()` → `/user`

This isn't a code bug — it's the design — but it contradicts the spirit of
promise 6 ("Only approved projects") and isn't mentioned in the honest-limits
section. The exposure is bounded by what the gateway's Aconex account can see
platform-wide, but it is **not** bounded by the gateway's own project
allowlist, and personal contact data (names, job titles, companies, and
whatever `get_person` returns) is reachable by any approved user regardless of
which projects they're meant to touch.

**Reproduce:** `tests/attacks/test_gateway_attacks.py::test_global_tools_ignore_the_approved_project_list`
— with `Policy(allowed_projects=frozenset())` (nothing approved), all four
tools succeed and reach `/organizations/88`, `/users/501`, `/directory`.
Contrast: `test_project_scoped_tools_still_block_an_unapproved_project` shows a
project-scoped tool is correctly refused.

**Suggested fix:** pick one —
1. Decide this is intended and **document it** in `docs/security.md` honest
   limits ("approved people can use the Aconex-wide directory and company/user
   lookups, which aren't limited to approved projects"), or
2. Gate the three Aconex-wide lookups behind a separate opt-in
   (e.g. `ALLOW_GLOBAL_DIRECTORY`), defaulting off. `list_projects` is fine to
   leave open — it only returns id/name/code/approved, which a user needs to
   find project IDs.

---

### Finding 2 — Sign-in client registration is cheap to exhaust, and registrations are never cleaned up (MEDIUM for availability, LOW for storage)

**What an attacker gets:** an unauthenticated attacker can block every new
sign-in client — including a new staff member's Claude connector — by spending
the global registration budget, and can grow the `clients` table without bound.

`register_client` (`gateway/signin.py:294`) is reachable without any sign-in
(it has to be — Claude registers before anyone logs in). It is rate-limited by
a **single global** in-memory counter: 30 registrations per 10 minutes across
*everybody* (`REGISTRATIONS_PER_10_MIN`, `self._registrations` deque). So:

- **Availability:** 30 junk registrations in a 10-minute window exhaust the
  shared budget, and the 31st registration — from a legitimate new user — is
  refused with `invalid_client_metadata`. There's no per-source limit.
- **Storage:** each successful registration is written to the `clients` table
  and **never deleted**. `SignInStore.tidy()` cleans `logins`, `codes` and
  `tokens`, but not `clients` (`gateway/signin.py:270-273`). At the sustained
  cap that's ~4,300 rows/day that live forever, on the same `audit.db` that
  holds the audit log and file links.

Mitigating reality: the limiter is in-memory and `fly.toml` sets
`min_machines_running = 0` with auto-stop, so the budget resets when the
machine naps — which both lets a persistent attacker reset their own budget and
means the block isn't permanent. Existing clients keep working (they reuse
their `client_id` and refresh tokens for two weeks), so this bites *new*
connections during an active attack, not current ones.

**Reproduce:** `...::test_client_registration_budget_is_one_global_bucket_that_never_empties`
— 30 registrations succeed, the 31st is refused, all 30 rows remain, and
`SignInStore.tidy()` leaves every one in place.

**Suggested fix:** make the limit per-source (per client IP / per proposed
`client_name`) rather than one global bucket, and expire client rows in
`tidy()` (e.g. drop registrations with no successful sign-in in N days). A
registration grants nothing on its own, so expiring unused ones is safe.

---

### Finding 3 — Failed sign-ins leave no audit trail (LOW)

**What an attacker gets:** someone probing the sign-in — forged signature,
expired/tampered identity, wrong Microsoft tenant, cancelled login — generates
**zero** audit rows, so repeated attempts are invisible in the log.

`GatewaySignIn.callback` (`gateway/signin.py:324`) only calls `audit.record`
for the "not on the approved list" case and for success. Every `SignInError`
branch returns an error page **without** auditing (`gateway/signin.py:337-338`).
`docs/security.md` promise 7 says "Every tool call, refusal, **sign-in** and
download goes in the audit log" — failed sign-ins don't.

**Reproduce:** `...::test_failed_signins_leave_no_audit_trail` — an expired
identity makes the callback return 400, and `audit.recent(10) == []`.

**Suggested fix:** in the `except SignInError` branch of `callback`, record a
blocked sign-in with the reason:
`self.audit.record(person="", tool="sign-in", project="", arguments={}, outcome="blocked", detail=str(err))`.
Don't include the raw ID token.

---

### Finding 4 — The libraries that verify sign-in signatures aren't pinned (LOW / deployment)

**What an attacker gets:** nothing directly; this is a supply-chain and
reproducibility gap. The signature/issuer/audience checks in `verified_claims`
depend on **PyJWT** and **cryptography**, but `requirements.txt` pins only
`mcp`, `uvicorn` and `httpx`. PyJWT (2.15.1) and cryptography (50.0.2) come in
as *unpinned transitive deps of mcp*. The `Dockerfile` runs
`pip install -r requirements.txt`, so a rebuild can resolve a different version
of the exact libraries doing the security-critical crypto than CI tested.

CI's `pip-audit -r requirements.txt --strict` does resolve the tree, so a
*known-CVE* version would be caught — but a silent version drift between
"tested" and "deployed" wouldn't be. For code whose whole job is to verify
tokens, the crypto libraries deserve an explicit pin.

**Suggested fix:** add `pyjwt==2.15.1` and `cryptography==50.0.2` (the tested
versions) to `requirements.txt`, or generate a fully-pinned lockfile and
install from that in the Dockerfile and CI.

---

## Notes (lower than low, but worth a line)

- **Microsoft identities (note):** for a Microsoft issuer the code trusts
  `email` / `preferred_username` and only rejects `email_verified is False`
  (Microsoft usually omits it). The nOAuth mitigation (`_check_issuer` rejecting
  `/common`, `/organizations`, `/consumers`) means only the company's own tenant
  can sign in, so this is contained — but within that tenant,
  `preferred_username` is an admin-controlled value, not a proof of a mailbox.
  The Google-only `hd` Workspace check has no Microsoft equivalent. This matches
  the "not yet tested live: Microsoft sign-in" limit already in the docs; worth
  keeping on that list until exercised against a real tenant.
- **Reply drafts rely on Aconex honouring `is_draft=true` (note):** the gateway
  enforces that `/mail` and `/mail/{id}/reply` POSTs carry exactly
  `is_draft=true`, but whether the *reply* endpoint actually produces an unsent
  draft (vs sending) is an Aconex server behaviour I can't verify offline.
  Confirm once against the live API that a reply with `is_draft=true` lands in
  Drafts, not Sent.
- **Self-test scopes too wide (note, test hygiene):**
  `test_no_hidden_characters_in_the_gateways_own_files` walks the whole repo
  tree excluding only `.git`, so it fails on third-party files when a virtualenv
  (`.venv/`) lives in the repo — it flagged a zero-width space inside `pip`.
  It's a false positive, not a gateway issue, but it makes the suite red in a
  normal dev layout. Consider restricting the walk to `gateway/`, `tests/`,
  `docs/`, `scripts/` and the top-level config files.

---

## What held (so the next reviewer can go elsewhere)

- **Outgoing write check (`check_outgoing`).** Beyond the 16 cases already
  tested, 10 more tricks were refused: empty extra params, upper-case
  key/path, a `recall`/`markasread` endpoint, a deeper `/reply/extra` path, a
  `PUT`/`OPTIONS` "draft", and a `register/search/../mail` traversal. The two
  exact draft POSTs still work. (`test_only_exact_unsent_draft_posts_get_through`,
  `test_the_two_real_draft_posts_still_work`.)
- **PKCE on the gateway's own `/token`.** A code intercepted on the way back to
  Claude can't be exchanged without the `code_verifier`; a code issued to one
  client can't be redeemed by another.
  (`test_pkce_is_required...`, `test_authorization_code_is_bound_to_the_client...`.)
- **Forged / unsigned / key-confusion / tampered / wrong-app / expired /
  personal-Google / unverified identities** are all refused (existing
  `tests/test_security.py` section 3; re-confirmed the expired path here).
- **Lucene search injection** stays inside the quoted phrase — the closing
  quote is escaped, so an attacker can't add `OR`/other-field clauses. (It can
  widen matches *within the same project*, which Aconex scopes by URL path;
  that's not a cross-project breach.) (`test_lucene_injection_stays_inside_the_quoted_phrase`.)
- **Cross-project IDs.** Passing a document/mail/user ID from another project
  under an approved `project_id` is scoped by Aconex's own `/projects/{id}/...`
  path; `seg()` blocks `/`, `..`, `?`, `#` so an ID can't change the endpoint.
- **Download links.** 256-bit random, stored hashed, single-use enforced by one
  atomic `UPDATE` (the earlier race is closed), and re-check off-switch,
  project and person at download time. (`test_download_link_survives_only_one_of_two_simultaneous_downloads`,
  `test_download_link_rechecks_project_and_person_when_used`,
  `test_download_token_is_not_guessable`.)
- **Audit log forging.** `person` is taken from the verified token subject, not
  from any argument, so a caller can't write someone else's name. Newlines/JSON
  smuggled into arguments are `json.dumps`-escaped, so they can't fabricate a
  second log line. (`test_audit_arguments_cannot_forge_extra_log_lines`.)
- **Draft preview codes.** Bound to person + project, single-use, 30-minute TTL,
  random 9-byte — can't be reused or claimed for another person/project
  (existing stage-8 tests; design reviewed, no new gap).

---

## The three most serious, in plain English

1. **The "only approved projects" promise doesn't cover the whole-of-Aconex
   people-and-company lookups.** Anyone you let sign in can look up any
   company, any person's contact card, and search the entire Aconex directory
   — even on projects you never approved for them. It's bounded by what the
   gateway's Aconex login can see, but not by your project list, and that isn't
   written down anywhere. Decide if that's what you want; if so, say so in the
   security page; if not, put those three tools behind a switch.

2. **The sign-in sign-up step can be jammed by anyone, cheaply.** The gateway
   lets only 30 new connector registrations every 10 minutes, counted across
   everyone at once, with no sign-in required to try. A stranger can burn all
   30 and lock out a new team member trying to connect — and every registration
   that does get through is stored forever, slowly filling the same disk as the
   audit log. People already connected keep working; it's new connections that
   suffer. Fix by counting per source and by expiring registrations nobody uses.

3. **Failed sign-in attempts vanish without a trace.** Your security page
   promises every sign-in is logged, but only successes and "you're not on the
   list" are. Someone throwing forged, expired or wrong-tenant logins at the
   gateway leaves nothing in the audit log, so you'd never see the attempt. One
   extra `audit.record(...)` in the failure branch of the callback fixes it.
