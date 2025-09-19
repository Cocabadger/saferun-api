"""
Basic tests for SafeRun API functionality.
"""

import pytest
import asyncio
from saferun.models.models import ActionRequest, ActionType, ProviderType
from saferun.core.risk import RiskAnalyzer
from saferun.core import safety_middleware


class TestRiskAnalyzer:
    """Test risk analysis functionality."""
    
    def test_risk_analyzer_initialization(self):
        """Test that risk analyzer initializes correctly."""
        analyzer = RiskAnalyzer()
        assert analyzer.risk_threshold > 0
        assert analyzer.high_risk_threshold > analyzer.risk_threshold
    
    def test_low_risk_read_operation(self):
        """Test that read operations are low risk."""
        analyzer = RiskAnalyzer()
        
        assessment = analyzer.assess_risk(
            provider=ProviderType.GITHUB,
            action_type=ActionType.READ,
            resource_path="repos/user/repo/issues",
            parameters={}
        )
        
        assert assessment.score < 0.5
        assert assessment.level.value in ["low", "medium"]
    
    def test_high_risk_delete_operation(self):
        """Test that delete operations on main branch are high risk."""
        analyzer = RiskAnalyzer()
        
        assessment = analyzer.assess_risk(
            provider=ProviderType.GITHUB,
            action_type=ActionType.DELETE,
            resource_path="repos/user/repo/branches/main",
            parameters={}
        )
        
        assert assessment.score > 0.7
        assert assessment.level.value in ["high", "critical"]
        assert len(assessment.factors) > 0
        assert len(assessment.mitigation_suggestions) > 0


class TestSafetyMiddleware:
    """Test safety middleware functionality."""
    
    @pytest.mark.asyncio
    async def test_preview_action(self):
        """Test action preview functionality."""
        request = ActionRequest(
            provider=ProviderType.GITHUB,
            action_type=ActionType.READ,
            resource_path="repos/user/repo/issues",
            parameters={},
            dry_run=True
        )
        
        # This will fail without proper GitHub token, but that's expected
        try:
            preview = await safety_middleware.preview_action(request)
            assert preview.action_id is not None
            assert preview.provider == ProviderType.GITHUB
            assert preview.action_type == ActionType.READ
        except Exception as e:
            # Expected to fail without proper provider credentials
            assert "GitHub" in str(e) or "token" in str(e).lower()
    
    def test_action_status_not_found(self):
        """Test getting status of non-existent action."""
        from saferun.utils.errors import ActionNotFoundError
        
        with pytest.raises(ActionNotFoundError):
            safety_middleware.get_action_status("non-existent-id")


class TestModels:
    """Test data models."""
    
    def test_action_request_validation(self):
        """Test ActionRequest model validation."""
        # Valid request
        request = ActionRequest(
            provider=ProviderType.GITHUB,
            action_type=ActionType.CREATE,
            resource_path="repos/user/repo/issues",
            parameters={"title": "Test issue"}
        )
        
        assert request.provider == ProviderType.GITHUB
        assert request.action_type == ActionType.CREATE
        assert request.dry_run is True  # Default value
        assert request.force is False  # Default value
    
    def test_risk_assessment_score_validation(self):
        """Test risk assessment score validation."""
        from saferun.models.models import RiskAssessment, RiskLevel
        from pydantic import ValidationError
        
        # Valid score
        assessment = RiskAssessment(
            score=0.5,
            level=RiskLevel.MEDIUM
        )
        assert assessment.score == 0.5
        
        # Invalid score (too high)
        with pytest.raises(ValidationError):
            RiskAssessment(
                score=1.5,  # Invalid: > 1.0
                level=RiskLevel.HIGH
            )
        
        # Invalid score (negative)
        with pytest.raises(ValidationError):
            RiskAssessment(
                score=-0.1,  # Invalid: < 0.0
                level=RiskLevel.LOW
            )


if __name__ == "__main__":
    pytest.main([__file__])