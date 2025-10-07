from fastapi import APIRouter, HTTPException, Depends
import json
from pydantic import BaseModel
import asyncio
from ..notify import notifier
from ..models.contracts import DryRunArchiveRequest, DryRunArchiveResponse, ProviderLiteral
from ..services.dryrun import build_dryrun
from ..metrics import time_apply, time_revert, time_dryrun, record_change_status
from .. import db_adapter as db
from .. import storage as storage_manager
from ..providers import factory as provider_factory
from ..providers.base import Provider
from typing import Dict
import uuid
from datetime import datetime, timezone
from saferun import __version__ as SR_VERSION
from .auth import verify_api_key

router = APIRouter(prefix="/v1", tags=["Archive"], dependencies=[Depends(verify_api_key)]) 

def _get_provider(name: str) -> Provider | None:
    try:
        return provider_factory.get_provider(name)  # type: ignore[return-value]
    except Exception:
        return None

class DryRunArchiveRequestIn(BaseModel):
    token: str
    target_id: str
    provider: ProviderLiteral | None = None
    policy: Dict | None = None


@router.post("/dry-run/{provider_name}.archive", response_model=DryRunArchiveResponse)
async def dry_run_archive(provider_name: str, payload: DryRunArchiveRequestIn, api_key: str = Depends(verify_api_key)):
    # provider_name may include a type suffix like "github.repo"; extract the provider id
    provider_id = provider_name.split(".", 1)[0]
    if not _get_provider(provider_id):
        raise HTTPException(status_code=400, detail=f"Unsupported provider: {provider_id}")
    # Normalize/validate provider: accept missing provider in body, enforce equality if present
    if payload.provider and payload.provider != provider_id:
        raise HTTPException(status_code=400, detail="Provider mismatch in path and body")

    # Build strict request model used by service layer
    # Special-case alias: support slack.channel.archive using same provider
    if provider_name.startswith("slack."):
        provider_id = "slack"

    strict_req = DryRunArchiveRequest(
        token=payload.token,
        target_id=payload.target_id,
        provider=provider_id,  # authoritative from path
        policy=payload.policy,
    )

    # Timing and request counting for dry-run are handled inside build_dryrun
    try:
        resp = await build_dryrun(strict_req, api_key=api_key)
        return resp
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Provider API error: {e}")


class ApplyRequest(BaseModel):
    change_id: str
    approval: bool | None = None
    admin_override: bool | None = None
    # Optional token override (e.g., Slack: apply with user token if bot lacks access)
    token: str | None = None


class ApplyResponse(BaseModel):
    service: str = "saferun"
    version: str = SR_VERSION
    change_id: str
    status: str
    revert_token: str | None = None
    applied_at: str | None = None
    telemetry: dict | None = None


class RevertRequest(BaseModel):
    revert_token: str
    # Optional token override for providers that require a different principal for revert
    token: str | None = None


class RevertResponse(BaseModel):
    service: str = "saferun"
    version: str = SR_VERSION
    revert_token: str
    status: str
    telemetry: dict | None = None


