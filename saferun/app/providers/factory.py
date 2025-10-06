"""Provider factory for SafeRun.

Provides a `get_provider(name)` function that returns a provider instance.
MVP Launch: GitHub only. Other providers disabled for initial release.
"""
from typing import Optional

# from .notion_provider import NotionProvider  # Coming after MVP
from .github_provider import GitHubProvider


# Active providers for current release
_PROVIDERS = {
    # MVP: GitHub only
    "github": GitHubProvider(),
    
    # Other providers - Coming after MVP testing
    # "notion": NotionProvider(),
    # "airtable": AirtableProvider(),
    # "slack": SlackProvider(),
    # "gdrive": GDriveProvider(),
}


def get_provider(name: str) -> Optional[object]:
    """Return provider instance for given name or None if unsupported.
    
    Currently supports: github
    Coming soon: notion, airtable, slack, gdrive, gsheets
    """
    return _PROVIDERS.get(name)
