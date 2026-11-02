# Attack brief: independent security review

You are reviewing the Aconex Gateway as a hostile, skilled attacker would.
Your job is to find ways to break its promises, not to confirm they hold.
Assume the author missed things. `docs/security.md` lists the promises;
`PLAN.md` and `docs/stages/` explain the design.

## Hard rules (non-negotiable)

1. **Never send mail, or cause mail to be sent, to anyone.** Not through the
   gateway, not through Aconex, not through any connector or tool.
2. **Never contact Aconex or Oracle** (`*.aconex.com`, `*.oraclecloud.com`),
   and never use an "Aconex" connector or tool if one is available to you.
3. **Never use Fly.io** (`flyctl`, `fly`, any `FLY_*` value) or any key,
   token or secret you find in your environment. If you notice one, say so
   in your report as a finding, and don't use it.
4. **The live gateway** (`https://aconex-gateway.fly.dev`): only requests
   *without* signing in, at most 1 a second and 200 in total. No load
   testing, no attempts to sign in as anyone, no guessing of real people's
   emails. It runs on a small machine that real people use.
5. **Don't change the gateway's code.** Write tests and a report only.

Everything else is fair game, offline: read all the code, run it locally
(`python -m pytest -q`; the tests use a fake Aconex and a fake Google), write
new tests that attack it, and run the server locally against the fakes.

## Where to dig (start here, don't stop here)

- **The outgoing check** (`check_outgoing` in `gateway/aconex/client.py`):
  any request that reaches the fake Aconex as a write other than an unsent
  draft or the register search. Encoding, redirects, header tricks, httpx
  behaviour.
- **Sign-in** (`gateway/signin.py` plus the MCP library's OAuth endpoints):
  client registration, redirect URIs, PKCE, `state`, code and refresh-token
  reuse, token `resource`/audience, revocation, the callback, ID token checks.
  Can someone not on the approved list get a working pass?
- **Project approval:** can an approved person reach data from a project that
  isn't approved (e.g. passing an ID that belongs to another project, or a
  tool that doesn't take `project_id`)? Global directory and company tools?
- **Search injection:** text passed into Aconex search queries
  (`gateway/aconex/parse.py` `lucene_phrase`, every `search_query` built in
  `gateway/tools/`). Can it widen a search beyond what was intended?
- **Download links** (`gateway/tools/files.py`): guessing, reuse, races,
  using a link after the person or project is removed, path tricks in
  `document` or `file_name`.
- **Drafts** (`gateway/tools/drafts.py`): can a draft be saved that differs
  from its preview, for another person or project, or with recipients outside
  the project directory? Can preview codes be guessed or reused?
- **Booby-trapped content:** what text from Aconex (mail, titles, file names,
  attachment names) reaches Claude, and could it trick Claude into a harmful
  *chain* of the gateway's own tools?
- **Audit log** (`gateway/guard.py`): can an attacker hide an action, fake
  another person's name in it, or break it with odd input?
- **Denial of service:** unbounded storage (client registrations, links,
  codes), huge responses, slow requests, the per-person limit.
- **Leaks:** secrets or personal data in error messages, logs, `/health`.
- **Deployment:** `Dockerfile`, `fly.toml`, `.github/workflows/ci.yml`,
  dependency versions.

## What to hand back

A report at `docs/attacks/<YYYY-MM-DD>-independent-review.md`, on a branch
named `attack-review-<YYYY-MM-DD>` (never on `main`), plus any attack tests in
`tests/attacks/`. For each finding:

- **Severity:** critical / high / medium / low / note
- **What an attacker gets**, in one plain sentence
- **Steps to reproduce**, ideally as a failing test
- **Suggested fix**

Also list what you tried that *held*, so the next reviewer can go elsewhere.
Be blunt. A finding the author doesn't like is the point.
