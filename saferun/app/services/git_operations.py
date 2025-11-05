import asyncio
import os
import uuid
from datetime import datetime, timezone
from typing import Dict

from .. import storage as storage_manager
from .. import db_adapter as db
from ..notify import notifier
from .dryrun import expiry, new_change_id
from ..models.contracts import (
    GitOperationDryRunRequest,
    DryRunArchiveResponse,
    TargetRef,
    Summary,
    DiffUnit,
    GitOperationStatusResponse,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ttl_seconds(expires_at: datetime) -> int:
    ttl = int(expires_at.timestamp() - _now().timestamp())
    return ttl if ttl > 0 else 3600


def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(value, maximum))


async def build_git_operation_dryrun(req: GitOperationDryRunRequest, api_key: str | None = None) -> DryRunArchiveResponse:
    storage = storage_manager.get_storage()

    risk_score = _clamp(req.risk_score)
    requires_approval = req.requires_approval if req.requires_approval is not None else risk_score >= 0.5

    change_id = new_change_id()
    created_at = db.iso_z(db.now_utc())
    expires_dt = expiry(req.ttl_minutes)
    expires_at = db.iso_z(expires_dt)
    ttl_seconds = _ttl_seconds(expires_dt)

    summary_payload: Dict = {
        "operation_type": req.operation_type,
        "command": req.command,
        "metadata": req.metadata,
        "target": req.target,
        "human_preview": req.human_preview,
        "reasons": req.reasons or [],
    }

    title = req.metadata.get("title") or req.metadata.get("branch") or req.metadata.get("target") or req.operation_type.replace("_", " ").title()
    summary = Summary(
        title=title,
        parent_type=req.metadata.get("scope"),
        blocks_count=0,
        blocks_count_approx=True,
        last_edited_time=None,
    )

    human_preview = req.human_preview or title

    change_data = {
        "change_id": change_id,
        "target_id": req.target,
        "provider": "git",
        "title": title,
        "status": "pending",
        "risk_score": risk_score,
        "expires_at": expires_at,
        "created_at": created_at,
        "last_edited_time": req.metadata.get("last_commit_at"),
        "policy": req.policy or {},
        "summary_json": summary_payload,
        "summary": summary_payload,
        "token": req.metadata.get("token"),
        "requires_approval": requires_approval,
        "human_preview": human_preview,
        "webhook_url": req.webhook_url,
    }

    storage.save_change(change_id, change_data, ttl_seconds)

    approve_url = None
    if requires_approval:
        base_url = os.getenv("APP_BASE_URL", "http://localhost:8500")  # type: ignore[name-defined]
        approve_url = f"{base_url}/approvals/{change_id}"
        change_record = storage.get_change(change_id)
        if change_record:
            asyncio.create_task(
                notifier.publish(
                    "dry_run",
                    change_record,
                    extras={
                        "approve_url": approve_url,
                        "meta": {
                            "latency_ms": 0,
                            "operation_type": req.operation_type,
                        },
                    },
                    api_key=api_key,
                )
            )

    db.insert_audit(change_id, "dry_run", {"latency_ms": 0, "summary": summary_payload})

    telemetry = {
        "latency_ms": 0,
        "provider_version": "cli",
        "operation_type": req.operation_type,
    }

    return DryRunArchiveResponse(
        change_id=change_id,
        target=TargetRef(provider="git", target_id=req.target, type="operation"),
        summary=summary,
        diff=[
            DiffUnit(
                op="git_operation",
                impact={
                    "operation_type": req.operation_type,
                    "command": req.command,
                    "metadata": req.metadata,
                },
            )
        ],
        risk_score=risk_score,
        reasons=req.reasons or [],
        requires_approval=requires_approval,
        human_preview=human_preview,
        approve_url=approve_url,
        revert_url=None,
        telemetry=telemetry,
        expires_at=expires_dt,
        apply=False,
        note="Execute the git command locally after approval",
    )


def get_git_operation_status(change_id: str) -> GitOperationStatusResponse:
    storage = storage_manager.get_storage()
    rec = storage.get_change(change_id)
    if not rec:
        raise ValueError("Change not found")

    requires_approval = bool(rec.get("requires_approval"))
    status = rec.get("status", "pending")
    # Operation is approved if status is approved or executed
    approved = status in ["approved", "executed", "applied"]

    # Parse JSON strings if needed (Postgres returns TEXT fields as strings)
    import json
    summary_raw = rec.get("summary_json") or rec.get("summary") or {}

    summary_data = {}
    if isinstance(summary_raw, str):
        try:
            parsed = json.loads(summary_raw)
            if isinstance(parsed, dict):
                summary_data = parsed
        except:
            pass
    elif isinstance(summary_raw, dict):
        summary_data = summary_raw

    reasons = summary_data.get("reasons", []) if isinstance(summary_data, dict) else []

    return GitOperationStatusResponse(
        change_id=change_id,
        status=status,
        requires_approval=requires_approval,
        approved=approved,
        expires_at=db.parse_dt(rec.get("expires_at")),
        human_preview=rec.get("human_preview") or summary_data.get("human_preview"),
        operation_type=summary_data.get("operation_type"),
        risk_score=float(rec.get("risk_score") or 0.0),
        reasons=reasons,
    )


def confirm_git_operation(change_id: str, status: str, metadata: Dict | None = None) -> GitOperationStatusResponse:
    storage = storage_manager.get_storage()
    rec = storage.get_change(change_id)
    if not rec:
        raise ValueError("Change not found")

    metadata = metadata or {}

    set_change_approved = getattr(storage, "set_change_approved", None)
    if callable(set_change_approved):
        try:
            set_change_approved(change_id, True)
        except Exception:
            pass

    storage.set_change_status(change_id, status)
    db.insert_audit(change_id, status, metadata)

    updated = storage.get_change(change_id) or rec
    requires_approval = bool(updated.get("requires_approval"))
    approved = not requires_approval and status in {"pending", "approved", "applied"}

    # Parse JSON strings if needed (Postgres returns TEXT fields as strings)
    import json
    summary_raw = updated.get("summary_json") or updated.get("summary") or {}

    summary_data = {}
    if isinstance(summary_raw, str):
        try:
            parsed = json.loads(summary_raw)
            if isinstance(parsed, dict):
                summary_data = parsed
        except:
            pass
    elif isinstance(summary_raw, dict):
        summary_data = summary_raw

    return GitOperationStatusResponse(
        change_id=change_id,
        status=status,
        requires_approval=requires_approval,
        approved=approved,
        expires_at=db.parse_dt(updated.get("expires_at")),
        human_preview=updated.get("human_preview") or summary_data.get("human_preview"),
        operation_type=summary_data.get("operation_type"),
        risk_score=float(updated.get("risk_score") or 0.0),
        reasons=summary_data.get("reasons") or [],
    )
