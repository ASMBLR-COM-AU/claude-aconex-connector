# Stage 1: Skeleton

**Job:** prove the gateway can be built, tested and hosted, before it touches
Aconex or holds any secret.

## What was built

- `gateway/server.py`: the gateway, built with the official MCP library
  (MCP is the standard way Claude talks to outside tools). It offers one tool,
  `ping`, and a `/health` page.
- It only answers to its own address (`PUBLIC_HOST`) and localhost. Requests
  claiming to be for any other address are refused.
- `Dockerfile` and `fly.toml`: how Fly.io runs it. It runs as a normal user,
  not root, and stops itself when idle to save money.
- `.github/workflows/ci.yml`: GitHub runs the tests on every change, and
  deploys to Fly from `main` once they pass. The Fly deploy token lives in
  GitHub's secrets, scoped to this one app.

## Done when

- [x] Tests pass: the menu holds only `ping`, `ping` answers, `/health` answers,
      and an unknown address is refused.
- [ ] Deployed on Fly and `https://<app>.fly.dev/health` answers.
- [x] No keys anywhere.

## Decisions

- **Stateless mode:** each request stands alone, so a restarted or stopped
  machine loses nothing.
- **MCP library version pinned** (`mcp==2.3.0`), so an update can't change
  behaviour without us choosing it.

## For the video

Show the tests passing, then the `/health` page on the live address. Don't show
the Fly dashboard's tokens.

## What went wrong

Deploying straight from the Claude session failed: Fly's image builder uses a
connection type the session's network proxy doesn't allow. We moved deploys to
GitHub Actions instead, which is where they were going anyway: from stage 5 a
person approves each change and GitHub deploys it.
