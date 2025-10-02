#!/usr/bin/env bash
set -euo pipefail

SAFERUN_API_URL="https://saferun-api.up.railway.app"
API_KEY="${SAFERUN_API_KEY:?set SAFERUN_API_KEY}"
REPO="${1:?usage: $0 owner/repo}"
BRANCH="${2:?usage: $0 owner/repo branch}"
TOKEN="${GITHUB_TOKEN:?set GITHUB_TOKEN}"

curl -sS -X POST "$SAFERUN_API_URL/v1/dry-run/github.branch.delete" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"token\": \"$TOKEN\", \"target_id\": \"$REPO#$BRANCH\"}" | jq
