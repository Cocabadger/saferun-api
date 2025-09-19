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

## Supported Providers

- **GitHub**: Repository archive/unarchive, branch delete/restore, bulk PR operations
- **Notion**: Page archive/unarchive with conflict detection

## Deployment

### Railway (Recommended)

1. Push to GitHub
2. Connect repo to Railway
3. Add environment variables in Railway dashboard
4. Deploy!

### Render

1. Create new Web Service
2. Connect GitHub repo
3. Build command: `pip install -r requirements.txt`
4. Start command: `uvicorn saferun.app.main:app --host 0.0.0.0 --port $PORT`

## Environment Variables

- `PORT`: Server port (default: 8500)
- `SR_LOG_LEVEL`: Log level (info/debug)
- `SR_STORAGE_BACKEND`: Storage type (sqlite)
- `SR_SQLITE_PATH`: Database path (data/saferun.db)

## Pricing

- First 100 API calls: FREE
- After: $0.01 per safety check

## Support

Email: support@saferun.dev
