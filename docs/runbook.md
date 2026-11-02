# Runbook

How IT operates the gateway. Every command runs on a computer with the Fly
command-line tool (`fly`), signed in to the Fly organisation that owns the
`aconex-gateway` app.

## Turn the gateway off (emergency)

```bash
fly secrets set GATEWAY_OFF=1 -a aconex-gateway
```

The machine restarts in a few seconds. Every Aconex tool then answers "switched
off by IT" and nothing reaches Aconex. `https://aconex-gateway.fly.dev/health`
shows `"switched_off": true`.

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
are refused, and `list_projects` doesn't show them.

## Request pacing

Aconex allows 5 requests a second and 10 at once for the whole company. The
gateway uses at most 3 a second and 4 at once by default, leaving room for
other systems. Change with the `ACONEX_PER_SECOND` and `ACONEX_AT_ONCE`
settings if IT agrees a different share.
