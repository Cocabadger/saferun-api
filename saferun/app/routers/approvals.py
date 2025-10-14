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
    revert_window: Optional[int] = None  # Revert window in hours
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
    from datetime import datetime, timezone
    
    storage = storage_manager.get_storage()
    rec = storage.get_change(change_id)

    if not rec:
        raise HTTPException(status_code=404, detail="Approval request not found")

    requires_approval = bool(rec.get("requires_approval"))
    status = rec.get("status", "pending")
    
    # Check if operation expired
    revert_expires_at = rec.get("revert_expires_at")
    if revert_expires_at and status == "pending":
        # Parse timestamp
        if isinstance(revert_expires_at, str):
            expires_dt = datetime.fromisoformat(revert_expires_at.replace('Z', '+00:00'))
        else:
            expires_dt = revert_expires_at
        
        # Ensure timezone aware
        if expires_dt.tzinfo is None:
            expires_dt = expires_dt.replace(tzinfo=timezone.utc)
        
        now = datetime.now(timezone.utc)
        
        if now > expires_dt:
            # Auto-expire
            storage.set_change_status(change_id, "expired")
            status = "expired"
    
    approved = not requires_approval and status in {"pending", "approved", "applied"}

    # Parse JSON strings if needed
    import json
    summary_raw = rec.get("summary_json") or rec.get("summary") or "{}"
    if isinstance(summary_raw, str):
        try:
            summary_data = json.loads(summary_raw)
        except Exception as e:
            print(f"Failed to parse summary_json: {e}, raw: {summary_raw}")
            summary_data = {}
    else:
        summary_data = summary_raw

    # Ensure summary_data is always a dict
    if not isinstance(summary_data, dict):
        summary_data = {}

    # Parse metadata (may be stored as JSON string)
    metadata_raw = rec.get("metadata") or summary_data.get("metadata") or {}
    if isinstance(metadata_raw, str):
        try:
            metadata_parsed = json.loads(metadata_raw)
        except Exception:
            metadata_parsed = {}
    else:
        metadata_parsed = metadata_raw
    
    if not isinstance(metadata_parsed, dict):
        metadata_parsed = {}

    # Convert datetime objects to ISO strings
    from datetime import datetime
    def to_iso(val):
        if isinstance(val, datetime):
            return val.isoformat()
        return str(val) if val else ""

    return ApprovalDetailResponse(
        change_id=change_id,
        status=status,
        requires_approval=requires_approval,
        approved=approved,
        expires_at=to_iso(rec.get("expires_at")),
        human_preview=rec.get("human_preview") or summary_data.get("human_preview"),
        operation_type=summary_data.get("operation_type"),
        command=summary_data.get("command"),
        target=summary_data.get("target") or rec.get("target_id"),
        risk_score=float(rec.get("risk_score") or 0.0),
        reasons=summary_data.get("reasons") or [],
        metadata=metadata_parsed,
        revert_window=rec.get("revert_window"),  # Add revert_window
        created_at=to_iso(rec.get("created_at")),
    )


