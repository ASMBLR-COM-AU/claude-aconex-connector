# Runbook

How IT operates the gateway. Every command runs on a computer with the Fly
command-line tool (`fly`), signed in to the Fly organisation that owns the
`aconex-gateway` app.

## Turn the gateway off (emergency)

```bash
fly secrets set GATEWAY_OFF=1 -a aconex-gateway
```

The machine restarts in a few seconds. Every Aconex tool then answers "switched
off by IT" and nothing reaches Aconex. To confirm, run
`fly logs -a aconex-gateway --no-tail`: after the restart it shows
"Gateway is SWITCHED OFF". (The public `/health` page deliberately says only
"ok", so outsiders learn nothing about the gateway's settings.)

Turn it back on:

```bash
fly secrets unset GATEWAY_OFF -a aconex-gateway
```

Other ways to stop it, from fastest to most drastic:

1. **Claude admin:** remove or disable the connector in the Claude organisation's
   connector settings. Nobody can reach the gateway from Claude.
2. **The off switch** above.
3. **Stop the app:** `fly scale count 0 -a aconex-gateway`.
4. **Aconex:** revoke the gateway's API client in Aconex. The keys stop working
   everywhere.

## Read the audit log

The latest 50 calls (who, which tool, which project, outcome, how long):

```bash
fly ssh console -a aconex-gateway -C "python -m gateway.guard 50"
```

Every call also appears in the live log, as a line starting `{"audit":`:

```bash
fly logs -a aconex-gateway
```

The log is kept on an encrypted Fly volume with daily snapshots, kept 5 days.

## Approve a project

Edit `ALLOWED_PROJECTS` in `fly.toml` (comma-separated Aconex project IDs),
then merge the change on GitHub. GitHub deploys it. Projects not on the list
are refused. `list_projects` shows the names of every project the gateway's
Aconex account can see, each marked approved or not (decided 2 Nov 2026, so
people can find the project to ask for).

## Approve a person

Edit `ALLOWED_EMAILS` (single people) or `ALLOWED_DOMAINS` (everyone at a
domain, e.g. `asmblr.com.au`) in `fly.toml`, then merge the change on GitHub.
Removing someone takes effect as soon as that deploy finishes: their pass stops
working on their next request and can't be renewed.

## Set up sign-in with Google Workspace

One-off, about 5 minutes, free. Use an admin account on the company's Google
Workspace.

1. Open https://console.cloud.google.com and create a project called
   "Aconex Gateway".
2. Go to **Google Auth Platform** (older screens call it **APIs & Services ›
   OAuth consent screen**). Set the app name to "Aconex Gateway", pick a support
   email, and choose audience **Internal**, so only the company's own accounts
   can sign in.
3. Go to **Clients › Create client**. Type: **Web application**. Name: "Aconex
   Gateway". Under **Authorised redirect URIs** add exactly:
   `https://aconex-gateway.fly.dev/auth/callback`. Create it.
4. Copy the **Client ID** and **Client secret**. Don't paste them into chats or
   email.
5. In the Fly dashboard, open the `aconex-gateway` app › **Secrets**, and add
   `SIGNIN_CLIENT_ID` and `SIGNIN_CLIENT_SECRET` with those values. Or on the
   command line:
   `fly secrets set SIGNIN_CLIENT_ID=... SIGNIN_CLIENT_SECRET=... -a aconex-gateway`.
   The gateway restarts with them.

## Set up sign-in with Microsoft Entra ID (not yet tested)

1. In the Entra admin centre: **App registrations › New registration**. Name
   "Aconex Gateway", accounts in this organisational directory only. Redirect
   URI (Web): `https://aconex-gateway.fly.dev/auth/callback`.
2. **Certificates & secrets › New client secret.** Copy the value.
3. Set `SIGNIN_ISSUER` in `fly.toml` to
   `https://login.microsoftonline.com/<tenant ID>/v2.0` (the tenant ID is on
   the app's overview page), and set the two secrets as for Google.

It must be the company's **own tenant ID**. The gateway refuses Microsoft's
shared addresses (`/common`, `/organizations`, `/consumers`): with those,
someone in any other Microsoft tenant could sign in with an email address they
typed in themselves.

## Add the gateway to Claude

An Owner of the Claude Team or Enterprise organisation:

1. **Admin settings › Connectors › Add custom connector.**
2. URL: `https://aconex-gateway.fly.dev/mcp`. Authentication: sign in with
   OAuth. OAuth client: **Register automatically** (the gateway doesn't support
   Claude's "published identity" option yet). Leave client ID and secret empty.
3. Each approved person then opens **Settings › Connectors**, finds the
   gateway and clicks **Connect**. They're sent to the company login page.

For Claude in claude.ai to fetch real files (PDFs, DWGs) on command, the Owner
also sets, under **Admin settings › Capabilities**:

- **Code execution** switched on, and
- **Network access › allowed domains:** add `aconex-gateway.fly.dev`.

Without these, Claude still finds documents but can only hand the person a
download link to click. Claude Code and Cowork need neither.

Claude's settings screens change from time to time; if the wording differs,
follow Claude's current help for "custom connectors".

### Recommended Claude settings (security)

The gateway controls what Claude can do *in Aconex*. These Claude settings
control what Claude can do with what it reads:

- **Allowed domains:** add only `aconex-gateway.fly.dev` (plus any the company
  already needs). Never "all domains". Otherwise a booby-trapped email could
  tell Claude to post project information to an outside website.
- **`save_draft` needs approval:** in the connector's tool settings, set
  `save_draft` to ask every time (if Claude offers per-tool settings on your
  plan; to be checked on screen). Then a person must click to allow each
  draft, rather than relying on Claude following instructions.
- **Other connectors in the same chat** (e.g. email that can send): be aware
  that Claude could be asked to copy Aconex content into them. Keep sending
  tools on "needs approval".

## Changing a secret in the Fly dashboard

The dashboard can save a secret as **Staged** without applying it. If the
secrets list says "Staged", click **Deploy secrets**, or run
`fly secrets deploy -a aconex-gateway`. The gateway restarts with them.

The Aconex keys can be either `ACONEX_CLIENT_ID` + `ACONEX_CLIENT_SECRET`, or
the Aconex skill's single combined value in `ACONEX_CREDENTIALS_B64`. When the
gateway starts, the log line "Aconex keys (shape only)" shows what it found
(lengths, never the values).

## Per-person limit

Each person can make at most 30 gateway requests a minute (`PERSON_CALLS_PER_MINUTE`).
Over that, Claude is told to wait a minute, and the audit log shows "over the
per-person limit". It stops one person, or a runaway chat, from using up the
company's shared Aconex limit.

## Request pacing

Aconex allows 5 requests a second and 10 at once for the whole company. The
gateway uses at most 3 a second and 4 at once by default, leaving room for
other systems. Change with the `ACONEX_PER_SECOND` and `ACONEX_AT_ONCE`
settings if IT agrees a different share.

## Test run (after every change, before every demo)

```bash
scripts/test-run.sh
```

Asks the gateway 23 real questions against the real Aconex test project
(find a drawing, get its PDF, search mail, preview a draft, refuse what it
should refuse, check the live site from outside) and prints a pass/fail
table, saved in `docs/test-runs/`. It takes about a minute.

It runs on a temporary Fly machine that deletes itself, never on the live one,
in reads-only mode: the outgoing check refuses even unsent drafts, so nothing
is saved or sent. The documents and people it looks for are in `FACTS` at the
top of `gateway/testrun.py`; change them for another company's test project.
