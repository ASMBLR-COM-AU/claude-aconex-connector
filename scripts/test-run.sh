#!/usr/bin/env bash
# Test run against the real Aconex, read-only, on a TEMPORARY Fly machine
# (never the live one, which is small and serves real people).
#
#   scripts/test-run.sh                       # this repo's own gateway (fly.toml)
#   scripts/test-run.sh deploy-<company>      # a company's gateway (its fly.toml and testrun.json)
#
# The report is printed and saved in docs/test-runs/ (or the company's folder).
#
# Needs flyctl logged in to the gateway's Fly app. The temporary machine uses
# the same image as the live gateway, gets the Aconex key from Fly secrets
# like the live one does, runs `python -m gateway.testrun` in reads-only mode
# (the outgoing check refuses even unsent drafts) and deletes itself.
set -euo pipefail

cd "$(dirname "$0")/.."
# Windows (Git Bash) usually has "python" or "py" rather than "python3".
PY="$(command -v python3 || command -v python || command -v py)" \
  || { echo "Install Python 3 first." >&2; exit 2; }
FLYCTL="$(command -v flyctl || command -v fly)" \
  || { echo "Install Fly's tool first: https://fly.io/docs/flyctl/install/" >&2; exit 2; }
FOLDER="${1:-}"
CONFIG="${FOLDER:+$FOLDER/}fly.toml"
REPORTS="${FOLDER:-docs/test-runs}"
[ -f "$CONFIG" ] || { echo "No $CONFIG" >&2; exit 2; }

setting() { grep -E "^\s*$1\s*=" "$CONFIG" | head -1 | sed -E 's/^[^=]*=\s*"([^"]*)".*/\1/'; }
APP="$(setting app)"
FACTS=""
if [ -n "$FOLDER" ]; then
  [ -f "$FOLDER/testrun.json" ] || { echo "No $FOLDER/testrun.json" >&2; exit 2; }
  grep -q "FILL IN" "$FOLDER/testrun.json" && { echo "Fill in $FOLDER/testrun.json first." >&2; exit 2; }
  FACTS="$("$PY" -c 'import json,sys; print(json.dumps(json.load(open(sys.argv[1]))))' "$FOLDER/testrun.json")"
fi

IMAGE=$("$FLYCTL" machine list -a "$APP" --json | "$PY" -c \
  'import json,sys; ms=[m for m in json.load(sys.stdin) if not m["name"].startswith("testrun")]; print(ms[0]["config"]["image"])')
NAME="testrun-$(date +%s)"
echo "Image: $IMAGE"
echo "Starting temporary machine $NAME ..."

ID=$("$FLYCTL" machine run "$IMAGE" -a "$APP" --region syd --vm-memory 512 --restart no --rm \
  --name "$NAME" --detach \
  --env PYTHONUNBUFFERED=1 \
  --env ALLOWED_PROJECTS="$(setting ALLOWED_PROJECTS)" \
  --env ALLOWED_EMAILS="$(setting ALLOWED_EMAILS)" \
  --env ACONEX_WEB_URL="$(setting ACONEX_WEB_URL)" \
  --env TESTRUN_LIVE_URL="https://$(setting PUBLIC_HOST)" \
  ${FACTS:+--env "TESTRUN_FACTS=$FACTS"} \
  -- python -m gateway.testrun 2>&1 | tee /dev/stderr | grep -oE 'Machine ID: [0-9a-f]+' | awk '{print $3}')
[ -n "$ID" ] || { echo "Couldn't start the temporary machine." >&2; exit 2; }

echo "Waiting for the test run to finish (machine $ID) ..."
LOG=$(mktemp)
for _ in $(seq 1 60); do
  sleep 10
  "$FLYCTL" logs -a "$APP" -i "$ID" --no-tail > "$LOG" 2>/dev/null || true
  grep -q "TEST RUN:" "$LOG" && break
done

grep -q "TEST RUN:" "$LOG" || { echo "No result after 10 minutes. Log so far:" >&2; cat "$LOG" >&2; exit 2; }

mkdir -p "$REPORTS"
OUT="$REPORTS/test-run-$(date -u +%Y-%m-%d-%H%M).md"
# Fly prefixes each log line with colours, time, machine, region and level
# ("... app[id] syd [info]"); remove exactly that, then keep only the report.
sed -E 's/\x1b\[[0-9;]*m//g; s/^[^]]*\] [a-z]+ \[[a-z]+\]//' "$LOG" | sed -n '/=====REPORT=====/,/=====END=====/p' | sed '1d;$d' > "$OUT"
cp "$OUT" "$REPORTS/latest.md"
cat "$OUT"
echo
grep -o "TEST RUN: .*" "$LOG" | tail -1
grep -q "TEST RUN: \([0-9]*\)/\1 passed" "$LOG"
