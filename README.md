# Claude Aconex Gateway

A small app that lets Claude work in Oracle Aconex safely. It holds the Aconex
keys, gives Claude a fixed menu of actions, and checks every request. Claude
never sees the keys.

- **The plan and every decision:** [PLAN.md](PLAN.md)
- **What each build stage did:** [docs/stages/](docs/stages/)

## Current stage

Stage 1, the skeleton: one test tool (`ping`) and a `/health` page. No Aconex
access and no secrets.

## Run it on your computer

```bash
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest          # run the tests
.venv/bin/python -m gateway         # start it on http://localhost:8080
```

The menu Claude sees is at `/mcp`; `/health` says whether it's running.

## Deploy

Runs on Fly.io (see `fly.toml`). GitHub deploys it automatically whenever
`main` changes and the tests pass, using the `FLY_API_TOKEN` repository secret
(a deploy token for this one Fly app).
