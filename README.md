# SafeRun

**AI Safety Middleware** - Stop AI agents from breaking production.

SafeRun intercepts high-risk operations (like deleting repositories, modifying CI/CD pipelines, or exposing secrets) and requires human approval before execution.

## Why SafeRun?

AI agents are powerful but can make catastrophic mistakes:
- 🔥 Deleting production repositories
- 🔐 Exposing GitHub Actions secrets
- ⚙️ Modifying CI/CD workflows to run malicious code
- 🚨 Transferring repositories to external organizations
- 👁️ Making private repos public (permanent data leak)

**SafeRun catches these before they happen.**

## How It Works

1. **AI agent requests a dangerous operation** (e.g., delete repo)
2. **SafeRun scores the risk** (0.0 to 10.0 scale)
3. **High-risk operations (8.5+) require approval** via Slack/webhook
4. **You approve or reject** with one click
5. **SafeRun executes or blocks** the operation
6. **Most operations can be reverted** if something goes wrong

## Protected Operations

### GitHub (22+ operations covered)

**Critical Operations** (risk 8.5-10.0, require approval):
- 🚨 Repository transfer (IRREVERSIBLE)
- 🔑 GitHub Actions secrets (create/update/delete)
- ⚙️ Workflow file modifications (arbitrary code execution risk)
- 🛡️ Branch protection rules (bypass code review)
- 👁️ Repository visibility changes (private→public is permanent)

**Standard Operations** (risk 5.0-8.0):
- Repository archive/unarchive
- Branch deletion/restoration
- Pull request bulk operations
- Force push protection (via CLI hooks)

### Coming Soon
- Notion, Slack, Airtable, Google Drive, Google Sheets

## Security Features

- ✅ **Risk scoring engine** - Automatically detects dangerous operations
- ✅ **Token encryption** - AES-256-GCM encryption for all stored credentials
- ✅ **User isolation** - Users can only access their own tokens
- ✅ **Revert mechanism** - Undo operations that went wrong
- ✅ **Audit trail** - Full history of all operations
- ✅ **CLI secrets scanner** - Prevents credential leaks in git commits

---

## Quick Start

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Set environment variables
```bash
cp .env.example .env
# Edit .env with your settings
```

### 3. Run the server
```bash
uvicorn saferun.app.main:app --host 0.0.0.0 --port 8500
```

## API Usage

### 1. Get API Key
```bash
curl -X POST http://localhost:8500/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "your@email.com"}'
```

### 2. Use SafeRun API
```bash
# Dry run for GitHub repo archive
curl -X POST http://localhost:8500/v1/dry-run/github.repo.archive \
  -H "X-API-Key: your_api_key" \
  -H "Content-Type: application/json" \
  -d '{
    "token": "users_github_token",
    "target_id": "owner/repo"
  }'
```

### 3. Configure Notifications (Slack/Webhooks)

**Get current settings:**
```bash
curl -X GET https://saferun.up.railway.app/v1/settings/notifications \
  -H "X-API-Key: your_api_key"
```

**Configure Slack** (see [SLACK_SETUP.md](SLACK_SETUP.md) for full guide):
```bash
curl -X PUT https://saferun.up.railway.app/v1/settings/notifications \
  -H "X-API-Key: your_api_key" \
  -H "Content-Type: application/json" \
  -d '{
    "slack_bot_token": "xoxb-YOUR-BOT-TOKEN",
    "slack_channel": "#saferun-alerts",
    "slack_enabled": true
  }'
```

**Test notifications:**
```bash
curl -X POST https://saferun.up.railway.app/v1/settings/notifications/test/slack \
  -H "X-API-Key: your_api_key"
```

**Configure custom webhooks:**
```bash
curl -X PUT https://saferun.up.railway.app/v1/settings/notifications \
  -H "X-API-Key: your_api_key" \
  -H "Content-Type: application/json" \
  -d '{
    "webhook_url": "https://your-webhook.com/saferun",
    "webhook_secret": "your_secret_for_hmac_validation",
    "webhook_enabled": true
  }'
```

**Notification features:**
- ✅ Per-user settings stored in database
- ✅ Interactive Slack buttons (approve/reject)
- ✅ HMAC signature validation for webhooks
- ✅ Fallback to global admin settings

---

## Deployment

### Railway (Recommended)

1. Push to GitHub
2. Connect repo to Railway
3. Add environment variables:
   - `SR_STORAGE_BACKEND=sqlite`
   - `SR_SQLITE_PATH=/data/saferun.db`
4. Add Railway Volume mounted at `/data`
5. Deploy!

### Render

1. Create new Web Service
2. Connect GitHub repo
3. Build command: `pip install -r requirements.txt`
4. Start command: `uvicorn saferun.app.main:app --host 0.0.0.0 --port $PORT`

---

## Environment Variables

### Core Settings
- `PORT` - Server port (default: 8500)
- `SR_LOG_LEVEL` - Log level (info/debug)
- `SR_STORAGE_BACKEND` - Storage type (sqlite or postgres)
- `SR_SQLITE_PATH` - Database path (default: `/data/saferun.db`)
- `DATABASE_URL` - PostgreSQL connection URL (for production)
- `SR_FREE_TIER_LIMIT` - API call limit (default: 100, set `-1` to disable)

### Provider Settings
- `SR_GITHUB_API_BASE` - GitHub API base URL (optional)
- `SR_GITHUB_USER_AGENT` - Custom user agent (optional)

### Global Notification Settings (optional, for admin fallback)
- `NOTIFY_TIMEOUT_MS` - Webhook timeout (default: 2000)
- `NOTIFY_RETRY` - Retry count (default: 1)
- `SLACK_BOT_TOKEN` - Slack Bot Token (optional)
- `SLACK_CHANNEL` - Default Slack channel (default: #saferun-alerts)
- `SLACK_WEBHOOK_URL` - Slack Webhook URL (optional)
- `GENERIC_WEBHOOK_URL` - Generic webhook URL (optional)
- `GENERIC_WEBHOOK_SECRET` - Webhook signature secret (optional)

**Note:** Users can configure their own notification settings via API, which override these global settings.

---

## Pricing

- **Free Tier**: First 1000 API calls FREE
- Set `SR_FREE_TIER_LIMIT=-1` to disable rate limiting

---

## Production Info

- **Deployed**: https://saferun-api.up.railway.app
- **Health**: `/healthz` endpoint
- **Version**: 0.20.0
- **Support**: [GitHub Issues](https://github.com/Cocabadger/saferun-api/issues)
