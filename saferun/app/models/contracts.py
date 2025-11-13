from pydantic import BaseModel, Field
from typing import List, Literal, Optional, Dict, Any
from datetime import datetime, timedelta, timezone
import uuid
from saferun import __version__ as SR_VERSION

ProviderLiteral = Literal["notion", "gdrive", "slack", "gsheets", "airtable", "github", "git"]

class AirtableRecordArchiveDryRunRequest(BaseModel):
    token: str
    target_id: str  # "baseId/tableId/recordId"
    policy: Optional[Dict] = None
    webhook_url: Optional[str] = None

class AirtableBulkArchiveDryRunRequest(BaseModel):
    token: str
    target_id: str  # "baseId/tableId @viewName"
    policy: Optional[Dict] = None
    webhook_url: Optional[str] = None


class DryRunNotionArchiveRequest(BaseModel):
    notion_token: str
    page_id: str
    policy: Optional[Dict] = None
    webhook_url: Optional[str] = None
class GitHubRepoArchiveDryRunRequest(BaseModel):
    token: str
    target_id: str  # "org/repo"
    policy: Optional[Dict] = None
    webhook_url: Optional[str] = None

class GitHubBranchDeleteDryRunRequest(BaseModel):
    token: str
    target_id: str  # "org/repo#branch"
    policy: Optional[Dict] = None
    webhook_url: Optional[str] = None

class GitHubBulkClosePRsDryRunRequest(BaseModel):
    token: str
    target_id: str  # "org/repo@open_prs"
    policy: Optional[Dict] = None
    webhook_url: Optional[str] = None


class GitHubRepoDeleteDryRunRequest(BaseModel):
    token: str
    target_id: str  # "org/repo"
    reason: Optional[str] = None
    policy: Optional[Dict] = None
    webhook_url: Optional[str] = None


class GitHubForcePushDryRunRequest(BaseModel):
    token: str
    target_id: str  # "org/repo#branch" format
    commits_ahead: int = 0
    reason: Optional[str] = None
    policy: Optional[Dict] = None
    webhook_url: Optional[str] = None


class GitHubMergeDryRunRequest(BaseModel):
    token: str
    target_id: str  # "org/repo" format
    source_branch: str
    target_branch: str
    reason: Optional[str] = None
    policy: Optional[Dict] = None
    webhook_url: Optional[str] = None


# Additional 7 Critical GitHub Operations

class GitHubRepoTransferDryRunRequest(BaseModel):
    token: str
    target_id: str  # "org/repo" format
    new_owner: str  # Username or organization to transfer to
    team_ids: Optional[List[int]] = None  # For org transfers
    reason: Optional[str] = None
    policy: Optional[Dict] = None
    webhook_url: Optional[str] = None


class GitHubSecretCreateDryRunRequest(BaseModel):
    token: str
    target_id: str  # "org/repo" format
    secret_name: str
    encrypted_value: str  # Must be encrypted with repo's public key
    reason: Optional[str] = None
    policy: Optional[Dict] = None
    webhook_url: Optional[str] = None


class GitHubSecretDeleteDryRunRequest(BaseModel):
    token: str
    target_id: str  # "org/repo" format
    secret_name: str
    reason: Optional[str] = None
    policy: Optional[Dict] = None
    webhook_url: Optional[str] = None


class GitHubWorkflowUpdateDryRunRequest(BaseModel):
    token: str
    target_id: str  # "org/repo" format
    path: str  # Must be in .github/workflows/
    content: str  # YAML workflow content
    message: str  # Commit message
    branch: Optional[str] = None
    sha: Optional[str] = None  # Current file SHA (for updates)
    reason: Optional[str] = None
    policy: Optional[Dict] = None
    webhook_url: Optional[str] = None


class GitHubBranchProtectionUpdateDryRunRequest(BaseModel):
    token: str
    target_id: str  # "org/repo" format
    branch: str
    required_reviews: Optional[int] = None
    dismiss_stale_reviews: Optional[bool] = None
    require_code_owner_reviews: Optional[bool] = None
    required_status_checks: Optional[List[str]] = None
    enforce_admins: Optional[bool] = None
    restrictions: Optional[Dict[str, Any]] = None
    reason: Optional[str] = None
    policy: Optional[Dict] = None
    webhook_url: Optional[str] = None


class GitHubBranchProtectionDeleteDryRunRequest(BaseModel):
    token: str
    target_id: str  # "org/repo" format
    branch: str
    reason: Optional[str] = None
    policy: Optional[Dict] = None
    webhook_url: Optional[str] = None


class GitHubRepoVisibilityChangeDryRunRequest(BaseModel):
    token: str
    target_id: str  # "org/repo" format
    private: bool  # True = make private, False = make public
    reason: Optional[str] = None
    policy: Optional[Dict] = None
    webhook_url: Optional[str] = None


class GitOperationDryRunRequest(BaseModel):
    operation_type: Literal[
        "force_push",
        "branch_delete",
        "hard_reset",
        "reset_hard",
        "clean",
        "rebase",
        "cherry_pick",
        "commit_protected",
        "push_protected",
        "custom",
    ]
    target: str
    command: str
    metadata: Dict = {}
    risk_score: float = Field(ge=0.0, le=10.0)  # Changed from 1.0 to 10.0 to support new scoring
    human_preview: str
    requires_approval: Optional[bool] = None
    reasons: List[str] = []
    policy: Optional[Dict] = None
    webhook_url: Optional[str] = None
    ttl_minutes: int = Field(default=30, ge=5, le=240)


class GitOperationStatusResponse(BaseModel):
    change_id: str
    status: str
    requires_approval: bool
    approved: bool
    expires_at: datetime
    human_preview: Optional[str] = None
    operation_type: Optional[str] = None
    risk_score: Optional[float] = None
    reasons: List[str] = []


