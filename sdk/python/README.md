# SafeRun Python SDK

Official Python client for SafeRun API.

## Installation

```bash
pip install saferun
```

## Usage

```python
from saferun import SafeRunClient

client = SafeRunClient(api_key="your-api-key")
result = client.archive_github_repo(
    repo="owner/repo",
    github_token="ghp_xxx",
)

if result.needs_approval:
    print("Approve at:", result.approval_url)
```

See `examples/` for complete workflows (LangChain integration, webhook handling, etc.).
