"""LangChain tools backed by SafeRun."""
from __future__ import annotations

import os
from typing import Any

from langchain.tools import Tool
from saferun import SafeRunClient

client = SafeRunClient(api_key=os.getenv('SAFERUN_API_KEY', ''))


def safe_archive_repo(repo: str) -> str:
    token = os.getenv('GITHUB_TOKEN', '')
    result = client.archive_github_repo(repo=repo, github_token=token)
    if result.needs_approval:
        return f"Approval required: {result.approval_url}"
    return 'Repository archived'


archive_repo_tool = Tool(
    name='SafeArchiveRepo',
    description='Archive a GitHub repository with SafeRun approval flow',
    func=safe_archive_repo,
)
