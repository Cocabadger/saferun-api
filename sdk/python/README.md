# SafeRun Python SDK

Official Python client for SafeRun API - Safety middleware for AI agents.

## Installation

```bash
pip install saferun
```

## Quick Start

```python
from saferun import SafeRunClient

client = SafeRunClient(api_key="your-api-key")

# Archive a repository (basic operation)
result = client.archive_github_repo(
    repo="owner/repo",
    github_token="ghp_xxx",
)

if result.needs_approval:
    print("⚠️  Approval required!")
    print(f"Risk Score: {result.risk_score}/10")
    print(f"Approve at: {result.approval_url}")
    
    # Wait for approval
    status = client.wait_for_approval(result.change_id)
    if status.approved:
        print("✅ Operation completed!")
```

## Supported Operations

### Basic Operations
- `archive_github_repo()` - Archive a repository
- `delete_github_repo()` - Delete a repository (permanent!)
- `delete_github_branch()` - Delete a branch
- `bulk_close_github_prs()` - Close multiple PRs
- `archive_notion_page()` - Archive Notion page

### Advanced Operations (Phase 1.4)
- `transfer_repository()` - Transfer repo to another owner
- `create_or_update_secret()` - Manage GitHub Actions secrets
- `delete_secret()` - Remove secrets
- `update_workflow_file()` - Modify workflow files
- `update_branch_protection()` - Configure protection rules
- `delete_branch_protection()` - Remove protection
- `change_repository_visibility()` - Public ↔ Private

## Examples

### Transfer Repository
```python
result = client.transfer_repository(
    repo="my-org/my-repo",
    new_owner="target-org",
    github_token="ghp_xxx",
)
```

### Manage Secrets
```python
result = client.create_or_update_secret(
    repo="owner/repo",
    secret_name="API_KEY",
    secret_value="sk_live_abc123",
    github_token="ghp_xxx",
)
```

### Branch Protection
```python
result = client.update_branch_protection(
    repo="owner/repo",
    branch="main",
    github_token="ghp_xxx",
    required_reviews=2,
    require_code_owner_reviews=True,
    enforce_admins=True,
)
```

### Change Visibility
```python
# Make private
result = client.change_repository_visibility(
    repo="owner/repo",
    private=True,
    github_token="ghp_xxx",
)

# Make public (HIGH RISK!)
result = client.change_repository_visibility(
    repo="owner/repo",
    private=False,
    github_token="ghp_xxx",
)
```

## Complete Examples

See `examples/` directory:
- `01_basic_github.py` - Basic GitHub operations
- `02_branch_delete_with_approval.py` - Branch deletion with approval flow
- `03_transfer_repository.py` - Repository transfer
- `04_manage_secrets.py` - GitHub Actions secrets
- `05_branch_protection.py` - Protection rules
- `06_change_visibility.py` - Visibility changes

## Features

- ✅ **Approval Flow** - Human oversight for dangerous operations
- ✅ **Risk Scoring** - Automatic risk assessment (0-10)
- ✅ **Slack Notifications** - Real-time alerts with approval links
- ✅ **One-time Tokens** - Secure approval authentication
- ✅ **Revert Window** - 24-hour undo for reversible operations
- ✅ **Policy Engine** - Custom rules and thresholds

## API Reference

Full documentation: https://github.com/Cocabadger/saferun-api
