import json
from unittest.mock import patch, MagicMock

import pytest

from saferun import SafeRunClient
from saferun.exceptions import SafeRunAPIError


@pytest.fixture
def client() -> SafeRunClient:
    return SafeRunClient(api_key="test-key", api_url="https://example.com")


def make_response(status_code=200, payload=None):
    mock = MagicMock()
    mock.status_code = status_code
    mock.text = json.dumps(payload or {})
    mock.json.return_value = payload or {}
    return mock


def test_archive_repo_success(client):
    payload = {
        "change_id": "chg_123",
        "requires_approval": True,
        "approve_url": "https://approve",
        "risk_score": 0.8,
        "reasons": ["high_risk"],
        "expires_at": "2025-01-01T00:00:00Z",
    }
    with patch.object(client.session, "post", return_value=make_response(payload=payload)) as post:
        result = client.archive_github_repo("owner/repo", "token")
        assert result.change_id == "chg_123"
        assert result.needs_approval is True
        assert result.approval_url == "https://approve"
        post.assert_called_once()


def test_apply_change_error(client):
    with patch.object(client.session, "post", return_value=make_response(status_code=403, payload={"detail": "Forbidden"})):
        with pytest.raises(SafeRunAPIError):
            client.apply_change("chg_123")
