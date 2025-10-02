from fastapi import APIRouter, Depends, HTTPException

from ..models.contracts import (
    DryRunArchiveResponse,
    GitOperationConfirmRequest,
    GitOperationDryRunRequest,
    GitOperationStatusResponse,
)
from ..routers.auth import verify_api_key
from ..services.git_operations import (
    build_git_operation_dryrun,
    confirm_git_operation,
    get_git_operation_status,
)

router = APIRouter(tags=["Git Operations"], dependencies=[Depends(verify_api_key)])


@router.post("/v1/dry-run/git.operation", response_model=DryRunArchiveResponse)
async def dry_run_git_operation(req: GitOperationDryRunRequest) -> DryRunArchiveResponse:
    return await build_git_operation_dryrun(req)


@router.get("/v1/git/operations/{change_id}", response_model=GitOperationStatusResponse)
async def git_operation_status(change_id: str) -> GitOperationStatusResponse:
    try:
        return get_git_operation_status(change_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/v1/git/operations/confirm", response_model=GitOperationStatusResponse)
async def git_operation_confirm(body: GitOperationConfirmRequest) -> GitOperationStatusResponse:
    try:
        return confirm_git_operation(body.change_id, body.status, body.metadata)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