@router.post("/approvals/{change_id}/approve", response_model=ApprovalActionResponse)
async def approve_operation(change_id: str) -> ApprovalActionResponse:
    """
    Approve a pending operation.
    For CLI/SDK operations: sets requires_approval to False so they can proceed.
    For API operations with revert_window: executes immediately and sends notification.
    
    VERSION: 2025-10-14-v2 - UNARCHIVE FIX APPLIED
    """
    from datetime import datetime, timezone
    
    storage = storage_manager.get_storage()
    rec = storage.get_change(change_id)

    if not rec:
        raise HTTPException(status_code=404, detail="Approval request not found")

    current_status = rec.get("status", "pending")
    
    # Check if operation expired
    revert_expires_at = rec.get("revert_expires_at")
    if revert_expires_at and current_status == "pending":
        # Parse timestamp
        if isinstance(revert_expires_at, str):
            expires_dt = datetime.fromisoformat(revert_expires_at.replace('Z', '+00:00'))
        else:
            expires_dt = revert_expires_at
        
        # Ensure timezone aware
        if expires_dt.tzinfo is None:
            expires_dt = expires_dt.replace(tzinfo=timezone.utc)
        
        now = datetime.now(timezone.utc)
        
        if now > expires_dt:
            # Operation expired - abort
            storage.set_change_status(change_id, "expired")
            raise HTTPException(
                status_code=410,  # Gone
                detail="Operation expired after revert window. No action taken for security."
            )

    if current_status in {"applied", "cancelled", "rejected", "expired"}:
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

    # Check if this is an API operation with revert_window (needs immediate execution)
    revert_window_hours = rec.get("revert_window")
    if revert_window_hours is not None:
        # Execute the operation immediately
        import asyncio
        import os
        from datetime import datetime, timezone
        from .. import db_adapter as db_module
        
        provider = rec.get("provider")
        target_id = rec.get("target_id")
        token = rec.get("token")
        metadata = rec.get("metadata")
        api_key = rec.get("api_key")
        
        try:
            # Execute based on provider
            if provider == "github":
                from ..providers.github_provider import GitHubProvider
                
                # Get summary_json for operation_type
                summary_json = rec.get("summary_json", {})
                if isinstance(summary_json, str):
                    import json
                    try:
                        summary_json = json.loads(summary_json)
                    except Exception:
                        summary_json = {}
                
                # Parse metadata if it's a string
                if isinstance(metadata, str):
                    try:
                        metadata = json.loads(metadata)
                    except Exception:
                        metadata = {}
                
                operation_type = summary_json.get("operation_type") or metadata.get("operation_type") if metadata else None
                
                # Determine operation type from metadata
                object_type = metadata.get("object") if metadata else None
                
                # Parse owner/repo from target_id
                owner, repo = None, None
                if "/" in target_id:
                    parts = target_id.split("/")
                    owner, repo = parts[0], parts[1].split("#")[0] if "#" in parts[1] else parts[1]
                
                # Execute based on operation_type or object_type
                # FIXED: Check operation_type FIRST to avoid substring matching issues
                if operation_type == "github_repo_archive":
                    # Archive repository
                    await GitHubProvider.archive(target_id, token)
                    # Add revert_action for unarchive
                    rec["summary_json"] = {
                        "revert_action": {
                            "type": "repository_unarchive",
                            "owner": owner,
                            "repo": repo
                        }
                    }
                elif operation_type == "github_repo_unarchive":
                    # Unarchive repository
                    await GitHubProvider.unarchive(target_id, token)
                    # Add revert_action for archive
                    rec["summary_json"] = {
                        "revert_action": {
                            "type": "repository_archive",
                            "owner": owner,
                            "repo": repo
                        }
                    }
                elif object_type == "repository" and "archive" in str(summary_json) and "unarchive" not in str(summary_json):
                    # Fallback for archive (webhook)
                    await GitHubProvider.archive(target_id, token)
                    rec["summary_json"] = {
                        "revert_action": {
                            "type": "repository_unarchive",
                            "owner": owner,
                            "repo": repo
                        }
                    }
                elif object_type == "repository" and "unarchive" in str(summary_json):
                    # Fallback for unarchive (webhook)
                    await GitHubProvider.unarchive(target_id, token)
                    rec["summary_json"] = {
                        "revert_action": {
                            "type": "repository_archive",
                            "owner": owner,
                            "repo": repo
                        }
                    }
                elif object_type == "branch":
                    # Delete branch (stores SHA for revert)
                    revert_sha = await GitHubProvider.delete_branch(target_id, token)
                    rec["revert_token"] = revert_sha
                    rec["summary_json"] = {"github_restore_sha": revert_sha}
            
            # Update status to executed
            rec["status"] = "executed"
            rec["executed_at"] = db_module.iso_z(datetime.now(timezone.utc))
            storage.set_change_status(change_id, "executed")
            
            # Send Slack notification with revert instructions
            from ..notify import notifier
            
            # Build revert URL
            api_base = os.environ.get("API_BASE_URL") or os.environ.get("RAILWAY_PUBLIC_DOMAIN", "http://localhost:8500")
            if api_base and not api_base.startswith("http"):
                api_base = f"https://{api_base}"
            revert_url = f"{api_base}/webhooks/github/revert/{change_id}"
            
            # Send notification
            asyncio.create_task(
                notifier.publish(
                    "executed_with_revert",
                    rec,
                    extras={
                        "revert_url": revert_url,
                        "revert_window_hours": revert_window_hours,
                        "metadata": metadata,
                        "meta": {"latency_ms": 0, "provider_version": "unknown"}
                    },
                    api_key=api_key
                )
            )
            
        except Exception as e:
            # If execution fails, update status and re-raise
            print(f"[ERROR] Approval execution failed: {type(e).__name__}: {str(e)}")
            import traceback
            print(f"[ERROR] Traceback:\n{traceback.format_exc()}")
            rec["status"] = "failed"
            rec["error"] = str(e)
            storage.set_change_status(change_id, "failed")
            raise HTTPException(status_code=500, detail=f"Execution failed: {str(e)}")

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
    from datetime import datetime, timezone
    
    storage = storage_manager.get_storage()
    rec = storage.get_change(change_id)

    if not rec:
        raise HTTPException(status_code=404, detail="Approval request not found")

    current_status = rec.get("status", "pending")
    
    # Check if already expired (idempotent - return success)
    revert_expires_at = rec.get("revert_expires_at")
    if revert_expires_at and current_status == "pending":
        # Parse timestamp
        if isinstance(revert_expires_at, str):
            expires_dt = datetime.fromisoformat(revert_expires_at.replace('Z', '+00:00'))
        else:
            expires_dt = revert_expires_at
        
        # Ensure timezone aware
        if expires_dt.tzinfo is None:
            expires_dt = expires_dt.replace(tzinfo=timezone.utc)
        
        now = datetime.now(timezone.utc)
        
        if now > expires_dt:
            # Already expired - update status and return
            storage.set_change_status(change_id, "expired")
            return ApprovalActionResponse(
                change_id=change_id,
                status="expired",
                approved=False,
                message="Operation already expired. No action needed."
            )

    if current_status in {"applied", "cancelled", "rejected", "expired"}:
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
