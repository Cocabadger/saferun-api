# SafeRun Production

AI Safety Middleware - Prevent destructive actions by AI agents

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

### 3. Enable Webhook Notifications (NEW!)
```bash
# Add webhook_url to get real-time notifications
curl -X POST http://localhost:8500/v1/dry-run/github.repo.archive \
  -H "X-API-Key: your_api_key" \
  -H "Content-Type: application/json" \
  -d '{
    "token": "users_github_token",
    "target_id": "owner/repo",
    "webhook_url": "https://your-webhook-handler.com/saferun"
  }'
```

Webhooks are sent for:
- **dry_run** - High-risk actions requiring approval
- **applied** - Actions executed
- **reverted** - Actions rolled back

See [WEBHOOK_GUIDE.md](../WEBHOOK_GUIDE.md) for integration examples.

### 4. Configure User Notifications (Slack/Email/Webhooks)

Each user can configure their own notification channels via API. Notifications will be sent to user-specific channels when high-risk actions require approval.

#### Get current notification settings
```bash
curl -X GET https://saferun.up.railway.app/v1/settings/notifications \
  -H "X-API-Key: your_api_key"
```

#### Configure Slack notifications

**See [SLACK_SETUP.md](SLACK_SETUP.md) for complete step-by-step guide!**

Quick setup:
```bash
curl -X PUT https://saferun.up.railway.app/v1/settings/notifications \
  -H "X-API-Key: your_api_key" \
  -H "Content-Type: application/json" \
  -d '{
    "slack_bot_token": "xoxb-YOUR-BOT-TOKEN",
    "slack_channel": "#saferun-alerts",
    "slack_enabled": true,
    "email_enabled": false
  }'
```

#### Test Slack notifications
```bash
curl -X POST https://saferun.up.railway.app/v1/settings/notifications/test/slack \
  -H "X-API-Key: your_api_key"
```

#### Configure Custom Webhooks
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

#### Reset notification settings to defaults
```bash
curl -X DELETE https://saferun.up.railway.app/v1/settings/notifications \
  -H "X-API-Key: your_api_key"
```

**Features:**
- ✅ Per-user notification settings stored in database
- ✅ Interactive Slack buttons for approve/reject (when using Bot Token)
- ✅ Custom webhooks with HMAC signature validation
- ✅ Fallback to global admin settings if user settings not configured

## What SafeRun Protects

### ✅ GitHub (Production Ready)

- **Repository operations**: 
  - Archive/unarchive with full revert capability
  - ⚠️ **DELETE repository protection** (IRREVERSIBLE - requires approval)
- **Branch protection**: Delete/restore branches safely  
- **Pull request management**: Bulk close/reopen PRs
- **CLI integration**: Git hooks for force push protection
- **Webhook notifications**: Real-time alerts for all operations
- **Rate limiting**: Configurable per-API-key limits (default: 1000 req/hour)

### 🔜 Coming Soon

Additional platforms after MVP testing:
- Notion (page operations)
- Slack (channel operations)
- Airtable, Google Drive, Google Sheets

Request new integrations via [GitHub Issues](https://github.com/Cocabadger/saferun-api/issues)

---

## How You Get Notified

SafeRun sends approval requests via:

- 💬 **Slack** - Interactive approve/reject buttons in your Slack channels
- 🔗 **Webhooks** - Custom webhook integration with HMAC signature validation

See [SLACK_SETUP.md](SLACK_SETUP.md) for Slack configuration.

## Deployment

### Railway (Recommended)

1. Push to GitHub
2. Connect repo to Railway
3. Add environment variables in Railway dashboard
   - `SR_STORAGE_BACKEND=sqlite`
   - `SR_SQLITE_PATH=/data/saferun.db`
4. Add a Railway Volume mounted at `/data` (Service → Settings → Volumes)
5. Deploy!

### Render

1. Create new Web Service
2. Connect GitHub repo
3. Build command: `pip install -r requirements.txt`
4. Start command: `uvicorn saferun.app.main:app --host 0.0.0.0 --port $PORT`

## Environment Variables

### Core Settings
- `PORT`: Server port (default: 8500)
- `SR_LOG_LEVEL`: Log level (info/debug)
- `SR_STORAGE_BACKEND`: Storage type (sqlite or postgres)
- `SR_SQLITE_PATH`: Database path (default `/data/saferun.db` when using a Railway Volume; set to `data/saferun.db` for local development)
- `DATABASE_URL`: PostgreSQL connection URL (for production deployments)
- `SR_FREE_TIER_LIMIT`: Rate limit - requests per hour per API key (default: 1000)

> **🔒 Security**: Rate limiting CANNOT be disabled or bypassed. When limit is exceeded, requests are BLOCKED with HTTP 429. Users must either:
> - ⏰ Wait for the hourly window to reset
> - 💰 Upgrade to paid tier (unlimited requests via contact support@saferun.dev)

### Provider Settings
- `SR_GITHUB_API_BASE`: Override GitHub API base URL (optional, defaults to `https://api.github.com`)
- `SR_GITHUB_USER_AGENT`: Custom user agent string for GitHub requests (optional)

### Global Notification Settings (Optional - for admin/fallback)
- `NOTIFY_TIMEOUT_MS`: Webhook timeout in milliseconds (default: 2000)
- `NOTIFY_RETRY`: Number of webhook retries (default: 1)
- `SLACK_BOT_TOKEN`: Slack Bot Token for admin notifications (optional)
- `SLACK_CHANNEL`: Default Slack channel (default: #saferun-alerts)
- `SLACK_WEBHOOK_URL`: Slack Webhook URL (alternative to Bot Token, optional)
- `GENERIC_WEBHOOK_URL`: Generic webhook URL for all events (optional)
- `GENERIC_WEBHOOK_SECRET`: Secret for webhook signature validation (optional)

**Note:** Users can configure their own notification settings via API (see above), which override these global settings.

## Pricing

- First 1000 API calls: FREE

## Support

(https://github.com/Cocabadger/saferun-api/issues)
