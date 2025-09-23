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

### Webhook Settings (Optional)
- `NOTIFY_TIMEOUT_MS`: Webhook timeout in milliseconds (default: 2000)
- `NOTIFY_RETRY`: Number of webhook retries (default: 1)
- `SLACK_WEBHOOK_URL`: Your Slack webhook for SafeRun system notifications (optional)
- `GENERIC_WEBHOOK_URL`: Generic webhook URL for all events (optional)
- `GENERIC_WEBHOOK_SECRET`: Secret for webhook signature validation (optional)

## Pricing

- First 1000 API calls: FREE

## Support

(https://github.com/Cocabadger/saferun-api/issues)
