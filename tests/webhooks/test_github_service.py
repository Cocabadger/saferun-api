"""Tests for GitHub service (signature verification, risk scoring, revert operations)"""
import pytest
import os
import hashlib
import hmac
from unittest.mock import AsyncMock, patch, MagicMock
from saferun.app.services.github import (
    verify_webhook_signature,
    calculate_github_risk_score,
    revert_force_push,
    restore_deleted_branch,
    create_revert_commit,
    create_revert_action
)


class TestWebhookSignatureVerification:
    """Test HMAC-SHA256 signature verification"""
    
    def test_valid_signature(self):
        """Test that valid signature passes verification"""
        os.environ["GITHUB_WEBHOOK_SECRET"] = "test-secret-key"
        
        payload = b'{"action": "created", "installation": {"id": 123}}'
        
        # Generate valid signature
        expected_sig = "sha256=" + hmac.new(
            b"test-secret-key",
            payload,
            hashlib.sha256
        ).hexdigest()
        
        assert verify_webhook_signature(payload, expected_sig) is True
    
    def test_invalid_signature(self):
        """Test that invalid signature fails verification"""
        os.environ["GITHUB_WEBHOOK_SECRET"] = "test-secret-key"
        
        payload = b'{"action": "created"}'
        invalid_sig = "sha256=fakesignature123"
        
        assert verify_webhook_signature(payload, invalid_sig) is False
    
    def test_missing_sha256_prefix(self):
        """Test that signature without sha256= prefix fails"""
        os.environ["GITHUB_WEBHOOK_SECRET"] = "test-secret-key"
        
        payload = b'{"action": "created"}'
        invalid_sig = "fakesignature123"  # Missing "sha256=" prefix
        
        assert verify_webhook_signature(payload, invalid_sig) is False
    
    def test_empty_signature(self):
        """Test that empty signature fails"""
        os.environ["GITHUB_WEBHOOK_SECRET"] = "test-secret-key"
        
        payload = b'{"action": "created"}'
        
        assert verify_webhook_signature(payload, "") is False
        assert verify_webhook_signature(payload, None) is False
    
    def test_missing_secret_raises_error(self):
        """Test that missing GITHUB_WEBHOOK_SECRET raises ValueError"""
        os.environ["GITHUB_WEBHOOK_SECRET"] = ""
        
        payload = b'{"action": "created"}'
        signature = "sha256=test"
        
        with pytest.raises(ValueError, match="GITHUB_WEBHOOK_SECRET not configured"):
            verify_webhook_signature(payload, signature)


