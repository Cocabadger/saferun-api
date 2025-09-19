"""
Core models for the SafeRun API.
"""

"""
Core models for the SafeRun API.
"""

from enum import Enum
from typing import Dict, List, Optional, Any, Union
from datetime import datetime
from pydantic import BaseModel, Field
import uuid


class ActionType(str, Enum):
    """Enumeration of supported action types."""
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    READ = "read"


class RiskLevel(str, Enum):
    """Risk levels for actions."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ActionStatus(str, Enum):
    """Status of action execution."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class ProviderType(str, Enum):
    """Supported provider types."""
    GITHUB = "github"
    NOTION = "notion"


class ActionRequest(BaseModel):
    """Request to perform an action through a provider."""
    provider: ProviderType
    action_type: ActionType
    resource_path: str = Field(..., description="Path to the resource being acted upon")
    parameters: Dict[str, Any] = Field(default_factory=dict)
    dry_run: bool = Field(default=True, description="Whether to perform a dry run")
    force: bool = Field(default=False, description="Force execution without approval")
    
    class Config:
        json_schema_extra = {
            "example": {
                "provider": "github",
                "action_type": "create",
                "resource_path": "repos/owner/repo/issues",
                "parameters": {
                    "title": "New issue",
                    "body": "Issue description"
                },
                "dry_run": True,
                "force": False
            }
        }


class RiskAssessment(BaseModel):
    """Risk assessment for an action."""
    score: float = Field(..., ge=0.0, le=1.0, description="Risk score from 0 to 1")
    level: RiskLevel
    factors: List[str] = Field(default_factory=list, description="Risk factors identified")
    mitigation_suggestions: List[str] = Field(default_factory=list)
    
    class Config:
        json_schema_extra = {
            "example": {
                "score": 0.8,
                "level": "high",
                "factors": ["Destructive operation", "Production environment"],
                "mitigation_suggestions": ["Use dry-run first", "Get manual approval"]
            }
        }


class ActionPreview(BaseModel):
    """Preview of what an action would do."""
    action_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    provider: ProviderType
    action_type: ActionType
    resource_path: str
    parameters: Dict[str, Any]
    risk_assessment: RiskAssessment
    predicted_changes: List[str] = Field(default_factory=list)
    affected_resources: List[str] = Field(default_factory=list)
    requires_approval: bool
    estimated_duration: Optional[float] = Field(None, description="Estimated duration in seconds")
    
    class Config:
        json_schema_extra = {
            "example": {
                "action_id": "123e4567-e89b-12d3-a456-426614174000",
                "provider": "github",
                "action_type": "delete",
                "resource_path": "repos/owner/repo/branches/feature-branch",
                "parameters": {},
                "risk_assessment": {
                    "score": 0.9,
                    "level": "critical",
                    "factors": ["Branch deletion", "Contains unmerged commits"],
                    "mitigation_suggestions": ["Backup branch first", "Confirm with team"]
                },
                "predicted_changes": ["Delete branch 'feature-branch'"],
                "affected_resources": ["refs/heads/feature-branch"],
                "requires_approval": True,
                "estimated_duration": 2.5
            }
        }


class ActionExecution(BaseModel):
    """Details of action execution."""
    action_id: str
    status: ActionStatus
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    rollback_data: Optional[Dict[str, Any]] = None
    approval_required: bool = False
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None


class RollbackRequest(BaseModel):
    """Request to rollback an action."""
    action_id: str
    reason: Optional[str] = None


class RollbackResult(BaseModel):
    """Result of a rollback operation."""
    action_id: str
    rollback_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: ActionStatus
    rollback_actions: List[str] = Field(default_factory=list)
    completed_at: Optional[datetime] = None
    error: Optional[str] = None


class APIKeyRequest(BaseModel):
    """Request for API key authentication."""
    api_key: str


class AuthToken(BaseModel):
    """Authentication token response."""
    access_token: str
    token_type: str = "bearer"
    expires_in: int


__all__ = [
    "ActionType",
    "RiskLevel", 
    "ActionStatus",
    "ProviderType",
    "ActionRequest",
    "RiskAssessment",
    "ActionPreview",
    "ActionExecution",
    "RollbackRequest",
    "RollbackResult",
    "APIKeyRequest",
    "AuthToken",
]