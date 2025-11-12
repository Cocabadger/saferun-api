import os
import json
import uuid
from datetime import datetime, timezone
from ..models.contracts import DryRunArchiveRequest, DryRunArchiveResponse, TargetRef, Summary, DiffUnit
from ..metrics import time_dryrun
from .. import storage as storage_manager
from .. import db_adapter as db
from ..providers import factory as provider_factory
from ..providers.base import Provider
from typing import Dict
from ..notify import notifier
from . import policy_engine
from .risk import compute_risk, human_preview as hp_render

# Providers are resolved via factory so tests can monkeypatch easily.

async def build_dryrun(req: DryRunArchiveRequest, notion_version: str | None = None, api_key: str | None = None) -> DryRunArchiveResponse:
    storage = storage_manager.get_storage()
    provider_instance = provider_factory.get_provider(req.provider)
    # For GitHub, prefer the concrete class instance so tests that monkeypatch
    # GitHubProvider methods take effect even if factory is overridden in conftest.
    if req.provider == "github":
        try:
            from ..providers.github_provider import GitHubProvider  # type: ignore
            # Use the singleton from factory when possible to keep state consistent
            gh = getattr(provider_factory, "_PROVIDERS", {}).get("github") if hasattr(provider_factory, "_PROVIDERS") else None
            provider_instance = gh or GitHubProvider()
        except Exception:
            pass
    if not provider_instance:
        raise ValueError(f"Unsupported provider: {req.provider}")

    with time_dryrun(req.provider):
        try:
            # 1) Fetch metadata and children count from provider
            if req.provider == "notion":
                # Use local wrappers so tests can monkeypatch get_page/get_children_count
                try:
                    pg = await get_page(req.target_id, req.token)
                except NameError:
                    pg = await provider_instance.get_metadata(req.target_id, req.token)

                metadata = pg[0] if isinstance(pg, (tuple, list)) else pg

                try:
                    children_raw = await get_children_count(req.target_id, req.token)
                except NameError:
                    children_raw = await provider_instance.get_children_count(req.target_id, req.token)
            else:
                # Use metadata from request if provided, otherwise fetch from provider
                if req.metadata is not None and req.metadata != {}:
                    metadata = req.metadata
                else:
                    metadata = await provider_instance.get_metadata(req.target_id, req.token)
                children_raw = await provider_instance.get_children_count(req.target_id, req.token)

            # Normalize children/blocks
            blocks = children_raw[0] if isinstance(children_raw, (tuple, list)) else children_raw

            # 1.a) Notion-specific normalization (title, parent_type)
            title = None
            if req.provider == "notion" and isinstance(metadata, dict):
                props = metadata.get("properties", {})
                for v in props.values():
                    if isinstance(v, dict) and v.get("type") == "title":
                        rich = v.get("title") or []
                        if isinstance(rich, list):
                            title = "".join([x.get("plain_text", "") for x in rich]) or None
                        break

                parent = metadata.get("parent", {})
                if parent.get("workspace"):
                    metadata["parent_type"] = "workspace"
                elif parent.get("database_id"):
                    metadata["parent_type"] = "database"
                elif parent.get("page_id"):
                    metadata["parent_type"] = "page"

            # Title fallback for non-Notion providers
            title = title or (metadata.get("name") or metadata.get("title"))

            # Support multiple provider-specific last edited keys
            last_edit = (
                metadata.get("modifiedTime")
                or metadata.get("lastModifiedTime")
                or metadata.get("last_edited_time")
            )

            # Item type normalization per provider
            item_type = metadata.get("mimeType") or metadata.get("filetype") or metadata.get("object")
            if req.provider == "gsheets":
                item_type = "file"
            if req.provider == "slack":
                # Distinguish channel vs file
                if isinstance(metadata, dict) and metadata.get("object") == "channel":
                    item_type = "channel"
                else:
                    item_type = "file"
            if req.provider == "airtable":
                item_type = "bulk_view" if metadata.get("type") == "bulk_view_dry_run" else "record"
            if req.provider == "github":
                if metadata.get("type") in ("bulk_pr_dry_run", "bulk_pr"):
                    item_type = "bulk_pr"
                elif metadata.get("object") == "branch":
                    item_type = "branch"
                else:
                    item_type = "repo"
                
                # Detect operation type from reason or metadata
                if req.reason and "DELETE" in req.reason.upper():
                    metadata["operation_type"] = "delete_repo"
                elif req.reason and "FORCE" in req.reason.upper():
                    metadata["operation_type"] = "force_push"

            # 2) Calculate risk score and other context variables
            linked_count = metadata.get("linkedCount", 0)
            if req.provider == "github":
                last_edit = metadata.get("lastPushedAt") or metadata.get("lastCommitDate") or last_edit
            risk_score, risk_reasons = compute_risk(req.provider, title, blocks, last_edit, linked_count, metadata=metadata)

            edited_age_hours = 1e9
            if last_edit:
                last_edit_dt = datetime.fromisoformat(last_edit.replace("Z", "+00:00"))
                age_delta = datetime.now(timezone.utc) - last_edit_dt
                edited_age_hours = age_delta.total_seconds() / 3600

            # GitHub extra: default branch adds risk
            if req.provider == "github" and item_type == "branch" and metadata.get("isDefault"):
                risk_score += 0.50
                risk_reasons.append("github_default_branch")

            # 3) Load policy
            policy_json_str = os.getenv("DEFAULT_POLICY_JSON")
            loaded_policy = req.policy
            if not loaded_policy:
                loaded_policy = json.loads(policy_json_str) if policy_json_str else policy_engine.DEFAULT_POLICY
            else:
                # Back-compat: accept {max_risk: x}
                if isinstance(loaded_policy, dict) and "rules" not in loaded_policy:
                    if "max_risk" in loaded_policy:
                        loaded_policy = {
                            "version": "1.0",
                            "rules": [
                                {"type": "max_risk", "value": loaded_policy.get("max_risk"), "action": "require_approval"}
                            ],
                            "mode": "ANY",
                        }

            # 4) Evaluate policy
            ctx = {
                "risk_score": risk_score,
                "title": title,
                "blocks_count": blocks,
                "parent_type": metadata.get("parent_type"),
                "edited_age_hours": edited_age_hours,
            }
            need_approval, policy_reasons = policy_engine.evaluate(metadata, ctx, loaded_policy)
            all_reasons = risk_reasons + [f"policy:{r}" for r in policy_reasons]

            # 4.5) UNIFIED APPROVAL LOGIC (MVP): ALL operations require approval, 24h window
            # Philosophy: SafeRun is PROTECTION system. No auto-execute.
            
            # ALL OPERATIONS:
            need_approval = True              # ALWAYS require approval
            revert_window_hours = 24          # ALWAYS 24 hours for everything
            
            # Determine if operation is reversible (for revert button after execution)
            is_reversible = False
            if req.provider == "github":
                object_type = metadata.get("object")
                operation_type = metadata.get("operation_type", "")
                
                # Reversible operations: can be undone
                reversible_operations = ["repository", "branch"]  # archive, branch-delete
                
                # Irreversible operations: cannot be undone
                irreversible_operations = ["merge", "force_push", "delete_repo"]
                
                if object_type in reversible_operations:
                    is_reversible = True
                    all_reasons.append("github:reversible_operation")
                elif operation_type in irreversible_operations:
                    is_reversible = False
                    all_reasons.append("github:irreversible_operation")
                
                # Add main branch protection reason if applicable
                default_branch = metadata.get("default_branch", "main")
                is_main_branch = False
                
                # Check target_id for branch specification (repo#branch format)
                if "#" in req.target_id and "→" not in req.target_id:  # Not a merge
                    _, branch_name = req.target_id.split("#", 1)
                    is_main_branch = (branch_name == default_branch)
                elif object_type == "repository":
                    # Whole repo operation affects main branch
                    is_main_branch = True
                elif object_type == "branch":
                    # Branch operation - check if it's the default branch
                    is_main_branch = (metadata.get("name") == default_branch or metadata.get("isDefault", False))
                
                if is_main_branch:
                    all_reasons.append("github:main_branch_protection")

            # 5) Persist the change request
            change_id = new_change_id()
            
            expires_dt_obj = expiry(120)  # 2 hours timeout for polling (kept for backwards compatibility)
            created_at_str = db.iso_z(expiry(0))
            expires_at_str = db.iso_z(expires_dt_obj)
            ttl_seconds = int(expires_dt_obj.timestamp() - datetime.now(timezone.utc).timestamp())

            # Build summary_json for the change record
            summary_json = {
                "operation_type": metadata.get("operation_type", "archive"),
                "provider": req.provider,
                "target_id": req.target_id,
                "title": title,
                "item_type": item_type,
                "risk_score": risk_score,
                "reasons": all_reasons,
                "blocks": blocks,
                "linked_count": linked_count,
                "last_edit": last_edit,
                "reason": req.reason or "",
            }
            
            # Add GitHub-specific fields
            if req.provider == "github":
                summary_json["repo_name"] = metadata.get("full_name", "")
                summary_json["branch_name"] = metadata.get("name", "")
                summary_json["is_default_branch"] = metadata.get("isDefault", False)
            
            change_data = {
                "change_id": change_id,
                "api_key": api_key,  # Store API key for user isolation
                "provider": req.provider,
                "target_id": req.target_id,
                "title": title,
                "last_edited_time": last_edit,
                "risk_score": risk_score,
                "policy": loaded_policy,
                "expires_at": expires_at_str,
                "token": req.token,
                "status": "pending",
                "requires_approval": need_approval,
                "created_at": created_at_str,
                "webhook_url": req.webhook_url,  # Store webhook URL
                "metadata": metadata,  # Store metadata for revert logic (object type, etc.)
                "summary_json": json.dumps(summary_json),  # Add summary_json field
            }
            
            # Add revert_window for non-approval GitHub archives
            if revert_window_hours is not None:
                revert_expires = expiry(0)  # Current time
                from datetime import timedelta
                revert_expires = datetime.now(timezone.utc) + timedelta(hours=revert_window_hours)
                change_data["revert_window"] = revert_window_hours
                change_data["revert_expires_at"] = db.iso_z(revert_expires)
            
            storage.save_change(change_id, change_data, ttl_seconds)
            
            # 5.1) Create one-time approval token AFTER saving change (FK constraint requirement)
            approval_token = db.create_approval_token(change_id)

            # 6) If no approval required but has revert_window - execute immediately and notify with revert option
            # 6) ALL operations require approval in MVP - NO auto-execute
            # (Old auto-execute logic removed - everything goes through approval flow)
            
            # 7) Approval URL and notification for approval-required changes
            approve_url = None
            if need_approval:
                base = os.environ.get("APP_BASE_URL", "http://localhost:8500")
                # Include approval token in URL (Phase 1.4 fix: auth for Landing page)
                approve_url = f"{base}/approvals/{change_id}?token={approval_token}"

                # publish notification (use saferun namespace import)
                import asyncio
                from ..notify import notifier
                change_record = storage.get_change(change_id)
                if change_record:
                    asyncio.create_task(
                        notifier.publish("dry_run", change_record, extras={"approve_url": approve_url, "metadata": metadata, "meta": {"latency_ms": 0, "provider_version": "unknown"}}, api_key=api_key)
                    )

            telemetry_dict = {"latency_ms": 0, "provider_version": "unknown"}

            # 7) Bulk-specific handling (Airtable/GitHub)
            if metadata.get("type") in ("bulk_view_dry_run", "bulk_pr_dry_run", "bulk_pr"):
                records = metadata.get("records_affected")
                sample_list = []
                bulk_risk = 0.0
                if req.provider == "github":
                    try:
                        prs = await provider_instance.list_open_prs(req.target_id, req.token)
                    except Exception:
                        prs = []
                    sample_list = [f"#{p.get('number')} \"{p.get('title')}\"" for p in prs[:3]]
                    titles = " ".join([p.get("title", "") for p in prs])
                    bulk_risk += 0.30
                    if (records or 0) > 20:
                        bulk_risk += 0.30
                    if any(k in titles.lower() for k in ["hotfix", "release", "prod"]):
                        bulk_risk += 0.20
                    # recent <24h
                    now = datetime.now(timezone.utc)
                    for p in prs:
                        ts = p.get("updatedAt") or p.get("lastCommitAt")
                        if ts:
                            try:
                                dtv = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                                if (now - dtv).total_seconds() <= 24 * 3600:
                                    bulk_risk += 0.10
                                    break
                            except Exception:
                                pass

                records_count = records if isinstance(records, int) else blocks
                if req.provider == "github":
                    change_data["requires_approval"] = True
                    storage.save_change(change_id, change_data, ttl_seconds)

                hp_text = (
                    f"Bulk dry-run for Airtable view '{metadata.get('view_name')}'. "
                    if req.provider == "airtable"
                    else (
                        f"⚠️ BULK PREVIEW (GitHub PRs)\n"
                        f"Repo: {metadata.get('owner')}/{metadata.get('repo')}\n"
                        f"Affected PRs: {records_count}\n"
                        f"Sample: {', '.join(sample_list)}\n"
                    )
                )

                return DryRunArchiveResponse(
                    change_id=change_id,
                    target=TargetRef(provider=req.provider, target_id=req.target_id, type=item_type),
                    summary=Summary(
                        title=f"Bulk Dry-Run for {metadata.get('view_name')}",
                        blocks_count=records_count,
                        blocks_count_approx=True,
                        last_edited_time=None,
                    ),
                    diff=[DiffUnit(op="bulk_preview", impact={"records_affected": records_count, "sample": sample_list})],
                    risk_score=bulk_risk,
                    reasons=["bulk_dry_run_only"],
                    requires_approval=True if req.provider == "github" else False,
                    human_preview=hp_text + "Bulk apply not supported yet.",
                    approve_url=None,
                    revert_url=None,
                    telemetry=telemetry_dict,
                    expires_at=expires_dt_obj,
                    apply=False,
                    note="bulk apply not supported yet",
                    records_affected=records_count,
                )

            # 8) Write audit event and build final response for non-bulk
            db.insert_audit(change_id, "dry_run", {"latency_ms": 0, "summary": {"title": title, "blocks": blocks}})
            hp = hp_render(req.provider, title, item_type, blocks, last_edit, risk_score, all_reasons, metadata.get("linkedCount", 0))

            op = "archive"
            if req.provider == "github" and item_type == "branch":
                op = "delete_branch"

            # Prepare revert_url if revert window is available
            revert_response_url = None
            revert_window_response = None
            if revert_window_hours is not None:
                # Use API_BASE_URL for API endpoints (defaults to Railway public domain or localhost)
                api_base = os.environ.get("API_BASE_URL") or os.environ.get("RAILWAY_PUBLIC_DOMAIN", "http://localhost:8500")
                if api_base and not api_base.startswith("http"):
                    api_base = f"https://{api_base}"
                revert_response_url = f"{api_base}/webhooks/github/revert/{change_id}"
                revert_window_response = revert_window_hours

            # Save change to database (for approval flow)
            # NOTE: For auto-execute flow, change_data is already saved earlier (line 250, 268)
            # This handles the approval flow where we need to persist the change for later execution
            if need_approval:
                storage.save_change(change_id, change_data, ttl_seconds)

            return DryRunArchiveResponse(
                change_id=change_id,
                target=TargetRef(provider=req.provider, target_id=req.target_id, type=item_type),
                summary=Summary(
                    title=title,
                    parent_type=metadata.get("parent_type"),
                    blocks_count=blocks,
                    blocks_count_approx=True,
                    last_edited_time=last_edit,
                ),
                diff=[DiffUnit(op=op, impact={"pages_affected": 1})],
                risk_score=risk_score,
                reasons=all_reasons,
                requires_approval=need_approval,
                human_preview=hp,
                approve_url=approve_url,
                revert_url=revert_response_url,
                revert_window_hours=revert_window_response,
                telemetry=telemetry_dict,
                expires_at=expires_dt_obj,
            )
        except Exception as e:
            # Surface exception for tests/debugging
            raise


# Compatibility wrappers used by tests to monkeypatch Notion helpers via import path
async def get_page(page_id: str, token: str):
    from .notion_api import get_page
    return await get_page(page_id, token)


async def get_children_count(page_id: str, token: str):
    from .notion_api import get_children_count
    return await get_children_count(page_id, token)


# Utility functions
def new_change_id():
    """Generate a new change ID."""
    return str(uuid.uuid4())


def expiry(minutes: int = 30):
    """Generate expiry datetime."""
    from datetime import timedelta
    return datetime.now(timezone.utc) + timedelta(minutes=minutes)


def human_preview(provider: str, title: str, item_type: str, blocks: int, last_edit: str, risk_score: float, reasons: list, linked_count: int = 0) -> str:
    """Generate human-readable preview."""
    return f"Archive {provider} {item_type}: {title} ({blocks} blocks, risk: {risk_score:.2f})"