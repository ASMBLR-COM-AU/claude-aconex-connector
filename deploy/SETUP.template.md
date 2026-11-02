# Aconex Connector setup: {slug}

Work through this with the company's IT person. Tick each box as you go.
It takes about an hour, most of it waiting on admin screens.

**The gateway's address:** {public_url}
**Approved projects:** {projects}
**Approved people:** {emails} {domains}

## Golden rules

- **Keys are typed by the company's IT person, straight into Fly.** Never
  paste a key into a chat, an email, a document or a ticket, and never type
  one into anyone else's computer.
- **Start small:** one test project and a few named people. Widen later by
  editing `fly.toml` and deploying again.
- **The company owns everything:** the Fly account, the Aconex account and the
  sign-in app are all theirs. Whoever installs it doesn't keep access.

## Who's needed

- [ ] Someone who can create a **Fly.io** account for the company and add a
      payment card (it costs a few US dollars a month).
- [ ] The company's **Aconex organisation administrator**.
- [ ] A **{signin}** administrator, to register the sign-in app.
- [ ] An **Owner** of the company's **Claude Team or Enterprise** plan.

## 1. Aconex: an account for the gateway, and its key

The Aconex administrator:

- [ ] Creates a **plain Aconex user** for the connector (e.g. "Claude
      Connector"). Not an administrator. It sees exactly what this user can see.
- [ ] Adds that user to the approved project(s) ({projects}) with a role that
      can **read documents and mail** and **create mail** (for drafts; the
      gateway can never send). Nothing more.
- [ ] Registers a **USERBOUND API client** bound to that user (in Oracle's
      Lobby, under OAuth clients), and notes its **client ID** and **secret**
      somewhere private. *(Exact screen names: confirm with the Aconex admin.)*

## 2. Sign-in: the company's own login
<!-- if google -->
In Google Cloud, with a Google Workspace admin account:

- [ ] Create a project called "Aconex Connector".
- [ ] **Google Auth Platform** (or **APIs & Services › OAuth consent
      screen**): app name "Aconex Connector", audience **Internal**.
- [ ] **Clients › Create client**: type **Web application**, name "Aconex
      Gateway", **Authorised redirect URI** exactly:
      `{public_url}/auth/callback`
- [ ] Keep the **client ID** and **client secret** private for step 4.
<!-- end --><!-- if microsoft -->
In the Microsoft Entra admin centre:

- [ ] **App registrations › New registration**: name "Aconex Connector",
      accounts in **this organisational directory only**, redirect URI (Web)
      exactly: `{public_url}/auth/callback`
- [ ] **Certificates & secrets › New client secret.** Keep the **application
      (client) ID** and the **secret value** private for step 4.
- [ ] Check the tenant ID on the overview page matches the one in `fly.toml`
      (`SIGNIN_ISSUER`).
<!-- end -->
## 3. Fly: the company's own server

On the IT person's computer, in a copy of the gateway's code:

- [ ] Install Fly's tool (https://fly.io/docs/flyctl/install/) and sign in to
      the **company's** Fly account: `fly auth login`
- [ ] Create the app: `fly apps create {app}`
- [ ] Create the encrypted storage for the audit log, with daily backups kept
      5 days:
      `fly volumes create gateway_data --app {app} --region {region} --size 1 --snapshot-retention 5 --yes`

## 4. Keys: typed once, straight into Fly

- [ ] Run `scripts/set-keys.sh {app}` and type the four values when asked
      (Aconex client ID and secret, sign-in client ID and secret). Nothing is
      shown on screen or saved in a file.

## 5. Start it

- [ ] `fly deploy . --config deploy-{slug}/fly.toml --ha=false --remote-only`
- [ ] Check {public_url}/health says `{"status":"ok"}`.

## 6. Claude

The Claude Owner, in **Admin settings**:

- [ ] **Connectors › Add custom connector**: URL `{public_url}/mcp`,
      sign in with OAuth, client **Register automatically**.
- [ ] **Capabilities:** code execution **on**; allowed domains: add
      `{app}.fly.dev` (so Claude can hand over real PDFs). Don't allow all
      domains.
- [ ] If Claude offers per-tool settings for the connector, set `save_draft`
      to **ask every time**.
- [ ] Each approved person: **Settings › Connectors › Connect**, and sign in
      with their work account.

## 7. Test run

- [ ] Fill in `deploy-{slug}/testrun.json` with real facts from the test
      project (a drawing number, a word from its title, a word printed inside
      documents, a surname in the directory, the company's name in Aconex).
- [ ] Run `scripts/test-run.sh deploy-{slug}` and keep the report. All checks
      should pass.

## 8. Sign-off

- [ ] An approved person asked Claude to find a drawing and got the real PDF.
- [ ] An approved person asked Claude to draft a reply, opened the draft in
      Aconex, and **sent it themselves**.
- [ ] Someone **not** approved tried to connect and was refused.
- [ ] The company's IT person knows how to switch it off:
      `fly secrets set GATEWAY_OFF=1 -a {app}` (see the runbook).
- [ ] Whoever installed it has been **removed** from the company's Fly
      account.

## Later

- **Updates:** the company chooses when. In the gateway's code folder:
  `git pull`, read what changed, run the tests, then step 5 again.
- **More projects or people:** edit `deploy-{slug}/fly.toml`, then step 5.
- **The audit log, the off switch, rotating keys:** see `docs/runbook.md`.
