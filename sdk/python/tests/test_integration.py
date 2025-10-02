import os

import pytest

from saferun import SafeRunClient


@pytest.mark.skip(reason="Integration test requires SAFE_RUN_API_KEY env var and live API")
def test_integration_archive_repo():
    api_key = os.getenv("SAFERUN_API_KEY")
    if not api_key:
        pytest.skip("SAFERUN_API_KEY not set")
    client = SafeRunClient(api_key=api_key)
    result = client.archive_github_repo("owner/repo", "ghp_example")
    assert result.change_id
