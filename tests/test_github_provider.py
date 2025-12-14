"""Unit tests for GitHub Provider."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from saferun.app.providers.github_provider import GitHubProvider


@pytest.mark.asyncio
async def test_delete_repository():
    """Test delete_repository method."""
    with patch.object(GitHubProvider, '_request', new_callable=AsyncMock) as mock_request:
        mock_request.return_value = None
        
        await GitHubProvider.delete_repository("owner/repo", "fake_token")
        
        mock_request.assert_called_once_with(
            "DELETE",
            "/repos/owner/repo",
            "fake_token"
        )


@pytest.mark.asyncio
async def test_delete_repository_invalid_target():
    """Test delete_repository with invalid target (branch format)."""
    with pytest.raises(RuntimeError, match="Delete repository only supported for repositories"):
        await GitHubProvider.delete_repository("owner/repo#branch", "fake_token")


@pytest.mark.asyncio
async def test_archive_repository():
    """Test archive method."""
    with patch.object(GitHubProvider, '_request', new_callable=AsyncMock) as mock_request:
        mock_request.return_value = None
        
        await GitHubProvider.archive("owner/repo", "fake_token")
        
        mock_request.assert_called_once_with(
            "PATCH",
            "/repos/owner/repo",
            "fake_token",
            json_payload={"archived": True}
        )


@pytest.mark.asyncio
async def test_unarchive_repository():
    """Test unarchive method."""
    with patch.object(GitHubProvider, '_request', new_callable=AsyncMock) as mock_request:
        mock_request.return_value = None
        
        await GitHubProvider.unarchive("owner/repo", "fake_token")
        
        mock_request.assert_called_once_with(
            "PATCH",
            "/repos/owner/repo",
            "fake_token",
            json_payload={"archived": False}
        )


@pytest.mark.asyncio
async def test_delete_branch():
    """Test delete_branch method returns SHA."""
    with patch.object(GitHubProvider, '_request', new_callable=AsyncMock) as mock_request:
        # Mock GET ref response
        mock_request.side_effect = [
            {"object": {"sha": "abc123def456"}},  # GET ref
            None  # DELETE ref
        ]
        
        sha = await GitHubProvider.delete_branch("owner/repo#main", "fake_token")
        
        assert sha == "abc123def456"
        assert mock_request.call_count == 2


@pytest.mark.asyncio
async def test_restore_branch():
    """Test restore_branch method."""
    with patch.object(GitHubProvider, '_request', new_callable=AsyncMock) as mock_request:
        mock_request.return_value = None
        
        await GitHubProvider.restore_branch("owner/repo#main", "fake_token", "abc123")
        
        mock_request.assert_called_once_with(
            "POST",
            "/repos/owner/repo/git/refs",
            "fake_token",
            json_payload={"ref": "refs/heads/main", "sha": "abc123"}
        )


@pytest.mark.asyncio
async def test_parse_target_repo():
    """Test _parse_target for repository format."""
    info = GitHubProvider._parse_target("owner/repo")
    assert info == {"kind": "repo", "owner": "owner", "repo": "repo"}


@pytest.mark.asyncio
async def test_parse_target_branch():
    """Test _parse_target for branch format."""
    info = GitHubProvider._parse_target("owner/repo#main")
    assert info == {"kind": "branch", "owner": "owner", "repo": "repo", "branch": "main"}


@pytest.mark.asyncio
async def test_parse_target_merge():
    """Test _parse_target for merge format."""
    info = GitHubProvider._parse_target("owner/repo#feature→main")
    assert info == {
        "kind": "merge",
        "owner": "owner",
        "repo": "repo",
        "source_branch": "feature",
        "target_branch": "main"
    }


@pytest.mark.asyncio
async def test_parse_target_bulk():
    """Test _parse_target for bulk format."""
    info = GitHubProvider._parse_target("owner/repo@view")
    assert info == {
        "kind": "bulk",
        "owner": "owner",
        "repo": "repo",
        "view": "view"
    }
