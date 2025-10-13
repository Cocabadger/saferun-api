from fastapi import APIRouter, Depends, HTTPException
from ..services.dryrun import build_dryrun
from ..models.contracts import (
    DryRunArchiveResponse,
    DryRunArchiveRequest,
    GitHubRepoArchiveDryRunRequest,
    GitHubBranchDeleteDryRunRequest,
    GitHubBulkClosePRsDryRunRequest,
    GitHubRepoDeleteDryRunRequest,
    GitHubForcePushDryRunRequest,
    GitHubMergeDryRunRequest,
    ArchiveRepositoryRequest,
    UnarchiveRepositoryRequest,
    DeleteBranchRequest,
    DeleteRepositoryRequest,
    MergePullRequestRequest,
    ForcePushRequest,
    OperationResponse,
)
from .auth import verify_api_key
from pydantic import BaseModel
from typing import Optional, Any, Dict
import uuid
import os
from datetime import datetime, timedelta
import hashlib

router = APIRouter(tags=["GitHub"], dependencies=[Depends(verify_api_key)]) 

@router.post("/v1/dry-run/github.repo.archive", response_model=DryRunArchiveResponse)
async def dry_run_github_repo(req: GitHubRepoArchiveDryRunRequest, api_key: str = Depends(verify_api_key)) -> DryRunArchiveResponse:
    # Extract owner/repo from target_id for metadata
    owner, repo = req.target_id.split("/") if "/" in req.target_id else (None, req.target_id)
    
    generic_req = DryRunArchiveRequest(
        token=req.token,
        target_id=req.target_id,
        provider="github",
        reason=getattr(req, 'reason', None),
        policy=req.policy,
        webhook_url=req.webhook_url,
        metadata={"object": "repository", "owner": owner, "repo": repo}
    )
    return await build_dryrun(generic_req, api_key=api_key)

@router.post("/v1/dry-run/github.branch.delete", response_model=DryRunArchiveResponse)
async def dry_run_github_branch(req: GitHubBranchDeleteDryRunRequest, api_key: str = Depends(verify_api_key)) -> DryRunArchiveResponse:
    # Extract owner/repo and branch from target_id (format: "owner/repo#branch")
    repo_part, branch = req.target_id.split("#") if "#" in req.target_id else (req.target_id, None)
    owner, repo = repo_part.split("/") if "/" in repo_part else (None, repo_part)
    
    generic_req = DryRunArchiveRequest(
        token=req.token,
        target_id=req.target_id,
        provider="github",
        reason=getattr(req, 'reason', None),
        policy=req.policy,
        webhook_url=getattr(req, 'webhook_url', None),
        metadata={"object": "branch", "owner": owner, "repo": repo, "name": branch}
    )
    return await build_dryrun(generic_req, api_key=api_key)

@router.post("/v1/dry-run/github.bulk.close_prs", response_model=DryRunArchiveResponse)
async def dry_run_github_bulk(req: GitHubBulkClosePRsDryRunRequest, api_key: str = Depends(verify_api_key)) -> DryRunArchiveResponse:
    owner, repo = req.target_id.split("/") if "/" in req.target_id else (None, req.target_id)
    
    generic_req = DryRunArchiveRequest(
        token=req.token,
        target_id=req.target_id,
        provider="github",
        reason=getattr(req, 'reason', None),
        policy=req.policy,
        webhook_url=getattr(req, 'webhook_url', None),
        metadata={"object": "pull_requests", "owner": owner, "repo": repo}
    )
    return await build_dryrun(generic_req, api_key=api_key)

@router.post("/v1/dry-run/github.repo.delete", response_model=DryRunArchiveResponse)
async def dry_run_github_repo_delete(req: GitHubRepoDeleteDryRunRequest, api_key: str = Depends(verify_api_key)) -> DryRunArchiveResponse:
    """Delete GitHub repository - IRREVERSIBLE operation, ALWAYS requires approval"""
    owner, repo = req.target_id.split("/") if "/" in req.target_id else (None, req.target_id)
    
    generic_req = DryRunArchiveRequest(
        token=req.token,
        target_id=req.target_id,
        provider="github",
        reason=req.reason or "Delete repository (PERMANENT - cannot be undone)",
        policy=req.policy,
        webhook_url=req.webhook_url,
        metadata={"object": "repository", "operation_type": "delete_repo", "owner": owner, "repo": repo}
    )
    return await build_dryrun(generic_req, api_key=api_key)

