from fastapi import APIRouter, Depends, HTTPException

from ..models.contracts import (
    DryRunArchiveResponse,
    GitOperationConfirmRequest,
    GitOperationDryRunRequest,
    GitOperationStatusResponse,
)
from ..routers.auth import verify_api_key
from ..routers.auth_helpers import verify_change_ownership
from .. import storage as storage_manager
from ..services.git_operations import (
    build_git_operation_dryrun,
    confirm_git_operation,
    get_git_operation_status,
)

router = APIRouter(tags=["Git Operations"], dependencies=[Depends(verify_api_key)])


@router.post("/v1/dry-run/git.operation", response_model=DryRunArchiveResponse, response_model_by_alias=True)
async def git_operation(req: GitOperationDryRunRequest, api_key: str = Depends(verify_api_key)) -> DryRunArchiveResponse:
    return await build_git_operation_dryrun(req, api_key=api_key)


@router.get("/v1/git/operations/{change_id}", response_model=GitOperationStatusResponse)
async def git_operation_status(
    change_id: str,
    api_key: str = Depends(verify_api_key)
) -> GitOperationStatusResponse:
    storage = storage_manager.get_storage()
    verify_change_ownership(change_id, api_key, storage)
    
    try:
        return get_git_operation_status(change_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/v1/git/operations/confirm", response_model=GitOperationStatusResponse)
async def git_operation_confirm(
    body: GitOperationConfirmRequest,
    api_key: str = Depends(verify_api_key)
) -> GitOperationStatusResponse:
    storage = storage_manager.get_storage()
    verify_change_ownership(body.change_id, api_key, storage)
    
    try:
        return confirm_git_operation(body.change_id, body.status, body.metadata)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
