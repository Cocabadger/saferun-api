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

#### Configure Email notifications
```bash
curl -X PUT https://saferun.up.railway.app/v1/settings/notifications \
  -H "X-API-Key: your_api_key" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "alerts@company.com",
    "email_enabled": true,
    "slack_enabled": false
  }'
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
- ✅ Email notifications (requires SMTP server configured)
- ✅ Custom webhooks with HMAC signature validation
- ✅ Fallback to global admin settings if user settings not configured

## Supported Providers

- **GitHub**: Repository archive/unarchive, branch delete/restore, bulk PR operations ✅ Webhooks
- **Notion**: Page archive/unarchive with conflict detection ✅ Webhooks
- **Airtable**: Record and bulk operations ✅ Webhooks
- **Google Drive**: File/folder operations (coming soon)
- **Slack**: Channel archive (coming soon)
- **Google Sheets**: Sheet operations (coming soon)

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
- `SR_STORAGE_BACKEND`: Storage type (sqlite)
- `SR_SQLITE_PATH`: Database path (default `/data/saferun.db` when using a Railway Volume; set to `data/saferun.db` for local development)
- `SR_FREE_TIER_LIMIT`: Number of free API calls before returning 403 (default 100, set to `-1` to disable)

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
- `SMTP_HOST`: Email server host (optional)
- `SMTP_PORT`: Email server port (optional)
- `SMTP_USER`: Email username (optional)
- `SMTP_PASS`: Email password (optional)
- `SMTP_FROM`: Sender email address (optional)

**Note:** Users can configure their own notification settings via API (see below), which override these global settings.

## Pricing

- First 1000 API calls: FREE

## Support

(https://github.com/Cocabadger/saferun-api/issues)
