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
)
from .auth import verify_api_key
from pydantic import BaseModel
from typing import Optional, Any, Dict

router = APIRouter(tags=["GitHub"], dependencies=[Depends(verify_api_key)]) 

@router.post("/v1/dry-run/github.repo.archive", response_model=DryRunArchiveResponse)
async def dry_run_github_repo(req: GitHubRepoArchiveDryRunRequest, api_key: str = Depends(verify_api_key)) -> DryRunArchiveResponse:
    generic_req = DryRunArchiveRequest(
        token=req.token,
        target_id=req.target_id,
        provider="github",
        reason=getattr(req, 'reason', None),
        policy=req.policy,
        webhook_url=req.webhook_url
    )
    return await build_dryrun(generic_req, api_key=api_key)

@router.post("/v1/dry-run/github.branch.delete", response_model=DryRunArchiveResponse)
async def dry_run_github_branch(req: GitHubBranchDeleteDryRunRequest, api_key: str = Depends(verify_api_key)) -> DryRunArchiveResponse:
    generic_req = DryRunArchiveRequest(
        token=req.token,
        target_id=req.target_id,
        provider="github",
        reason=getattr(req, 'reason', None),
        policy=req.policy,
        webhook_url=getattr(req, 'webhook_url', None)
    )
    return await build_dryrun(generic_req, api_key=api_key)

@router.post("/v1/dry-run/github.bulk.close_prs", response_model=DryRunArchiveResponse)
async def dry_run_github_bulk(req: GitHubBulkClosePRsDryRunRequest, api_key: str = Depends(verify_api_key)) -> DryRunArchiveResponse:
    generic_req = DryRunArchiveRequest(
        token=req.token,
        target_id=req.target_id,
        provider="github",
        reason=getattr(req, 'reason', None),
        policy=req.policy,
        webhook_url=getattr(req, 'webhook_url', None)
    )
    return await build_dryrun(generic_req, api_key=api_key)

@router.post("/v1/dry-run/github.repo.delete", response_model=DryRunArchiveResponse)
async def dry_run_github_repo_delete(req: GitHubRepoDeleteDryRunRequest, api_key: str = Depends(verify_api_key)) -> DryRunArchiveResponse:
    """Delete GitHub repository - IRREVERSIBLE operation, ALWAYS requires approval"""
    generic_req = DryRunArchiveRequest(
        token=req.token,
        target_id=req.target_id,
        provider="github",
        reason=req.reason or "Delete repository (PERMANENT - cannot be undone)",
        policy=req.policy,
        webhook_url=req.webhook_url
    )
    return await build_dryrun(generic_req, api_key=api_key)

@router.post("/v1/dry-run/github.force-push", response_model=DryRunArchiveResponse)
async def dry_run_github_force_push(req: GitHubForcePushDryRunRequest, api_key: str = Depends(verify_api_key)) -> DryRunArchiveResponse:
    """Force push to GitHub branch - IRREVERSIBLE operation, always requires approval"""
    # Mark as force-push operation in metadata
    generic_req = DryRunArchiveRequest(
        token=req.token,
        target_id=req.target_id,  # Format: "owner/repo#branch"
        provider="github",
        policy=req.policy,
        webhook_url=req.webhook_url,
        reason=req.reason or "FORCE-PUSH: Rewrite branch history (DANGEROUS)"
    )
    return await build_dryrun(generic_req, api_key=api_key)

@router.post("/v1/dry-run/github.merge", response_model=DryRunArchiveResponse)
async def dry_run_github_merge(req: GitHubMergeDryRunRequest, api_key: str = Depends(verify_api_key)) -> DryRunArchiveResponse:
    """Merge branches on GitHub - IRREVERSIBLE operation, always requires approval"""
    # Construct target_id: org/repo#source_branch→target_branch
    target_id = f"{req.target_id}#{req.source_branch}→{req.target_branch}"
    generic_req = DryRunArchiveRequest(
        token=req.token,
        target_id=target_id,
        provider="github",
        reason=req.reason or f"Merge {req.source_branch} → {req.target_branch}",
        policy=req.policy,
        webhook_url=req.webhook_url
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

