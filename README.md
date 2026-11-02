# Claude Aconex Gateway

A small app that lets Claude work in Oracle Aconex safely. It holds the Aconex
keys, gives Claude a fixed menu of actions, and checks every request. Claude
never sees the keys.

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
