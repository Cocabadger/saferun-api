# Example Configuration

This directory contains example configuration files for the SafeRun API.

## Files

- `example.env` - Environment variables configuration
- `docker-compose.yml` - Docker Compose setup
- `github-example.json` - Example GitHub API requests
- `notion-example.json` - Example Notion API requests

## Quick Setup

1. Copy the example environment file:
```bash
cp examples/example.env .env
```

2. Edit `.env` with your actual API tokens:
```bash
# GitHub token with appropriate permissions
GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Notion integration token
NOTION_TOKEN=secret_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Generate a secure secret key
SECRET_KEY=$(openssl rand -hex 32)
```

3. Start the API:
```bash
python -m saferun.main
```

4. Test with the provided examples:
```bash
# Test authentication
curl -X POST http://localhost:8000/api/v1/auth/token \
  -H "Content-Type: application/json" \
  -d '{"api_key": "saferun-key-123"}'

# Test action preview
curl -X POST http://localhost:8000/api/v1/actions/preview \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d @examples/github-example.json
```