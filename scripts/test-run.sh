#!/usr/bin/env bash
# Test run against the real Aconex, read-only, on a TEMPORARY Fly machine
# (never the live one, which is small and serves real people).
#
#   scripts/test-run.sh            # report printed and saved to docs/test-runs/
#
# Needs flyctl logged in to the gateway's Fly app. The temporary machine uses
# the same image as the live gateway, gets the Aconex key from Fly secrets
# like the live one does, runs `python -m gateway.testrun` in reads-only mode
# (the outgoing check refuses even unsent drafts) and deletes itself.
set -euo pipefail

APP="${APP:-aconex-gateway}"
cd "$(dirname "$0")/.."

setting() { grep -E "^\s*$1\s*=" fly.toml | head -1 | sed -E 's/^[^=]*=\s*"([^"]*)".*/\1/'; }

IMAGE=$(flyctl machine list -a "$APP" --json | python3 -c \
  'import json,sys; ms=[m for m in json.load(sys.stdin) if not m["name"].startswith("testrun")]; print(ms[0]["config"]["image"])')
NAME="testrun-$(date +%s)"
echo "Image: $IMAGE"
echo "Starting temporary machine $NAME ..."

ID=$(flyctl machine run "$IMAGE" -a "$APP" --region syd --vm-memory 512 --restart no --rm \
  --name "$NAME" --detach \
  --env PYTHONUNBUFFERED=1 \
  --env ALLOWED_PROJECTS="$(setting ALLOWED_PROJECTS)" \
  --env ALLOWED_EMAILS="$(setting ALLOWED_EMAILS)" \
  --env ACONEX_WEB_URL="$(setting ACONEX_WEB_URL)" \
  -- python -m gateway.testrun 2>&1 | tee /dev/stderr | grep -oE 'Machine ID: [0-9a-f]+' | awk '{print $3}')
[ -n "$ID" ] || { echo "Couldn't start the temporary machine." >&2; exit 2; }

echo "Waiting for the test run to finish (machine $ID) ..."
LOG=$(mktemp)
for _ in $(seq 1 60); do
  sleep 10
  flyctl logs -a "$APP" -i "$ID" --no-tail > "$LOG" 2>/dev/null || true
  grep -q "TEST RUN:" "$LOG" && break
done

grep -q "TEST RUN:" "$LOG" || { echo "No result after 10 minutes. Log so far:" >&2; cat "$LOG" >&2; exit 2; }

mkdir -p docs/test-runs
OUT="docs/test-runs/$(date -u +%Y-%m-%d-%H%M).md"
# Fly prefixes each log line with colours, time, machine, region and level
# ("... app[id] syd [info]"); remove exactly that, then keep only the report.
sed -E 's/\x1b\[[0-9;]*m//g; s/^[^]]*\] [a-z]+ \[[a-z]+\]//' "$LOG" | sed -n '/=====REPORT=====/,/=====END=====/p' | sed '1d;$d' > "$OUT"
cp "$OUT" docs/test-runs/latest.md
cat "$OUT"
echo
grep -o "TEST RUN: .*" "$LOG" | tail -1
grep -q "TEST RUN: \([0-9]*\)/\1 passed" "$LOG"
