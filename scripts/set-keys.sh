#!/usr/bin/env bash
# Put the gateway's four keys into Fly secrets, typed once by the company's IT
# person. Nothing is shown on screen, written to a file or kept in the shell's
# history: each value goes straight from the keyboard to Fly.
#
#   scripts/set-keys.sh <fly app name>
set -euo pipefail

APP="${1:?Usage: scripts/set-keys.sh <fly app name>}"
command -v fly >/dev/null 2>&1 || command -v flyctl >/dev/null 2>&1 \
  || { echo "Install Fly's tool first: https://fly.io/docs/flyctl/install/" >&2; exit 1; }
FLY=$(command -v fly || command -v flyctl)

ask() {  # ask <NAME> <description>: reads a value without showing it
  local value=""
  while [ -z "$value" ]; do
    read -r -s -p "$2: " value; echo >&2
    value="$(printf '%s' "$value" | tr -d '[:space:]')"
    [ -n "$value" ] || echo "  (empty; try again)" >&2
  done
  printf '%s=%s\n' "$1" "$value"
}

echo "Setting keys for Fly app '$APP'. Typing is hidden. Paste each value and press Enter."
{
  ask ACONEX_CLIENT_ID     "Aconex API client ID"
  ask ACONEX_CLIENT_SECRET "Aconex API client secret"
  ask SIGNIN_CLIENT_ID     "Sign-in (Google/Microsoft) client ID"
  ask SIGNIN_CLIENT_SECRET "Sign-in (Google/Microsoft) client secret"
} | "$FLY" secrets import --stage -a "$APP" >/dev/null

echo "Done. Fly now holds the four keys (staged; they apply when the gateway is deployed)."
echo "Check the names only (never the values): $FLY secrets list -a $APP"
