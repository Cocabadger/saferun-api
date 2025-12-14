"""Unit tests for GitHub Delete Repository API endpoint."""
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch, MagicMock
from saferun.app.main import app


@pytest.fixture
def mock_db():
    """Mock database operations."""
    with patch("saferun.app.routers.auth.db") as mock:
        mock.validate_api_key.return_value = {
            "api_key": "test_key",
            "key_label": "Test Key",
            "is_active": True
        }
        yield mock


@pytest.fixture
def mock_build_dryrun():
    """Mock build_dryrun function."""
    with patch("saferun.app.routers.github.build_dryrun") as mock:
        mock.return_value = {
            "change_id": "test-change-123",
            "requires_approval": True,
            "status": "ok",
            "target": {"provider": "github", "target_id": "owner/repo", "type": "repo"},
            "summary": {"title": "test-repo"},
            "diff": [],
            "risk_score": 0.9,
            "reasons": ["github:irreversible_operation"],
            "human_preview": "Delete repository owner/repo (PERMANENT)",
            "approve_url": "https://api.saferun.dev/approve?t=token123",
            "expires_at": "2025-10-06T12:00:00Z",
            "telemetry": {},
            "service": "saferun",
            "version": "0.20.0"
        }
        yield mock


@pytest.mark.asyncio
async def test_delete_repo_endpoint_requires_auth():
    """Test delete repo endpoint requires authentication."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/dry-run/github.repo.delete",
            json={
                "token": "github_token",
                "target_id": "owner/repo"
            }
        )
        assert response.status_code == 401  # No API key


@pytest.mark.asyncio
async def test_delete_repo_endpoint_success(mock_db, mock_build_dryrun):
    """Test delete repo endpoint success."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/dry-run/github.repo.delete",
            json={
                "token": "github_token",
                "target_id": "owner/repo",
                "reason": "Cleanup old repo"
            },
            headers={"X-API-Key": "test_key"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["change_id"] == "test-change-123"
        assert data["requires_approval"] is True
        
        # Verify build_dryrun was called with correct params
        mock_build_dryrun.assert_called_once()
        call_args = mock_build_dryrun.call_args
        generic_req = call_args[0][0]
        assert generic_req.provider == "github"
        assert generic_req.target_id == "owner/repo"
        assert "Cleanup old repo" in generic_req.reason or "Delete repository" in generic_req.reason


@pytest.mark.asyncio
async def test_delete_repo_endpoint_default_reason(mock_db, mock_build_dryrun):
    """Test delete repo endpoint uses default reason."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/dry-run/github.repo.delete",
            json={
                "token": "github_token",
                "target_id": "owner/repo"
            },
            headers={"X-API-Key": "test_key"}
        )
        
        assert response.status_code == 200
        
        # Verify default reason was used
        call_args = mock_build_dryrun.call_args
        generic_req = call_args[0][0]
        assert "PERMANENT" in generic_req.reason or "cannot be undone" in generic_req.reason


@pytest.mark.asyncio
async def test_delete_repo_with_webhook(mock_db, mock_build_dryrun):
    """Test delete repo with webhook URL."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/dry-run/github.repo.delete",
            json={
                "token": "github_token",
                "target_id": "owner/repo",
                "webhook_url": "https://example.com/webhook"
            },
            headers={"X-API-Key": "test_key"}
        )
        
        assert response.status_code == 200
        
        # Verify webhook URL was passed
        call_args = mock_build_dryrun.call_args
        generic_req = call_args[0][0]
        assert generic_req.webhook_url == "https://example.com/webhook"


@pytest.mark.asyncio
async def test_delete_repo_missing_token(mock_db):
    """Test delete repo without GitHub token."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/dry-run/github.repo.delete",
            json={
                "target_id": "owner/repo"
            },
            headers={"X-API-Key": "test_key"}
        )
        
        assert response.status_code == 422  # Validation error (missing required field)


