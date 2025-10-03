from fastapi import APIRouter, Depends
from ..services.dryrun import build_dryrun
from ..models.contracts import (
    DryRunArchiveResponse,
    DryRunArchiveRequest,
    GitHubRepoArchiveDryRunRequest,
    GitHubBranchDeleteDryRunRequest,
    GitHubBulkClosePRsDryRunRequest,
)
from .auth import verify_api_key

router = APIRouter(tags=["Archive"], dependencies=[Depends(verify_api_key)]) 

@router.post("/v1/dry-run/github.repo.archive", response_model=DryRunArchiveResponse)
async def dry_run_github_repo(req: GitHubRepoArchiveDryRunRequest, api_key: str = Depends(verify_api_key)) -> DryRunArchiveResponse:
    generic_req = DryRunArchiveRequest(
        token=req.token,
        target_id=req.target_id,
        provider="github",
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
        policy=req.policy,
        webhook_url=getattr(req, 'webhook_url', None)
    )
    return await build_dryrun(generic_req, api_key=api_key)
