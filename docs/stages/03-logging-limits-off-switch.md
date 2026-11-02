# Stage 3: Logging, limits and off switch

**Job:** put IT's controls around every tool before any real person or real
key is connected.

## What was built

- `gateway/guard.py`
  - **Audit log:** one row per tool call: time, person, tool, project, the
    arguments, outcome (ok, error, blocked, crash) and how long it took. Kept
    in a small database file on an encrypted Fly volume (daily snapshots, 5
    days) and echoed to Fly's live log. The person shows as "unknown" until
    sign-in arrives in stage 4.
  - **Approved projects:** `ALLOWED_PROJECTS` in `fly.toml`. Empty means none.
    Changing it goes through GitHub, so a person approves each change.
  - **Off switch:** `GATEWAY_OFF`, set as a Fly secret so IT can flip it in
    seconds without a code change.
- `gateway/tools/__init__.py`: every Aconex tool is registered through one
  wrapper that applies the off switch and project check *before* the tool runs
  and writes the audit row *after*. A tool can't opt out.
- `gateway/aconex/client.py`: **request pacing.** At most 3 requests a second
  and 4 at once (Aconex's limit is 5 and 10 for the whole company). Extra
  requests wait their turn. When Aconex says it's busy, the gateway waits 5
  seconds, then 15, then gives up with a plain message.
- `docs/runbook.md`: how IT turns it off, reads the log and approves projects.
- The container starts as root only to hand the storage volume to a normal
  user, then switches to that user before serving anything.

## Done when

- [x] Every request appears in the log, including blocked ones (tests).
- [x] A burst of requests is queued, not refused: 6 at once go through, never
      more than the limit in flight, spaced to the rate (test).
- [x] Flipping the switch stops every Aconex tool, and nothing reaches Aconex
      (test). `/health` still answers and says it's off.
- [x] An unapproved project never reaches Aconex (test).
- [x] Live (2 Nov 2026): a call to an unapproved project was refused, and both
      calls appeared as audit lines in Fly's log.
- [ ] Live: the log file survives a restart. Needs `fly ssh` (see runbook),
      which this build session can't reach; covered by a test meanwhile.

## Decisions

- **Audit log location:** a small database file on Fly, not an outside service.
  Cheap (cents a month) and keeps everything in one place.
- **Default deny:** with no approved projects, nothing works. Projects are
  added at stage 5.
- **Arguments are logged** (search words, document numbers) so a question can be
  traced. Results are not logged.

## For the video

Show the off switch: set it, call a tool, show the "switched off by IT" answer
and the "blocked" log line, then unset it.
