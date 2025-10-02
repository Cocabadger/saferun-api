from fastapi import APIRouter, HTTPException
from typing import Dict, Optional
from pydantic import BaseModel

from .. import storage as storage_manager
from .. import db_adapter as db
from ..models.contracts import GitOperationStatusResponse

router = APIRouter(tags=["Approvals"], prefix="/api")


class ApprovalDetailResponse(BaseModel):
    change_id: str
    status: str
    requires_approval: bool
    approved: bool
    expires_at: str
    human_preview: Optional[str] = None
    operation_type: Optional[str] = None
    command: Optional[str] = None
    target: Optional[str] = None
    risk_score: float
    reasons: list[str] = []
    metadata: Dict = {}
    created_at: Optional[str] = None


class ApprovalActionResponse(BaseModel):
    change_id: str
    status: str
    approved: bool
    message: str


@router.get("/approvals/{change_id}", response_model=ApprovalDetailResponse)
async def get_approval_details(change_id: str) -> ApprovalDetailResponse:
    """
    Get detailed information about a pending approval request.
    Used by the web dashboard to display operation details.
    """
    storage = storage_manager.get_storage()
    rec = storage.get_change(change_id)

    if not rec:
        raise HTTPException(status_code=404, detail="Approval request not found")

    requires_approval = bool(rec.get("requires_approval"))
    status = rec.get("status", "pending")
    approved = not requires_approval and status in {"pending", "approved", "applied"}

    # Parse JSON strings if needed
    import json
    summary_raw = rec.get("summary_json") or rec.get("summary") or {}
    if isinstance(summary_raw, str):
        try:
            summary_data = json.loads(summary_raw)
        except:
            summary_data = {}
    else:
        summary_data = summary_raw

    return ApprovalDetailResponse(
        change_id=change_id,
        status=status,
        requires_approval=requires_approval,
        approved=approved,
        expires_at=rec.get("expires_at", ""),
        human_preview=rec.get("human_preview") or summary_data.get("human_preview"),
        operation_type=summary_data.get("operation_type"),
        command=summary_data.get("command"),
        target=summary_data.get("target") or rec.get("target_id"),
        risk_score=float(rec.get("risk_score") or 0.0),
        reasons=summary_data.get("reasons") or [],
        metadata=summary_data.get("metadata") or {},
        created_at=rec.get("created_at"),
    )


@router.post("/approvals/{change_id}/approve", response_model=ApprovalActionResponse)
async def approve_operation(change_id: str) -> ApprovalActionResponse:
    """
    Approve a pending operation.
    Sets requires_approval to False so the CLI can proceed with execution.
    """
    storage = storage_manager.get_storage()
    rec = storage.get_change(change_id)

    if not rec:
        raise HTTPException(status_code=404, detail="Approval request not found")

    current_status = rec.get("status", "pending")

    if current_status in {"applied", "cancelled", "rejected"}:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot approve: operation already {current_status}"
        )

    # Mark as approved by clearing requires_approval flag
    set_change_approved = getattr(storage, "set_change_approved", None)
    if callable(set_change_approved):
        set_change_approved(change_id, True)

    # Update status to approved
    storage.set_change_status(change_id, "approved")
    db.insert_audit(change_id, "approved", {"approved_via": "web_dashboard"})

    return ApprovalActionResponse(
        change_id=change_id,
        status="approved",
        approved=True,
        message="Operation approved successfully. CLI will proceed with execution.",
    )


@router.post("/approvals/{change_id}/reject", response_model=ApprovalActionResponse)
async def reject_operation(change_id: str) -> ApprovalActionResponse:
    """
    Reject a pending operation.
    Sets status to rejected so the CLI will abort.
    """
    storage = storage_manager.get_storage()
    rec = storage.get_change(change_id)

    if not rec:
        raise HTTPException(status_code=404, detail="Approval request not found")

    current_status = rec.get("status", "pending")

    if current_status in {"applied", "cancelled", "rejected"}:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot reject: operation already {current_status}"
        )

    # Mark as rejected
    storage.set_change_status(change_id, "rejected")
    db.insert_audit(change_id, "rejected", {"rejected_via": "web_dashboard"})

    return ApprovalActionResponse(
        change_id=change_id,
        status="rejected",
        approved=False,
        message="Operation rejected successfully. CLI will abort execution.",
    )
