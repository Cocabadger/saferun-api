#!/usr/bin/env bash
set -euo pipefail

SAFERUN_API_URL="https://saferun-api.up.railway.app"
API_KEY="${SAFERUN_API_KEY:?set SAFERUN_API_KEY}"
CHANGE_ID="${1:?usage: $0 change_id}"

curl -sS -X POST "$SAFERUN_API_URL/v1/apply" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"change_id\": \"$CHANGE_ID\", \"approval\": true}" | jq
