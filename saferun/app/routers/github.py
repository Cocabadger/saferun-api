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
async def dry_run_github_repo(req: GitHubRepoArchiveDryRunRequest) -> DryRunArchiveResponse:
    generic_req = DryRunArchiveRequest(token=req.token, target_id=req.target_id, provider="github", policy=req.policy)
    return await build_dryrun(generic_req)

@router.post("/v1/dry-run/github.branch.delete", response_model=DryRunArchiveResponse)
async def dry_run_github_branch(req: GitHubBranchDeleteDryRunRequest) -> DryRunArchiveResponse:
    generic_req = DryRunArchiveRequest(token=req.token, target_id=req.target_id, provider="github", policy=req.policy)
    return await build_dryrun(generic_req)

@router.post("/v1/dry-run/github.bulk.close_prs", response_model=DryRunArchiveResponse)
async def dry_run_github_bulk(req: GitHubBulkClosePRsDryRunRequest) -> DryRunArchiveResponse:
    generic_req = DryRunArchiveRequest(token=req.token, target_id=req.target_id, provider="github", policy=req.policy)
    return await build_dryrun(generic_req)
