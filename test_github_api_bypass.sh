#!/usr/bin/env bash
set -euo pipefail

# Это тест обхода CLI - делаем force push через GitHub API напрямую
# Должен сработать GitHub App webhook (Level 3 Protection)

GITHUB_TOKEN="${GITHUB_TOKEN:?Set GITHUB_TOKEN}"
OWNER="Cocabadger"
REPO="test-sf-v01"
BRANCH="main"

echo "🚀 Testing GitHub API bypass - Force push to $OWNER/$REPO#$BRANCH"
echo "This should trigger GitHub App webhook..."
echo ""

# Шаг 1: Получаем текущий SHA main ветки
echo "📍 Step 1: Get current main branch SHA..."
CURRENT_SHA=$(curl -s \
  -H "Authorization: token $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/$OWNER/$REPO/git/refs/heads/$BRANCH" | jq -r '.object.sha')

echo "Current SHA: $CURRENT_SHA"
echo ""

# Шаг 2: Получаем parent commit (на один коммит назад)
echo "📝 Step 2: Get parent commit to force-rewrite history..."
PARENT_SHA=$(curl -s \
  -H "Authorization: token $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/$OWNER/$REPO/git/commits/$CURRENT_SHA" | jq -r '.parents[0].sha')

echo "Parent SHA: $PARENT_SHA"

# Создаем коммит на базе parent (это сделает force push, т.к. переписывает историю)
TREE_SHA=$(curl -s \
  -H "Authorization: token $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/$OWNER/$REPO/git/commits/$PARENT_SHA" | jq -r '.tree.sha')

NEW_COMMIT=$(curl -s -X POST \
  -H "Authorization: token $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/$OWNER/$REPO/git/commits" \
  -d "{
    \"message\": \"test: REAL force push via API (rewrites history)\",
    \"tree\": \"$TREE_SHA\",
    \"parents\": [\"$PARENT_SHA\"]
  }")

NEW_SHA=$(echo "$NEW_COMMIT" | jq -r '.sha')
echo "New commit SHA: $NEW_SHA (based on parent, will rewrite history)"
echo ""

# Шаг 3: Force update ref (это обойдет CLI и триггернет webhook!)
echo "💥 Step 3: FORCE PUSH via GitHub API (bypassing CLI)..."
RESULT=$(curl -s -X PATCH \
  -H "Authorization: token $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/$OWNER/$REPO/git/refs/heads/$BRANCH" \
  -d "{
    \"sha\": \"$NEW_SHA\",
    \"force\": true
  }")

echo "$RESULT" | jq

echo ""
echo "✅ Force push completed via API!"
echo "🎯 Check Railway logs for GitHub webhook event..."
echo "🔔 Check Slack for notification..."