@router.post("/apply", response_model=ApplyResponse)
async def apply_change(body: ApplyRequest, api_key: str = Depends(verify_api_key)):
    storage = storage_manager.get_storage()
    rec = storage.get_change(body.change_id)
    if not rec:
        raise HTTPException(404, "change_id not found")

    if rec.get("status") == "applied":
        return ApplyResponse(change_id=body.change_id, status="already_applied", revert_token=rec.get("revert_token"))

    if db.parse_dt(rec.get("expires_at")) < db.now_utc():
        raise HTTPException(410, "change expired; run dry-run again")

    if rec.get("requires_approval") and not body.admin_override and not body.approval:
        raise HTTPException(403, "Manual approval required")

    provider_name = rec.get("provider")
    provider_instance = _get_provider(provider_name)
    if not provider_instance:
        raise HTTPException(status_code=400, detail=f"Unsupported provider: {provider_name}")

    # For GitHub, prefer the concrete class so tests that monkeypatch
    # GitHubProvider methods take effect even if provider factory is overridden.
    if provider_name == "github":
        try:
            from ..providers.github_provider import GitHubProvider  # type: ignore
            gh_singleton = getattr(provider_factory, "_PROVIDERS", {}).get("github") if hasattr(provider_factory, "_PROVIDERS") else None
            provider_instance = gh_singleton or GitHubProvider()
        except Exception:
            pass

    # Use token override when provided (applies to providers where the actor matters)
    token_for_apply = body.token or rec.get("token")

    with time_apply(provider_name):
        try:
            # For Notion we prefer the helpers exposed on the notion router (tests monkeypatch these)
            if provider_name == "notion":
                try:
                    from ..routers.notion import get_page_last_edited as _get_page_last_edited, patch_page_archive as _patch_page_archive
                except Exception:
                    from ..services.notion_api import get_page_last_edited as _get_page_last_edited, patch_page_archive as _patch_page_archive

                current_last_edited, _ = await _get_page_last_edited(rec["target_id"], token_for_apply)
                if current_last_edited and rec.get("last_edited_time") and current_last_edited != rec["last_edited_time"]:
                    raise HTTPException(409, "page changed since dry-run; run dry-run again")
                _, ms = await _patch_page_archive(rec["target_id"], token_for_apply, archived=True)
            elif provider_name == "github":
                target_id = rec["target_id"]
                token = token_for_apply
                # Resolve metadata to determine object type
                md = await provider_instance.get_metadata(target_id, token)
                if md.get("type") in ("bulk_pr_dry_run", "bulk_pr", "bulk") or ("@" in target_id):
                    # Bulk PR close
                    prs = await provider_instance.list_open_prs(target_id, token)
                    numbers = [int(p.get("number")) for p in prs]
                    await provider_instance.bulk_close_prs(target_id, token, numbers)
                    ms = 0
                    # Save numbers for revert
                    try:
                        summary = rec.get("summary_json") or rec.get("summary")
                        if isinstance(summary, str):
                            summary = json.loads(summary) if summary else {}
                        elif not isinstance(summary, dict):
                            summary = {}
                    except Exception:
                        summary = {}
                    summary["github_bulk_pr_numbers"] = numbers
                    new_rec = dict(rec)
                    new_rec["summary_json"] = summary
                    db.upsert_change(new_rec)
                elif md.get("type") == "repo" or md.get("object") == "repository":
                    # Check if this is DELETE REPOSITORY (permanent) or ARCHIVE (reversible)
                    reason = rec.get("reason", "").lower()
                    is_delete = "delete repository" in reason or "permanent" in reason
                    
                    if is_delete:
                        # DELETE REPOSITORY - IRREVERSIBLE, no conflict check needed
                        await provider_instance.delete_repository(target_id, token)
                        ms = 0
                    else:
                        # ARCHIVE REPOSITORY - reversible, check for conflicts
                        current = await provider_instance.get_metadata(target_id, token)
                        prev = rec.get("last_edited_time")
                        curr = current.get("lastPushedAt") or current.get("lastCommitDate")
                        if prev and curr and prev != curr:
                            raise HTTPException(409, "repo changed since dry-run; run dry-run again")
                        await provider_instance.archive(target_id, token)
                        ms = 0
                else:
                    # branch delete
                    sha = await provider_instance.delete_branch(target_id, token)
                    ms = 0
                    # Persist SHA into summary_json for later revert
                    try:
                        # rec fields summary_json/policy_json may be JSON strings depending on storage
                        summary = rec.get("summary_json") or rec.get("summary")
                        if isinstance(summary, str):
                            summary = json.loads(summary) if summary else {}
                        elif not isinstance(summary, dict):
                            summary = {}
                    except Exception:
                        summary = {}
                    summary["github_restore_sha"] = sha
                    new_rec = dict(rec)
                    new_rec["summary_json"] = summary
                    db.upsert_change(new_rec)
            else:
                result = await provider_instance.archive(rec["target_id"], token_for_apply)
                if provider_name == "slack":
                    # Slack SDK returns dict-like responses with ok/error fields (always HTTP 200)
                    try:
                        ok_flag = getattr(result, 'get', lambda k, d=None: None)("ok", None) if result is not None else None
                        # If result is a slack_sdk.web.slack_response.SlackResponse, it is subscriptable
                        if ok_flag is None and result is not None:
                            try:
                                ok_flag = result["ok"]
                            except Exception:
                                ok_flag = None
                        if ok_flag is False:
                            err_msg = None
                            try:
                                err_msg = result.get("error") if hasattr(result, 'get') else result["error"]
                            except Exception:
                                err_msg = "unknown_error"
                            raise HTTPException(status_code=400, detail=f"SLACK_API_ERROR:{err_msg}")
                    except HTTPException:
                        raise
                    except Exception as e:
                        # Fail safe: surface unexpected structure
                        raise HTTPException(status_code=502, detail=f"apply failed: slack response parse error: {e}")
                ms = 0

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(502, f"apply failed: {e}")

    # Revert token is a plain UUID that maps back to this change
    revert_token = str(uuid.uuid4())
    storage.set_change_status(body.change_id, "applied")
    storage.set_revert_token(body.change_id, revert_token)
    
    expires_dt_obj = db.parse_dt(rec.get("expires_at"))
    ttl_seconds = int(expires_dt_obj.timestamp() - datetime.now(timezone.utc).timestamp())
    token_data = {"kind": "revert", "ref": revert_token, "expires_at": rec.get("expires_at")}
    storage.save_token(revert_token, token_data, ttl_seconds if ttl_seconds > 0 else 3600)

    applied_at_str = db.iso_z(db.now_utc())
    db.insert_audit(body.change_id, "applied", {"applied_at": applied_at_str, "latency_ms": int(ms)})

    telemetry_dict = {"latency_ms": int(ms), "provider_version": "unknown"}
    asyncio.create_task(
        notifier.publish("applied", rec, extras={"revert_token": revert_token, "meta": telemetry_dict}, api_key=api_key)
    )

    return ApplyResponse(change_id=body.change_id, status="applied",
                         revert_token=revert_token, applied_at=applied_at_str, telemetry=telemetry_dict)