class TestRiskScoreCalculation:
    """Test risk score calculation for different GitHub events"""
    
    def test_force_push_to_main(self):
        """Test that force push to main has high risk score"""
        payload = {
            "forced": True,
            "ref": "refs/heads/main",
            "commits": [{"sha": "abc123"}]
        }
        
        risk_score, reasons = calculate_github_risk_score("push", payload)
        
        assert risk_score == 9.0  # 7.0 (force push) + 2.0 (to main)
        assert "github_force_push" in reasons
        assert "github_force_push_to_main" in reasons
    
    def test_force_push_to_feature_branch(self):
        """Test that force push to feature branch has medium risk"""
        payload = {
            "forced": True,
            "ref": "refs/heads/feature/test",
            "commits": []
        }
        
        risk_score, reasons = calculate_github_risk_score("push", payload)
        
        assert risk_score == 7.0  # Only force push penalty
        assert "github_force_push" in reasons
        assert "github_force_push_to_main" not in reasons
    
    def test_normal_push_low_risk(self):
        """Test that normal push has low/no risk"""
        payload = {
            "forced": False,
            "ref": "refs/heads/feature/test",
            "commits": [{"sha": "abc"}, {"sha": "def"}]
        }
        
        risk_score, reasons = calculate_github_risk_score("push", payload)
        
        assert risk_score == 0.0
        assert len(reasons) == 0
    
    def test_large_push_adds_risk(self):
        """Test that pushing >10 commits adds risk"""
        payload = {
            "forced": False,
            "ref": "refs/heads/feature/test",
            "commits": [{"sha": f"commit{i}"} for i in range(15)]
        }
        
        risk_score, reasons = calculate_github_risk_score("push", payload)
        
        assert risk_score == 0.5
        assert "github_large_push" in reasons
    
    def test_delete_main_branch_critical(self):
        """Test that deleting main branch is critical risk"""
        payload = {
            "ref_type": "branch",
            "ref": "main"
        }
        
        risk_score, reasons = calculate_github_risk_score("delete", payload)
        
        assert risk_score == 8.0  # 4.0 (branch delete) + 4.0 (main)
        assert "github_branch_delete" in reasons
        assert "github_delete_main_branch" in reasons
    
    def test_delete_feature_branch(self):
        """Test that deleting feature branch has medium risk"""
        payload = {
            "ref_type": "branch",
            "ref": "feature/old-stuff"
        }
        
        risk_score, reasons = calculate_github_risk_score("delete", payload)
        
        assert risk_score == 4.0
        assert "github_branch_delete" in reasons
        assert "github_delete_main_branch" not in reasons
    
    def test_delete_tag(self):
        """Test that deleting tag has medium risk"""
        payload = {
            "ref_type": "tag",
            "ref": "v1.0.0"
        }
        
        risk_score, reasons = calculate_github_risk_score("delete", payload)
        
        assert risk_score == 3.0
        assert "github_tag_delete" in reasons
    
    def test_merge_to_main_high_risk(self):
        """Test that merging to main has high risk"""
        payload = {
            "action": "closed",
            "pull_request": {
                "merged": True,
                "base": {"ref": "main"},
                "review_comments": 0
            }
        }
        
        risk_score, reasons = calculate_github_risk_score("pull_request", payload)
        
        assert risk_score == 6.0  # 5.0 (merge to main) + 1.0 (no review)
        assert "github_merge_to_main" in reasons
        assert "github_merge_without_review" in reasons
    
    def test_merge_to_main_with_review(self):
        """Test that reviewed merge to main has medium risk"""
        payload = {
            "action": "closed",
            "pull_request": {
                "merged": True,
                "base": {"ref": "main"},
                "review_comments": 3
            }
        }
        
        risk_score, reasons = calculate_github_risk_score("pull_request", payload)
        
        assert risk_score == 5.0  # Only merge to main penalty
        assert "github_merge_to_main" in reasons
        assert "github_merge_without_review" not in reasons
    
    def test_merge_to_feature_branch(self):
        """Test that merging to feature branch has low risk"""
        payload = {
            "action": "closed",
            "pull_request": {
                "merged": True,
                "base": {"ref": "develop"},
                "review_comments": 0
            }
        }
        
        risk_score, reasons = calculate_github_risk_score("pull_request", payload)
        
        assert risk_score == 2.0
        assert "github_merge" in reasons
        assert "github_merge_to_main" not in reasons
    
    def test_archive_repository_critical(self):
        """Test that archiving repository is critical risk"""
        payload = {"action": "archived"}
        
        risk_score, reasons = calculate_github_risk_score("repository", payload)
        
        assert risk_score == 8.0
        assert "github_repository_archived" in reasons
    
    def test_delete_repository_maximum_risk(self):
        """Test that deleting repository is maximum risk"""
        payload = {"action": "deleted"}
        
        risk_score, reasons = calculate_github_risk_score("repository", payload)
        
        assert risk_score == 10.0  # Capped at 10.0
        assert "github_repository_deleted" in reasons
    
    def test_risk_score_capped_at_10(self):
        """Test that risk score never exceeds 10.0"""
        # Create extreme scenario
        payload = {
            "forced": True,
            "ref": "refs/heads/main",
            "commits": [{"sha": f"c{i}"} for i in range(100)]
        }
        
        risk_score, reasons = calculate_github_risk_score("push", payload)
        
        assert risk_score <= 10.0