@router.post("/v1/dry-run/github.force-push", response_model=DryRunArchiveResponse)
async def dry_run_github_force_push(req: GitHubForcePushDryRunRequest, api_key: str = Depends(verify_api_key)) -> DryRunArchiveResponse:
    """Force push to GitHub branch - IRREVERSIBLE operation, always requires approval"""
    # Extract owner/repo and branch from target_id (format: "owner/repo#branch")
    repo_part, branch = req.target_id.split("#") if "#" in req.target_id else (req.target_id, None)
    owner, repo = repo_part.split("/") if "/" in repo_part else (None, repo_part)
    
    generic_req = DryRunArchiveRequest(
        token=req.token,
        target_id=req.target_id,  # Format: "owner/repo#branch"
        provider="github",
        policy=req.policy,
        webhook_url=req.webhook_url,
        reason=req.reason or "FORCE-PUSH: Rewrite branch history (DANGEROUS)",
        metadata={"object": "branch", "operation_type": "force_push", "owner": owner, "repo": repo, "name": branch}
    )
    return await build_dryrun(generic_req, api_key=api_key)

@router.post("/v1/dry-run/github.merge", response_model=DryRunArchiveResponse)
async def dry_run_github_merge(req: GitHubMergeDryRunRequest, api_key: str = Depends(verify_api_key)) -> DryRunArchiveResponse:
    """Merge branches on GitHub - IRREVERSIBLE operation, always requires approval"""
    # Construct target_id: org/repo#source_branch→target_branch
    target_id = f"{req.target_id}#{req.source_branch}→{req.target_branch}"
    owner, repo = req.target_id.split("/") if "/" in req.target_id else (None, req.target_id)
    
    generic_req = DryRunArchiveRequest(
        token=req.token,
        target_id=target_id,
        provider="github",
        reason=req.reason or f"Merge {req.source_branch} → {req.target_branch}",
        policy=req.policy,
        webhook_url=req.webhook_url,
        metadata={
            "object": "branch",
            "operation_type": "merge",
            "owner": owner,
            "repo": repo,
            "source_branch": req.source_branch,
            "target_branch": req.target_branch
        }
    )
    return await build_dryrun(generic_req, api_key=api_key)


# Response model for change status
class ChangeStatusResponse(BaseModel):
    change_id: str
    status: str  # pending, approved, executed, rejected, failed
    provider: Optional[str] = None
    target_id: Optional[str] = None
    title: Optional[str] = None
    risk_score: Optional[float] = None
    requires_approval: Optional[bool] = None
    executed_at: Optional[str] = None
    revert_expires_at: Optional[str] = None
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


@router.get("/v1/changes/{change_id}", response_model=ChangeStatusResponse)
async def get_change_status(change_id: str, api_key: str = Depends(verify_api_key)) -> ChangeStatusResponse:
    """
    Poll change status for API operations with approval.
    Returns current status: pending, approved, executed, rejected, or failed.
    """
    from .. import storage as storage_manager
    
    storage = storage_manager.get_storage()
    change = storage.get_change(change_id)
    
    if not change:
        raise HTTPException(status_code=404, detail="Change not found or expired")
    
    # Parse metadata if it's a JSON string
    metadata = change.get("metadata")
    if isinstance(metadata, str):
        import json
        try:
            metadata = json.loads(metadata)
        except Exception:
            metadata = None
    
    return ChangeStatusResponse(
        change_id=change_id,
        status=change.get("status", "pending"),
        provider=change.get("provider"),
        target_id=change.get("target_id"),
        title=change.get("title"),
        risk_score=change.get("risk_score"),
        requires_approval=change.get("requires_approval"),
        executed_at=change.get("executed_at"),
        revert_expires_at=change.get("revert_expires_at"),
        error=change.get("error"),
        metadata=metadata
    )


# ============================================================================
# OPERATIONAL API ENDPOINTS (Phase 1 MVP)
# ============================================================================

