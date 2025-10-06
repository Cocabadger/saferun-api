from fastapi import APIRouter, Depends
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
        reason=req.reason
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
