# Claude Aconex Gateway

A small app that lets Claude work in Oracle Aconex safely. It holds the Aconex
keys, gives Claude a fixed menu of actions, and checks every request. Claude
never sees the keys.

- **The plan and every decision:** [PLAN.md](PLAN.md)
- **What each build stage did:** [docs/stages/](docs/stages/)

## Current stage

Stage 6 done: read-only tools for projects, people and the document register,
plus the real files (PDF, DWG) on command, behind company sign-in (Google or
Microsoft), an audit log, approved projects and people, an off switch and
request pacing. Running against the real Aconex on one test project with a
testing key. See [docs/stages/](docs/stages/) for each stage and
[docs/runbook.md](docs/runbook.md) for operating it.

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

## Deploy

Runs on Fly.io (see `fly.toml`). GitHub deploys it automatically whenever
`main` changes and the tests pass, using the `FLY_API_TOKEN` repository secret
(a deploy token for this one Fly app).