class TestRevertOperations:
    """Test GitHub revert operations (force push, branch delete, merge)"""
    
    @pytest.mark.asyncio
    async def test_revert_force_push_success(self):
        """Test successful force push revert"""
        with patch('httpx.AsyncClient') as mock_client:
            # Mock successful API response
            mock_response = MagicMock()
            mock_response.status_code = 200
            
            mock_client_instance = AsyncMock()
            mock_client_instance.patch.return_value = mock_response
            mock_client.return_value.__aenter__.return_value = mock_client_instance
            
            result = await revert_force_push(
                owner="test-owner",
                repo="test-repo",
                branch="main",
                before_sha="abc123",
                github_token="test-token"
            )
            
            assert result is True
            
            # Verify API was called correctly
            mock_client_instance.patch.assert_called_once()
            call_args = mock_client_instance.patch.call_args
            
            assert "test-owner/test-repo/git/refs/heads/main" in call_args[0][0]
            assert call_args[1]["json"]["sha"] == "abc123"
            assert call_args[1]["json"]["force"] is True
            assert call_args[1]["headers"]["Authorization"] == "token test-token"
    
    @pytest.mark.asyncio
    async def test_revert_force_push_failure(self):
        """Test failed force push revert"""
        with patch('httpx.AsyncClient') as mock_client:
            # Mock failed API response
            mock_response = MagicMock()
            mock_response.status_code = 403  # Forbidden
            
            mock_client_instance = AsyncMock()
            mock_client_instance.patch.return_value = mock_response
            mock_client.return_value.__aenter__.return_value = mock_client_instance
            
            result = await revert_force_push(
                owner="test-owner",
                repo="test-repo",
                branch="main",
                before_sha="abc123",
                github_token="invalid-token"
            )
            
            assert result is False
    
    @pytest.mark.asyncio
    async def test_restore_deleted_branch_success(self):
        """Test successful branch restoration"""
        with patch('httpx.AsyncClient') as mock_client:
            # Mock successful API response
            mock_response = MagicMock()
            mock_response.status_code = 201  # Created
            
            mock_client_instance = AsyncMock()
            mock_client_instance.post.return_value = mock_response
            mock_client.return_value.__aenter__.return_value = mock_client_instance
            
            result = await restore_deleted_branch(
                owner="test-owner",
                repo="test-repo",
                branch="deleted-branch",
                sha="def456",
                github_token="test-token"
            )
            
            assert result is True
            
            # Verify API was called correctly
            mock_client_instance.post.assert_called_once()
            call_args = mock_client_instance.post.call_args
            
            assert "test-owner/test-repo/git/refs" in call_args[0][0]
            assert call_args[1]["json"]["ref"] == "refs/heads/deleted-branch"
            assert call_args[1]["json"]["sha"] == "def456"
    
    @pytest.mark.asyncio
    async def test_create_revert_commit_success(self):
        """Test successful revert commit creation"""
        with patch('httpx.AsyncClient') as mock_client:
            # Mock responses for GET commit and PATCH ref
            mock_get_response = MagicMock()
            mock_get_response.status_code = 200
            mock_get_response.json.return_value = {
                "parents": [{"sha": "parent123"}]
            }
            
            mock_patch_response = MagicMock()
            mock_patch_response.status_code = 200
            
            mock_client_instance = AsyncMock()
            mock_client_instance.get.return_value = mock_get_response
            mock_client_instance.patch.return_value = mock_patch_response
            mock_client.return_value.__aenter__.return_value = mock_client_instance
            
            result = await create_revert_commit(
                owner="test-owner",
                repo="test-repo",
                branch="main",
                commit_sha="merge789",
                github_token="test-token"
            )
            
            assert result is True


class TestRevertActionCreation:
    """Test revert action instruction generation"""
    
    def test_create_force_push_revert_action(self):
        """Test force push revert action creation"""
        payload = {
            "forced": True,
            "repository": {
                "owner": {"login": "owner"},
                "name": "repo"
            },
            "ref": "refs/heads/main",
            "before": "old_sha",
            "after": "new_sha"
        }
        
        action = create_revert_action("push", payload)
        
        assert action is not None
        assert action["type"] == "force_push_revert"
        assert action["owner"] == "owner"
        assert action["repo"] == "repo"
        assert action["branch"] == "main"
        assert action["before_sha"] == "old_sha"
        assert action["after_sha"] == "new_sha"
    
    def test_create_branch_delete_revert_action(self):
        """Test branch delete revert action creation"""
        payload = {
            "ref_type": "branch",
            "ref": "deleted-branch",
            "repository": {
                "owner": {"login": "owner"},
                "name": "repo"
            }
        }
        
        action = create_revert_action("delete", payload)
        
        assert action is not None
        assert action["type"] == "branch_restore"
        assert action["owner"] == "owner"
        assert action["repo"] == "repo"
        assert action["branch"] == "deleted-branch"
        assert action["sha"] is None  # Will be populated from previous push
    
    def test_create_merge_revert_action(self):
        """Test merge revert action creation"""
        payload = {
            "action": "closed",
            "pull_request": {
                "merged": True,
                "base": {"ref": "main"},
                "merge_commit_sha": "merge123"
            },
            "repository": {
                "owner": {"login": "owner"},
                "name": "repo"
            }
        }
        
        action = create_revert_action("pull_request", payload)
        
        assert action is not None
        assert action["type"] == "merge_revert"
        assert action["owner"] == "owner"
        assert action["repo"] == "repo"
        assert action["branch"] == "main"
        assert action["merge_commit_sha"] == "merge123"
    
    def test_normal_push_no_revert_action(self):
        """Test that normal push doesn't create revert action"""
        payload = {
            "forced": False,
            "ref": "refs/heads/feature"
        }
        
        action = create_revert_action("push", payload)
        
        assert action is None
    
    def test_pr_opened_no_revert_action(self):
        """Test that PR opened doesn't create revert action"""
        payload = {
            "action": "opened",
            "pull_request": {"merged": False}
        }
        
        action = create_revert_action("pull_request", payload)
        
        assert action is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
