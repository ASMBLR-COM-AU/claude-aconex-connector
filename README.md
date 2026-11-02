# Aconex Connector for Claude

A Claude connector that lets a company's staff work in Oracle Aconex safely.
Its server (called **the gateway** in the code) holds the company's Aconex key,
gives Claude a fixed menu of actions, and checks every request. Claude never
sees the key.

## Skill or connector?

ASMBLR makes two separate products that let Claude work in Oracle Aconex.
They don't share code, and neither needs the other.

| | **Aconex skill** | **Aconex Connector** |
|---|---|---|
| What it is | Instructions plus a script that Claude runs on the person's own computer | A small server the company hosts; Claude connects to it like any other connector |
| Where it lives | [ASMBLR-COM-AU/aconex-skill](https://github.com/ASMBLR-COM-AU/aconex-skill) (open source) | ASMBLR-COM-AU/claude-aconex-connector (private; ask [ASMBLR](https://asmblr.com.au)) |
| Who holds the Aconex key | Each person, in a file or setting on their computer | Only the company's server (in its own Fly.io account); Claude and staff never see it |
| Works in | Claude Code, Cowork, and the Claude apps with code execution and Aconex allowed in network settings | Claude on the web, desktop and mobile, Claude Code and Cowork, with no network settings beyond the connector's address |
| Sign-in | None: whoever has the key file | Each person signs in with their work Google or Microsoft account; only approved people get in |
| Company controls | The script's built-in limits | Approved people and projects, an audit log with a name on every action, an off switch, per-person limits |
| Set up by | One person, about 10 minutes | The company's IT, about an hour, once |
| Best for | One person or a small team trying it out | A company rolling it out to staff |
| Can it send mail? | No: unsent drafts only | No: unsent drafts only |

In the Connector's code and technical docs, its server is called **the gateway**.


- **The plan and every decision:** [PLAN.md](PLAN.md)
- **What it can and can't do, and the proof:** [docs/security.md](docs/security.md)
- **Operating it:** [docs/runbook.md](docs/runbook.md)
- **What each build stage did:** [docs/stages/](docs/stages/)

## Current stage

Stages 1 to 8 done: projects, people, the document register, real files (PDF,
DWG) on command, whole-project mail, and unsent drafts with the person's
signature, behind company sign-in (Google or Microsoft), an audit log,
approved projects and people, an off switch and request pacing. Security pass
and independent review fixes in 0.9.x. Running against the real Aconex on one
test project with a testing key; the latest test run is in
[docs/test-runs/latest.md](docs/test-runs/latest.md).

## Run it on your computer

```bash
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest          # run the tests
.venv/bin/python -m gateway         # start it on http://localhost:8080
```

Sign-in is always on. To try it on your own computer without sign-in, set
`GATEWAY_NO_SIGNIN=1` first; never set it on Fly.

The menu Claude sees is at `/mcp`; `/health` says whether it's running.

## Set it up for a company

Each company gets its own copy in its **own** Fly account, so it owns its
Aconex key and nobody else ever sees it.

```bash
python3 scripts/new_company.py     # asks a few questions, writes deploy-<company>/
```

Then work through `deploy-<company>/SETUP.md` with the company's IT person:
Aconex account and key, sign-in app, Fly app, keys typed once with
`scripts/set-keys.sh`, deploy, Claude connector settings, a test run with
`scripts/test-run.sh deploy-<company>`, and sign-off.

## Deploy (this repo's own gateway)

Runs on Fly.io (see `fly.toml`). GitHub deploys it automatically whenever
`main` changes and the tests pass, using the `FLY_API_TOKEN` repository secret
(a deploy token for this one Fly app).
