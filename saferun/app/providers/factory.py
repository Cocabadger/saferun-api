"""Provider factory for SafeRun MVP.

Provides a `get_provider(name)` function that returns a provider instance.
MVP supports only GitHub and Notion providers.
"""
from typing import Optional

from .notion_provider import NotionProvider
from .github_provider import GitHubProvider


# Provider instances for MVP
_PROVIDERS = {
    "notion": NotionProvider(),
    "github": GitHubProvider(),
}


def get_provider(name: str) -> Optional[object]:
    """Return provider instance for given name or None if unsupported."""
    return _PROVIDERS.get(name)