class GitOperationConfirmRequest(BaseModel):
    change_id: str
    status: Literal["applied", "cancelled", "failed"] = "applied"
    metadata: Dict = {}





class DryRunArchiveRequest(BaseModel):
    token: str
    target_id: str
    provider: ProviderLiteral
    reason: Optional[str] = None
    policy: Optional[Dict] = None
    webhook_url: Optional[str] = None
    metadata: Optional[Dict] = None  # For passing operation context (e.g., object type for GitHub)

class DiffUnit(BaseModel):
    op: Literal["archive", "delete_branch", "bulk_preview", "git_operation"]
    impact: Dict

class TargetRef(BaseModel):
    provider: ProviderLiteral
    target_id: str
    type: Literal[
        "page",
        "db_item",
        "file",
        "folder",
        "record",
        "bulk_view",
        "repo",
        "branch",
        "bulk_pr",
        "channel",
        "operation",
    ]

class Summary(BaseModel):
    title: Optional[str]
    parent_type: Optional[str] = None
    blocks_count: int = 0
    blocks_count_approx: bool = True
    last_edited_time: Optional[datetime] = None
    # GitHub-specific summary fields (optional)
    name: Optional[str] = None
    stars: Optional[int] = None
    forks: Optional[int] = None
    lastPushedAt: Optional[str] = None
    isDefault: Optional[bool] = None
    lastCommitDate: Optional[str] = None

class DryRunArchiveResponse(BaseModel):
    service: str = "saferun"
    version: str = SR_VERSION
    status: str = "ok"
    change_id: str
    target: TargetRef
    summary: Summary
    diff: List[DiffUnit]
    risk_score: float = Field(ge=0.0, le=10.0)  # Changed from 1.0 to 10.0 to support new scoring
    reasons: List[str] = []
    requires_approval: bool = Field(default=True, alias="needsApproval", serialization_alias="needsApproval")
    human_preview: str
    telemetry: Dict
    approve_url: Optional[str] = None
    revert_url: Optional[str] = None
    revert_window_hours: Optional[int] = None
    apply: Optional[bool] = None
    note: Optional[str] = None
    records_affected: Optional[int] = None
    expires_at: datetime
    
    model_config = {
        "populate_by_name": True,  # Allow both requires_approval and needsApproval
        "by_alias": True  # CRITICAL: Use aliases (needsApproval) in serialization
    }


def new_change_id() -> str:
    return str(uuid.uuid4())

def expiry(minutes: int = 30) -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=minutes)


# Alias the notion response to the generic dry-run response shape for now
DryRunNotionArchiveResponse = DryRunArchiveResponse


# ============================================================================
# API OPERATION REQUESTS (Phase 1 MVP)
# ============================================================================

class ArchiveRepositoryRequest(BaseModel):
    """Request to archive a GitHub repository"""
    token: str = Field(..., description="GitHub Personal Access Token")
    reason: Optional[str] = Field(None, description="Optional reason for archiving")


class UnarchiveRepositoryRequest(BaseModel):
    """Request to unarchive a GitHub repository"""
    token: str = Field(..., description="GitHub Personal Access Token")
    reason: Optional[str] = Field(None, description="Optional reason for unarchiving")


class DeleteBranchRequest(BaseModel):
    """Request to delete a GitHub branch"""
    token: str = Field(..., description="GitHub Personal Access Token")
    reason: Optional[str] = Field(None, description="Optional reason for deletion")


class DeleteRepositoryRequest(BaseModel):
    """Request to delete a GitHub repository (PERMANENT)"""
    token: str = Field(..., description="GitHub Personal Access Token with delete_repo scope")
    reason: str = Field(..., min_length=20, description="Required reason for deletion (minimum 20 characters)")
    confirm_deletion: str = Field(..., description="Must be 'DELETE:{owner}/{repo}' to confirm")


class MergePullRequestRequest(BaseModel):
    """Request to merge a pull request"""
    token: str = Field(..., description="GitHub Personal Access Token")
    commit_title: Optional[str] = Field(None, description="Custom merge commit title")
    commit_message: Optional[str] = Field(None, description="Custom merge commit message")
    merge_method: Literal["merge", "squash", "rebase"] = Field("merge", description="Merge method to use")
    reason: Optional[str] = Field(None, description="Optional reason for merging")


class ForcePushRequest(BaseModel):
    """Request to force push to a branch"""
    token: str = Field(..., description="GitHub Personal Access Token")
    ref: str = Field(..., description="Git reference to update (e.g., 'refs/heads/main')")
    sha: str = Field(..., description="Target commit SHA to force push")
    reason: Optional[str] = Field(None, description="Optional reason for force push")


# ============================================================================
# API OPERATION RESPONSES (Phase 1 MVP)
# ============================================================================

class OperationResponse(BaseModel):
    """Standard response for operational API endpoints"""
    change_id: str = Field(..., description="Unique identifier for this operation")
    status: Literal["pending", "approved", "rejected", "executed", "expired"] = Field("pending", description="Current operation status")
    requires_approval: bool = Field(True, description="Whether human approval is required")
    revert_window_hours: int = Field(24, description="Hours until operation expires")
    expires_at: str = Field(..., description="ISO 8601 timestamp when operation expires")
    risk_score: float = Field(..., ge=0.0, le=10.0, description="Risk score (0.0-10.0)")
    revertable: bool = Field(True, description="Whether operation can be reverted after execution")
    revert_type: Optional[Literal["counter_commit", "branch_restore", "repository_unarchive", "restore_previous_sha"]] = Field(None, description="Type of revert available")
    warning: Optional[str] = Field(None, description="Critical warning for dangerous operations")
    message: str = Field(..., description="Human-readable status message")
