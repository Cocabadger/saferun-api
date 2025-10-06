#!/bin/bash

# Example: Delete GitHub repository (IRREVERSIBLE - requires approval)

API_KEY="your_api_key_here"
GITHUB_TOKEN="your_github_token_here"
REPO="owner/repo"

echo "⚠️  WARNING: This will DELETE the repository permanently!"
echo "Repository: $REPO"
echo ""

# Step 1: Request dry-run (will ALWAYS require approval for delete)
RESPONSE=$(curl -s -X POST https://saferun-api.up.railway.app/v1/dry-run/github.repo.delete \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"token\": \"$GITHUB_TOKEN\",
    \"target_id\": \"$REPO\",
    \"reason\": \"Cleanup old repository\"
  }")

echo "Dry-run response:"
echo "$RESPONSE" | jq '.'

CHANGE_ID=$(echo "$RESPONSE" | jq -r '.change_id')
REQUIRES_APPROVAL=$(echo "$RESPONSE" | jq -r '.requires_approval')

echo ""
echo "Change ID: $CHANGE_ID"
echo "Requires approval: $REQUIRES_APPROVAL"

if [ "$REQUIRES_APPROVAL" = "true" ]; then
  echo ""
  echo "⚠️  APPROVAL REQUIRED - repository deletion is IRREVERSIBLE"
  echo "Approve URL: $(echo "$RESPONSE" | jq -r '.approve_url')"
  echo ""
  echo "Waiting for approval..."
  echo "Press Enter after approving..."
  read
  
  # Step 2: Apply the change (delete repository)
  APPLY_RESPONSE=$(curl -s -X POST https://saferun-api.up.railway.app/v1/apply \
    -H "X-API-Key: $API_KEY" \
    -H "Content-Type: application/json" \
    -d "{
      \"change_id\": \"$CHANGE_ID\",
      \"approval\": true
    }")
  
  echo "Apply response:"
  echo "$APPLY_RESPONSE" | jq '.'
  
  STATUS=$(echo "$APPLY_RESPONSE" | jq -r '.status')
  if [ "$STATUS" = "applied" ]; then
    echo ""
    echo "✅ Repository deleted successfully"
    echo "⚠️  This operation CANNOT be undone - repository is permanently deleted"
  else
    echo ""
    echo "❌ Failed to delete repository"
  fi
else
  echo ""
  echo "ℹ️  No approval required (shouldn't happen for delete)"
fi
