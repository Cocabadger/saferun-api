"""AutoGPT custom command leveraging SafeRun SDK."""
from __future__ import annotations

import os
from typing import Any

from saferun import SafeRunClient

client = SafeRunClient(api_key=os.getenv("SAFERUN_API_KEY", ""))

def saferun_archive_repo(repo: str, github_token: str) -> str:
    """Archive a GitHub repo via SafeRun."""
    result = client.archive_github_repo(repo=repo, github_token=github_token)
    if result.needs_approval:
        return f"Approval required: {result.approval_url}"
    return "Repository archived"

COMMANDS = {
    "saferun_archive_repo": {
        "description": "Archive a GitHub repository safely",
        "function": saferun_archive_repo,
    }
}