async def create_pending_operation(
    operation_type: str,
    owner: str,
    repo: str,
    api_key: str,
    token: str,
    reason: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> tuple[str, float]:
    """
    Helper function to create a pending operation.
    
    Returns: (change_id, risk_score)
    """
    from .. import db_postgres as db
    from ..notify import notifier
    
    # 1. Calculate risk score
    target_id = f"{owner}/{repo}"
    if metadata and metadata.get("branch"):
        target_id = f"{owner}/{repo}#{metadata['branch']}"
    
    # Determine risk score based on operation type
    risk_score = 8.0  # Default for archive
    if operation_type == "github_repo_archive":
        risk_score = 8.0
    elif operation_type == "github_repo_unarchive":
        risk_score = 6.0
    elif operation_type == "github_repo_delete":
        risk_score = 10.0
    elif operation_type == "github_branch_delete":
        risk_score = 7.0 if "main" in target_id or "master" in target_id else 4.0
    elif operation_type == "github_pr_merge":
        risk_score = 6.0
    elif operation_type == "github_force_push":
        risk_score = 9.0 if "main" in target_id or "master" in target_id else 7.0
    
    # 2. Create pending operation in database
    change_id = str(uuid.uuid4())
    expires_at = datetime.now() + timedelta(hours=24)
    
    change_record = {
        "change_id": change_id,
        "target_id": target_id,
        "provider": "github",
        "title": f"{operation_type.replace('_', ' ').title()}",
        "status": "pending",
        "risk_score": risk_score,
        "requires_approval": True,
        "api_key": api_key,
        "expires_at": expires_at.isoformat(),
        "created_at": datetime.now().isoformat(),
        "revert_window": 24,
        "revert_expires_at": expires_at.isoformat(),
        "summary_json": {
            **(metadata or {}),
            "owner": owner,
            "repo": repo,
            "operation": operation_type,
            "operation_type": operation_type,
            "token_hash": hashlib.sha256(token.encode()).hexdigest()[:16],
            "reason": reason
        },
        "metadata": {
            "object": metadata.get("object", "repository") if metadata else "repository",
            "owner": owner,
            "repo": repo,
            "operation_type": operation_type
        }
    }
    
    db.upsert_change(change_record)
    
    # 3. Send Slack notification
    try:
        # Build extras for notification
        api_base = os.getenv("APP_BASE_URL", "https://saferun-api.up.railway.app")
        extras = {
            "approve_url": f"{api_base}/approvals/{change_id}",
            "revert_window_hours": 24,
            "metadata": change_record["metadata"]
        }
        
        # Send notification via notifier.publish
        await notifier.publish(
            event="dry_run",  # Use dry_run event to show approval buttons in Slack
            change=change_record,
            extras=extras,
            api_key=api_key
        )
    except Exception as e:
        # Log error but don't fail the request
        print(f"Failed to send Slack notification: {e}")
    
    return change_id, risk_score


@router.post("/v1/github/repos/{owner}/{repo}/archive", response_model=OperationResponse)
async def archive_repository(
    owner: str,
    repo: str,
    req: ArchiveRepositoryRequest,
    api_key: str = Depends(verify_api_key)
) -> OperationResponse:
    """
    Archive a GitHub repository with human approval requirement.
    
    Flow:
    1. Validates GitHub token
    2. Calculates risk score (typically 8.0)
    3. Creates pending operation in database
    4. Sends Slack notification with Approve/Reject buttons
    5. Returns change_id for tracking
    6. Operation executes after human approval
    
    Args:
        owner: Repository owner (username or org name)
        repo: Repository name
        req: Request containing GitHub token and optional reason
        api_key: SafeRun API key (from header)
    
    Returns:
        OperationResponse with change_id and status
    
    Example:
        ```bash
        curl -X POST https://saferun-api.up.railway.app/v1/github/repos/owner/repo/archive \\
          -H "X-API-Key: YOUR_API_KEY" \\
          -H "Content-Type: application/json" \\
          -d '{"token": "ghp_...", "reason": "Archiving old project"}'
        ```
    """
    # Create pending operation
    change_id, risk_score = await create_pending_operation(
        operation_type="github_repo_archive",
        owner=owner,
        repo=repo,
        api_key=api_key,
        token=req.token,
        reason=req.reason,
        metadata={"object": "repository", "operation": "archive"}
    )
    
    # Return response
    expires_at = datetime.now() + timedelta(hours=24)
    return OperationResponse(
        change_id=change_id,
        status="pending",
        requires_approval=True,
        revert_window_hours=24,
        expires_at=expires_at.isoformat(),
        risk_score=risk_score,
        revertable=True,
        revert_type="repository_unarchive",
        message="Archive request created. Check Slack for approval."
    )


@router.post("/v1/github/repos/{owner}/{repo}/unarchive", response_model=OperationResponse)
async def unarchive_repository(
    owner: str,
    repo: str,
    req: UnarchiveRepositoryRequest,
    api_key: str = Depends(verify_api_key)
) -> OperationResponse:
    """
    Unarchive a GitHub repository with human approval requirement.
    
    Similar to archive but with lower risk score (typically 6.0).
    """
    # Create pending operation
    change_id, risk_score = await create_pending_operation(
        operation_type="github_repo_unarchive",
        owner=owner,
        repo=repo,
        api_key=api_key,
        token=req.token,
        reason=req.reason,
        metadata={"object": "repository", "operation": "unarchive"}
    )
    
    # Return response
    expires_at = datetime.now() + timedelta(hours=24)
    return OperationResponse(
        change_id=change_id,
        status="pending",
        requires_approval=True,
        revert_window_hours=24,
        expires_at=expires_at.isoformat(),
        risk_score=risk_score,
        revertable=True,
        revert_type="repository_unarchive",
        message="Unarchive request created. Check Slack for approval."
    )