@router.get("/approve")
async def approve_get(t: str):
    storage = storage_manager.get_storage()
    token = storage.get_token(t)
    if not token:
        raise HTTPException(404, "token not found")

    if token.get("used"):
        raise HTTPException(410, "token already used")
    if db.parse_dt(token.get("expires_at")) < db.now_utc():
        raise HTTPException(410, "token expired")

    if token["kind"] != "approve":
        raise HTTPException(400, "unexpected token type")

    change_id = token["ref"]
    rec = storage.get_change(change_id)
    if not rec:
        return {"status": "not_found"}

    resp = {
        "change_id": change_id,
        "provider": rec.get("provider"),
        "target_id": rec.get("target_id"),
        "summary": rec.get("summary"),
        "policy": rec.get("policy"),
        "requires_approval": rec.get("requires_approval"),
        "reason": rec.get("reason"),
        "token": t,
        "status": rec.get("status")
    }

    return resp


@router.post("/approve")
async def approve_post(t: str):
    storage = storage_manager.get_storage()
    token = storage.get_token(t)
    if not token:
        raise HTTPException(404, "token not found")

    if token.get("used"):
        raise HTTPException(410, "token already used")
    if db.parse_dt(token.get("expires_at")) < db.now_utc():
        raise HTTPException(410, "token expired")

    if token["kind"] != "approve":
        raise HTTPException(400, "unexpected token type")

    change_id = token["ref"]
    rec = storage.get_change(change_id)
    if not rec:
        raise HTTPException(404, "change not found")

    # Mark approved: clear requires_approval flag
    try:
        storage.set_change_approved(change_id, True)
    except Exception:
        pass
    storage.use_token(t)
    return {"change_id": change_id, "status": "approved"}


@router.post("/revert", response_model=RevertResponse)
async def revert_change(body: RevertRequest, api_key: str = Depends(verify_api_key)):
    storage = storage_manager.get_storage()
    rec = storage.get_change_by_revert_token(body.revert_token)
    if not rec:
        raise HTTPException(status_code=404, detail="revert_token not found")

    if rec.get("status") == "reverted":
        return RevertResponse(revert_token=body.revert_token, status="already_reverted")

    provider_instance = _get_provider(rec["provider"]) 
    if not provider_instance:
        raise HTTPException(status_code=400, detail=f"Unsupported provider: {rec['provider']}")

    # For GitHub, prefer the concrete class for the same reason as in apply
    if rec["provider"] == "github":
        try:
            from ..providers.github_provider import GitHubProvider  # type: ignore
            gh_singleton = getattr(provider_factory, "_PROVIDERS", {}).get("github") if hasattr(provider_factory, "_PROVIDERS") else None
            provider_instance = gh_singleton or GitHubProvider()
        except Exception:
            pass

    # Use token override when provided (e.g., Slack unarchive may require user token)
    token_for_revert = body.token or rec.get("token")

    with time_revert(rec["provider"]):
        try:
            if rec["provider"] == "notion":
                try:
                    from ..routers.notion import patch_page_archive as _patch_page_archive
                except Exception:
                    from ..services.notion_api import patch_page_archive as _patch_page_archive
                _, ms = await _patch_page_archive(rec["target_id"], token_for_revert, archived=False)
            elif rec["provider"] == "github":
                target_id = rec["target_id"]
                if "@" in target_id:
                    # bulk PR reopen
                    try:
                        summary = rec.get("summary_json") or rec.get("summary")
                        if isinstance(summary, str):
                            summary = json.loads(summary) if summary else {}
                    except Exception:
                        summary = {}
                    numbers = (summary or {}).get("github_bulk_pr_numbers") or []
                    # Signature: bulk_reopen_prs(target_repo: str, pr_numbers: list[int], token: Optional[str])
                    await provider_instance.bulk_reopen_prs(target_id, numbers, token_for_revert)
                    ms = 0
                elif "#" in target_id:
                    # branch restore; fetch sha from summary_json
                    try:
                        summary = rec.get("summary_json") or rec.get("summary")
                        if isinstance(summary, str):
                            summary = json.loads(summary) if summary else {}
                    except Exception:
                        summary = {}
                    sha = (summary or {}).get("github_restore_sha")
                    await provider_instance.restore_branch(target_id, token_for_revert, sha)
                    ms = 0
                else:
                    # repo unarchive
                    await provider_instance.unarchive(target_id, token_for_revert)
                    ms = 0
            else:
                await provider_instance.unarchive(rec["target_id"], token_for_revert)
                ms = 0
        except Exception as e:
            raise HTTPException(502, f"revert failed: {e}")

    storage.set_change_status(rec["change_id"], "reverted")
    db.insert_audit(rec["change_id"], "reverted", {"latency_ms": int(ms)})

    telemetry_dict = {"latency_ms": int(ms), "provider_version": "unknown"}
    asyncio.create_task(
        notifier.publish("reverted", rec, extras={"meta": telemetry_dict}, api_key=api_key)
    )

    return RevertResponse(revert_token=body.revert_token, status="reverted", telemetry=telemetry_dict)
