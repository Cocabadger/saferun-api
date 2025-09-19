"""
Risk assessment and scoring system for SafeRun API.
"""

from typing import Dict, List, Any, Tuple
from saferun.models.models import ActionType, RiskLevel, RiskAssessment, ProviderType
import os
from dotenv import load_dotenv
import structlog

load_dotenv()
logger = structlog.get_logger(__name__)

# Configuration
DEFAULT_RISK_THRESHOLD = float(os.getenv("DEFAULT_RISK_THRESHOLD", "0.7"))
HIGH_RISK_THRESHOLD = float(os.getenv("HIGH_RISK_THRESHOLD", "0.9"))


class RiskAnalyzer:
    """Risk analysis engine for actions."""
    
    # Risk weights for different factors
    ACTION_TYPE_WEIGHTS = {
        ActionType.READ: 0.1,
        ActionType.CREATE: 0.3,
        ActionType.UPDATE: 0.5,
        ActionType.DELETE: 0.9
    }
    
    # Risk patterns for resource paths
    HIGH_RISK_PATTERNS = [
        "main",
        "master", 
        "production",
        "prod",
        "release",
        "deploy",
        "database",
        "config",
        "secrets",
        "admin",
        "root"
    ]
    
    # Critical operation keywords
    CRITICAL_OPERATIONS = [
        "delete",
        "remove",
        "drop",
        "truncate",
        "destroy",
        "purge",
        "wipe",
        "reset",
        "format"
    ]
    
    def __init__(self):
        self.risk_threshold = DEFAULT_RISK_THRESHOLD
        self.high_risk_threshold = HIGH_RISK_THRESHOLD
    
    def assess_risk(
        self, 
        provider: ProviderType,
        action_type: ActionType,
        resource_path: str,
        parameters: Dict[str, Any]
    ) -> RiskAssessment:
        """Assess risk for a given action."""
        
        # Start with base risk from action type
        base_risk = self.ACTION_TYPE_WEIGHTS.get(action_type, 0.5)
        
        # Analyze risk factors
        risk_factors = []
        mitigation_suggestions = []
        risk_multipliers = []
        
        # Check resource path for high-risk patterns
        path_risk, path_factors, path_suggestions = self._analyze_resource_path(resource_path)
        risk_factors.extend(path_factors)
        mitigation_suggestions.extend(path_suggestions)
        risk_multipliers.append(path_risk)
        
        # Check parameters for dangerous operations
        param_risk, param_factors, param_suggestions = self._analyze_parameters(parameters)
        risk_factors.extend(param_factors)
        mitigation_suggestions.extend(param_suggestions)
        risk_multipliers.append(param_risk)
        
        # Provider-specific risk analysis
        provider_risk, provider_factors, provider_suggestions = self._analyze_provider_specific(
            provider, action_type, resource_path, parameters
        )
        risk_factors.extend(provider_factors)
        mitigation_suggestions.extend(provider_suggestions)
        risk_multipliers.append(provider_risk)
        
        # Calculate final risk score
        final_risk = base_risk
        for multiplier in risk_multipliers:
            final_risk = min(1.0, final_risk * multiplier)
        
        # Determine risk level
        risk_level = self._determine_risk_level(final_risk)
        
        # Add general mitigation suggestions based on risk level
        if risk_level in [RiskLevel.HIGH, RiskLevel.CRITICAL]:
            mitigation_suggestions.extend([
                "Perform dry-run first",
                "Get manual approval",
                "Create backup before execution"
            ])
        
        return RiskAssessment(
            score=round(final_risk, 3),
            level=risk_level,
            factors=list(set(risk_factors)),  # Remove duplicates
            mitigation_suggestions=list(set(mitigation_suggestions))
        )
    
    def _analyze_resource_path(self, resource_path: str) -> Tuple[float, List[str], List[str]]:
        """Analyze resource path for risk factors."""
        risk_multiplier = 1.0
        factors = []
        suggestions = []
        
        path_lower = resource_path.lower()
        
        # Check for high-risk patterns
        for pattern in self.HIGH_RISK_PATTERNS:
            if pattern in path_lower:
                risk_multiplier += 0.3
                factors.append(f"High-risk resource pattern: {pattern}")
                suggestions.append(f"Exercise caution with {pattern} resources")
        
        # Check for production indicators
        if any(indicator in path_lower for indicator in ["prod", "production", "live"]):
            risk_multiplier += 0.4
            factors.append("Production environment detected")
            suggestions.append("Use staging environment first")
        
        # Check for system/admin paths
        if any(admin in path_lower for admin in ["admin", "root", "system", "config"]):
            risk_multiplier += 0.3
            factors.append("Administrative resource detected")
            suggestions.append("Verify administrative permissions")
        
        return risk_multiplier, factors, suggestions
    
    def _analyze_parameters(self, parameters: Dict[str, Any]) -> Tuple[float, List[str], List[str]]:
        """Analyze parameters for dangerous operations."""
        risk_multiplier = 1.0
        factors = []
        suggestions = []
        
        # Convert all parameter values to strings for analysis
        param_text = " ".join(str(v).lower() for v in parameters.values() if v)
        
        # Check for critical operations
        for operation in self.CRITICAL_OPERATIONS:
            if operation in param_text:
                risk_multiplier += 0.4
                factors.append(f"Critical operation detected: {operation}")
                suggestions.append(f"Double-check {operation} operation")
        
        # Check for force/skip safety flags
        if any(key.lower() in ["force", "skip", "ignore"] for key in parameters.keys()):
            risk_multiplier += 0.2
            factors.append("Safety bypass flags detected")
            suggestions.append("Remove safety bypass flags")
        
        # Check for bulk operations
        if any(key.lower() in ["all", "bulk", "batch"] for key in parameters.keys()):
            risk_multiplier += 0.2
            factors.append("Bulk operation detected")
            suggestions.append("Consider processing in smaller batches")
        
        return risk_multiplier, factors, suggestions
    
    def _analyze_provider_specific(
        self, 
        provider: ProviderType,
        action_type: ActionType,
        resource_path: str,
        parameters: Dict[str, Any]
    ) -> Tuple[float, List[str], List[str]]:
        """Provider-specific risk analysis."""
        
        if provider == ProviderType.GITHUB:
            return self._analyze_github_risk(action_type, resource_path, parameters)
        elif provider == ProviderType.NOTION:
            return self._analyze_notion_risk(action_type, resource_path, parameters)
        
        return 1.0, [], []
    
    def _analyze_github_risk(
        self, 
        action_type: ActionType,
        resource_path: str,
        parameters: Dict[str, Any]
    ) -> Tuple[float, List[str], List[str]]:
        """GitHub-specific risk analysis."""
        risk_multiplier = 1.0
        factors = []
        suggestions = []
        
        path_lower = resource_path.lower()
        
        # Repository deletion is extremely high risk
        if action_type == ActionType.DELETE and "repos/" in path_lower:
            risk_multiplier += 1.0
            factors.append("Repository deletion detected")
            suggestions.append("Create full backup before deletion")
        
        # Branch operations on main/master
        if "branches" in path_lower and any(branch in path_lower for branch in ["main", "master"]):
            risk_multiplier += 0.5
            factors.append("Main/master branch operation")
            suggestions.append("Protect main branches from direct modification")
        
        # Force push operations
        if parameters.get("force"):
            risk_multiplier += 0.4
            factors.append("Force push operation")
            suggestions.append("Avoid force push on shared branches")
        
        # Large scale operations
        if "organizations" in path_lower or "teams" in path_lower:
            risk_multiplier += 0.3
            factors.append("Organization-level operation")
            suggestions.append("Verify organization permissions")
        
        return risk_multiplier, factors, suggestions
    
    def _analyze_notion_risk(
        self, 
        action_type: ActionType,
        resource_path: str,
        parameters: Dict[str, Any]
    ) -> Tuple[float, List[str], List[str]]:
        """Notion-specific risk analysis."""
        risk_multiplier = 1.0
        factors = []
        suggestions = []
        
        path_lower = resource_path.lower()
        
        # Database operations are high risk
        if "databases" in path_lower and action_type == ActionType.DELETE:
            risk_multiplier += 0.8
            factors.append("Database deletion detected")
            suggestions.append("Export database before deletion")
        
        # Workspace-level operations
        if "workspace" in path_lower:
            risk_multiplier += 0.4
            factors.append("Workspace-level operation")
            suggestions.append("Verify workspace permissions")
        
        # Bulk page operations
        if "pages" in path_lower and parameters.get("bulk"):
            risk_multiplier += 0.3
            factors.append("Bulk page operation")
            suggestions.append("Process pages in smaller batches")
        
        return risk_multiplier, factors, suggestions
    
    def _determine_risk_level(self, risk_score: float) -> RiskLevel:
        """Determine risk level based on score."""
        if risk_score >= 0.9:
            return RiskLevel.CRITICAL
        elif risk_score >= 0.7:
            return RiskLevel.HIGH
        elif risk_score >= 0.4:
            return RiskLevel.MEDIUM
        else:
            return RiskLevel.LOW
    
    def requires_approval(self, risk_assessment: RiskAssessment) -> bool:
        """Determine if action requires manual approval."""
        return (
            risk_assessment.score >= self.high_risk_threshold or
            risk_assessment.level in [RiskLevel.HIGH, RiskLevel.CRITICAL]
        )