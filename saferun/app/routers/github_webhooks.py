"""GitHub App webhook endpoints"""
from fastapi import APIRouter, Request, HTTPException, Header, Depends, Query
import json
import uuid
from typing import Optional
from datetime import datetime, timezone, timedelta

from .. import db_adapter as db
from .. import storage as storage_manager
from ..routers.auth import verify_api_key
from ..routers.auth_helpers import verify_change_ownership
from ..services.github import (
    verify_webhook_signature,
    calculate_github_risk_score,
    create_revert_action,
    revert_force_push,
    restore_deleted_branch,
    create_revert_commit,
    get_deleted_branch_sha
)
from ..notify import notifier  # Use OAuth-based notifier instead of legacy webhooks

router = APIRouter(prefix="/webhooks/github", tags=["github_webhooks"])


def iso_z(dt: datetime) -> str:
    """Convert datetime to ISO format with Z suffix"""
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@router.post("/install")
async def github_app_installation(
    request: Request,
    x_hub_signature_256: Optional[str] = Header(None)
):
    """
    Handle GitHub App installation/uninstallation events
    
    Events:
    - installation.created: App installed on account
    - installation.deleted: App uninstalled
    - installation_repositories.added/removed: Repos added/removed
    """
    # Verify webhook signature
    body = await request.body()
    
    if not verify_webhook_signature(body, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="Invalid signature")
    
    payload = await request.json()
    action = payload.get("action")
    installation = payload.get("installation", {})
    installation_id = installation.get("id")
    account = installation.get("account", {})
    account_login = account.get("login")
    
    if action == "created":
        # New installation - store in DB with repositories from payload
        # FIX: GitHub sends repositories list in installation.created event
        repos = payload.get("repositories", [])
        repo_names = [r.get("full_name") for r in repos]
        
        db.exec(
            "INSERT INTO github_installations(installation_id, account_login, installed_at, repositories_json) VALUES(%s,%s,%s,%s) ON CONFLICT (installation_id) DO UPDATE SET repositories_json = EXCLUDED.repositories_json",
            (installation_id, account_login, iso_z(datetime.now(timezone.utc)), json.dumps(repo_names))
        )
        
        print(f"✅ GitHub App installed: installation_id={installation_id}, account={account_login}, repos={repo_names}")
        
        return {
            "status": "installation_created",
            "installation_id": installation_id,
            "account": account_login,
            "message": "Please link this installation_id to your SafeRun account via API settings"
        }
    
    elif action == "deleted":
        # Uninstallation
        db.exec("DELETE FROM github_installations WHERE installation_id=%s", (installation_id,))
        print(f"❌ GitHub App uninstalled: installation_id={installation_id}, account={account_login}")
        
        return {
            "status": "installation_deleted",
            "installation_id": installation_id
        }
    
    elif action in ["added", "removed"]:
        # Repository access changed
        repositories = payload.get("repositories_added" if action == "added" else "repositories_removed", [])
        repo_names = [r.get("full_name") for r in repositories]
        
        # Update repositories_json
        if action == "added":
            current = db.fetchone("SELECT repositories_json FROM github_installations WHERE installation_id=%s", (installation_id,))
            if current:
                current_repos = json.loads(current.get("repositories_json", "[]"))
                updated_repos = list(set(current_repos + repo_names))
                db.exec(
                    "UPDATE github_installations SET repositories_json=%s WHERE installation_id=%s",
                    (json.dumps(updated_repos), installation_id)
                )
        
        print(f"🔄 Repositories {action}: {repo_names} for installation {installation_id}")
        
        return {
            "status": f"repositories_{action}",
            "repositories": repo_names
        }
    
    return {"status": "ok"}


@router.post("/event")
async def github_webhook_event(
    request: Request,
    x_hub_signature_256: Optional[str] = Header(None),
    x_github_event: Optional[str] = Header(None)
):
    """
    Handle GitHub webhook events (push, delete, pull_request, etc)
    
    This is Level 3 Protection - intercepts ALL GitHub operations
    regardless of how they were initiated (SDK, CLI, or direct API)
    """
    # Verify webhook signature
    body = await request.body()
    
    if not verify_webhook_signature(body, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="Invalid signature")
    
    payload = await request.json()
    event_type = x_github_event
    
    # Handle installation events (created, deleted, repositories_added/removed)
    if event_type == "installation" or event_type == "installation_repositories":
        return await github_app_installation(request, x_hub_signature_256)
    
    # Extract repository and user info
    repository = payload.get("repository", {})
    repo_full_name = repository.get("full_name", "unknown/unknown")
    sender = payload.get("sender", {})
    sender_login = sender.get("login", "unknown")
    
    # FILTER OUT: Events from SafeRun bot itself (revert operations)
    if sender_login in ["saferun-ai[bot]", "SafeRun-AI[bot]"]:
        print(f"⏭️  Ignoring event from SafeRun bot (revert operation): {repo_full_name}")
        return {"status": "ignored", "reason": "saferun_bot_operation"}
    
    # FILTER OUT: Push events with zero commits (GitHub sends these on branch delete - ignore them!)
    # BUT: Save the SHA for branch creation events so we can restore the branch later
    if event_type == "push":
        commits = payload.get("commits", [])
        deleted = payload.get("deleted", False)
        if not commits and not deleted:
            # This is a branch CREATION event (push with no commits) - save SHA for future revert!
            branch_name = payload.get("ref", "").replace("refs/heads/", "")
            head_sha = payload.get("after")
            if branch_name and head_sha and head_sha != "0000000000000000000000000000000000000000":
                # Store a lightweight record just to capture the SHA
                branch_record_id = str(uuid.uuid4())
                db.exec(
                    """INSERT INTO changes (change_id, target_id, provider, title, status, risk_score, 
                       expires_at, created_at, summary_json, branch_head_sha)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (change_id) DO NOTHING""",
                    (branch_record_id, repo_full_name, "github", 
                     f"Branch Created: {branch_name}", "executed", 0.0,
                     iso_z(datetime.now(timezone.utc) + timedelta(hours=24)),
                     iso_z(datetime.now(timezone.utc)),
                     json.dumps({"operation_type": "github_branch_create", "branch_name": branch_name, "source": "github_webhook"}),
                     head_sha)
                )
                print(f"📌 Saved SHA {head_sha[:8]} for new branch '{branch_name}' in {repo_full_name}")
            print(f"⏭️  Ignoring empty push event (branch creation): {repo_full_name}")
            return {"status": "ignored", "reason": "branch_creation_event", "sha_saved": True}
        elif deleted:
            print(f"⏭️  Ignoring empty push event (branch delete artifact): {repo_full_name}")
            return {"status": "ignored", "reason": "empty_push_event"}

    # Calculate risk score
    risk_score, reasons = calculate_github_risk_score(event_type, payload)
    
    # Create action type
    action_type = f"github_{event_type}"
    if "forced" in payload and payload["forced"]:
        action_type = "github_force_push"
    elif event_type == "delete":
        action_type = f"github_delete_{payload.get('ref_type', 'unknown')}"
    elif event_type == "pull_request" and payload.get("action") == "closed" and payload.get("pull_request", {}).get("merged"):
        action_type = "github_merge"
    
    # Check if this event was initiated via API (to prevent duplicate notifications)
    # Look for recent pending/executed operations with same repo/branch in last 5 minutes
    repo_full_name = payload.get("repository", {}).get("full_name", "")
    ref_name = payload.get("ref", "").replace("refs/heads/", "") or payload.get("pull_request", {}).get("base", {}).get("ref", "")
    
    if repo_full_name and action_type in ["github_merge", "github_force_push"]:
        # Check for recent CLI/API operations to avoid duplicate notifications
        # Use naive datetime to match PostgreSQL timestamp without time zone
        check_time = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=5)
        
        # Map webhook action_type to operation_type stored in summary_json
        if action_type == "github_merge":
            operation_type_pattern = "merge"
        elif action_type == "github_force_push":
            operation_type_pattern = "force_push"
        else:
            operation_type_pattern = action_type
        
        # Construct target pattern to match both formats:
        # CLI: "Cocabadger/test-sf-v01#main"
        # Webhook: "Cocabadger/test-sf-v01"
        target_pattern = f"%{repo_full_name}%"
        
        # Check for PENDING operations (skip webhook to avoid duplicate approval requests)
        recent_pending_op = db.fetchone(
            """SELECT change_id, status FROM changes 
               WHERE target_id LIKE %s 
               AND summary_json::text LIKE %s
               AND summary_json::text LIKE %s
               AND created_at > %s
               AND status = 'pending'
               ORDER BY created_at DESC
               LIMIT 1""",
            (target_pattern, '%"operation_type"%', f'%"{operation_type_pattern}"%', check_time)
        )
        
        if recent_pending_op:
            # Skip - user already has approval request from CLI
            print(f"⏭️  Skipping webhook notification - Pending operation detected: {recent_pending_op['change_id']}")
            return {"status": "skipped", "reason": "pending_operation", "change_id": recent_pending_op['change_id']}
        
        # Check for EXECUTED/APPROVED operations (send completion notification)
        recent_executed_op = db.fetchone(
            """SELECT change_id, status, summary_json FROM changes 
               WHERE target_id LIKE %s 
               AND summary_json::text LIKE %s
               AND summary_json::text LIKE %s
               AND created_at > %s
               AND status IN ('approved', 'executed')
               ORDER BY created_at DESC
               LIMIT 1""",
            (target_pattern, '%"operation_type"%', f'%"{operation_type_pattern}"%', check_time)
        )
        
        if recent_executed_op:
            # Send completion notification instead of new approval request
            print(f"✅ Sending completion notification for executed operation: {recent_executed_op['change_id']}")
            
            # Get api_key from the executed operation (CLI operation has user's api_key)
            executed_change = db.fetchone(
                "SELECT * FROM changes WHERE change_id = %s",
                (recent_executed_op['change_id'],)
            )
            
            user_api_key = executed_change.get("api_key") if executed_change else None
            
            # UPDATE CLI record with revert data from webhook payload
            # CLI records don't have revert_action or before_sha - webhook provides these
            revert_action = create_revert_action(event_type, payload)
            if revert_action and executed_change:
                try:
                    existing_summary = json.loads(executed_change.get("summary_json", "{}")) if executed_change.get("summary_json") else {}
                    
                    # Add revert_action and update status to executed
                    existing_summary["revert_action"] = revert_action
                    
                    # Add before_sha to payload for fallback in revert_change()
                    if "payload" not in existing_summary:
                        existing_summary["payload"] = {}
                    existing_summary["payload"]["before"] = payload.get("before")
                    existing_summary["payload"]["after"] = payload.get("after")
                    
                    # CRITICAL: Save installation_id for GitHub App token in revert
                    webhook_installation_id = payload.get("installation", {}).get("id")
                    if webhook_installation_id:
                        existing_summary["installation_id"] = webhook_installation_id
                        print(f"✅ Saved installation_id={webhook_installation_id} from webhook")
                    
                    # Determine object_type from revert_action
                    if revert_action.get("type") == "force_push_revert":
                        existing_summary["metadata"] = existing_summary.get("metadata", {})
                        existing_summary["metadata"]["object_type"] = "force_push"
                    
                    # Update the record with revert data and status using db helper functions
                    db.update_summary_json(recent_executed_op['change_id'], existing_summary)
                    db.set_change_status(recent_executed_op['change_id'], 'executed')
                    print(f"✅ Updated CLI record with revert_action: {revert_action.get('type')}, before_sha: {payload.get('before')}")
                    
                    # Re-fetch updated change for notification
                    executed_change = db.fetchone(
                        "SELECT * FROM changes WHERE change_id = %s",
                        (recent_executed_op['change_id'],)
                    )
                except Exception as e:
                    print(f"⚠️ Error updating CLI record with revert data: {e}")
                    import traceback
                    traceback.print_exc()
            
            if user_api_key:
                try:
                    # Send via OAuth-based notifier (uses slack_installations table)
                    await notifier.publish(
                        event="executed_with_revert",
                        change=executed_change,
                        api_key=user_api_key
                    )
                    print(f"✅ Completion notification sent for {recent_executed_op['change_id']}")
                except Exception as e:
                    print(f"❌ Error sending completion notification: {e}")
                    import traceback
                    traceback.print_exc()
            
            return {"status": "completion_notification_sent", "api_change_id": recent_executed_op['change_id']}
    
    # Generate unique change ID
    change_id = str(uuid.uuid4())
    
    # Find user by installation_id
    installation_id = payload.get("installation", {}).get("id")
    user_email = None
    user_api_key = None
    
    if installation_id:
        # Try to find user by installation_id
        install_row = db.fetchone(
            "SELECT api_key FROM github_installations WHERE installation_id=%s",
            (installation_id,)
        )
        if install_row and install_row.get("api_key"):
            user_api_key = install_row["api_key"]
            # Get user email
            user_row = db.fetchone("SELECT email FROM api_keys WHERE api_key=%s", (user_api_key,))
            if user_row:
                user_email = user_row.get("email")
    
    if not user_email:
        user_email = sender_login
        print(f"⚠️ No SafeRun user found for GitHub event: {repo_full_name} (installation_id={installation_id})")
    
    # Extract branch SHA for push events
    branch_head_sha = None
    if event_type == "push":
        branch_head_sha = payload.get("after")  # SHA of the new HEAD
    
    # Create revert action and populate SHA for delete events from DB
    revert_action = create_revert_action(event_type, payload)
    
    # For delete events, get SHA from last push to this branch
    if event_type == "delete" and payload.get("ref_type") == "branch" and revert_action:
        branch_name = payload.get("ref", "")
        # Query last push event for this branch (filter by branch_name in summary_json)
        last_push = db.fetchone(
            """SELECT branch_head_sha FROM changes 
               WHERE target_id = %s 
               AND summary_json::text LIKE %s
               AND branch_head_sha IS NOT NULL
               ORDER BY created_at DESC LIMIT 1""",
            (repo_full_name, f'%"branch_name": "{branch_name}"%')
        )
        if last_push and last_push.get("branch_head_sha"):
            revert_action["sha"] = last_push["branch_head_sha"]
            revert_action["before_sha"] = last_push["branch_head_sha"]  # Alias for frontend compatibility
            print(f"✅ Retrieved SHA for branch '{branch_name}' delete from DB: {revert_action['sha']}")
        else:
            # Fallback: try to get SHA from GitHub Events API
            print(f"⚠️ No SHA found in DB for deleted branch '{branch_name}', trying GitHub API...")
            if installation_id:
                owner = payload.get("repository", {}).get("owner", {}).get("login")
                repo_name = payload.get("repository", {}).get("name")
                if owner and repo_name:
                    api_sha = get_deleted_branch_sha(owner, repo_name, branch_name, installation_id)
                    if api_sha:
                        revert_action["sha"] = api_sha
                        revert_action["before_sha"] = api_sha  # Alias for frontend compatibility
                        print(f"✅ Retrieved SHA for branch '{branch_name}' delete from GitHub API: {api_sha}")
                    else:
                        print(f"❌ Could not retrieve SHA for deleted branch '{branch_name}' from any source")
    
    # Normalize risk_score to 0-1 range for storage (displayed as 0-10 in UI)
    normalized_risk_score = min(risk_score / 10.0, 1.0)
    
    # Determine object_type from revert_action for revert functionality
    object_type = None
    if revert_action:
        revert_type = revert_action.get("type", "")
        if revert_type == "force_push_revert":
            object_type = "force_push"
        elif revert_type == "branch_restore":
            object_type = "branch"
        elif revert_type == "repository_unarchive":
            object_type = "repository"
        elif revert_type == "merge_revert":
            object_type = "merge"
    
    # Create change record
    change = {
        "change_id": change_id,
        "target_id": repo_full_name,
        "provider": "github",
        "title": f"{action_type.replace('github_', '').replace('_', ' ').title()} - {repo_full_name}",
        "status": "executed",  # Webhook events are already executed on GitHub
        "risk_score": normalized_risk_score,  # Store normalized (0-1)
        "expires_at": iso_z(datetime.now(timezone.utc) + timedelta(hours=2)),  # 2 hours for consistency with CLI
        "created_at": iso_z(datetime.now(timezone.utc)),
        "last_edited_time": iso_z(datetime.now(timezone.utc)),
        "revert_window": 24,  # 24 hours revert window
        "revert_expires_at": datetime.now(timezone.utc) + timedelta(hours=24),  # Revert available for 24h
        "policy_json": {"risk_reasons": reasons},
        "summary_json": {
            "operation_type": action_type,
            "repo_name": repo_full_name,
            "branch_name": payload.get("ref", "").replace("refs/heads/", "") if event_type == "push" else payload.get("ref", ""),
            "source": "github_webhook",
            "event_type": event_type,
            "sender": sender_login,
            "installation_id": installation_id,  # Save for GitHub App token generation
            "payload": payload,
            "revert_action": revert_action  # Now contains SHA for delete events!
        },
        "metadata": {"object": object_type} if object_type else {},  # Object type for revert
        "api_key": user_api_key,  # Link to user for multi-user isolation
        "branch_head_sha": branch_head_sha  # Save SHA for future revert
    }
    
    db.upsert_change(change)
    
    # Generate approval token for revert operations (used in Slack button)
    approval_token = None
    if revert_action:  # Only generate token if revert is possible
        approval_token = db.create_approval_token(change_id)
        # Update change record with the approval token
        db.exec("UPDATE changes SET revert_token = %s WHERE change_id = %s", (approval_token, change_id))
    
    # Insert audit log
    db.insert_audit(change_id, "github_webhook_received", {
        "event_type": event_type,
        "risk_score": risk_score,
        "sender": sender_login,
        "installation_id": installation_id
    })
    
    # Send Slack notification via OAuth-based notifier (uses slack_installations table)
    if user_api_key:
        try:
            # REACTIVE GOVERNANCE: Webhooks are ALWAYS post-factum
            # The operation has ALREADY HAPPENED - we can only offer REVERT, not APPROVAL
            # Use executed_high_risk (red alert + Revert) or executed_with_revert (green + Revert)
            if risk_score >= 7.0:
                notify_event = "executed_high_risk"  # Red alert with Revert button
            else:
                notify_event = "executed_with_revert"  # Green notification with Revert button
            
            await notifier.publish(
                event=notify_event,
                change=change,
                extras={
                    "approve_url": f"/api/github/approve/{change_id}?token={approval_token}" if approval_token else None,
                    "meta": {
                        "source": "github_webhook",
                        "event_type": event_type,
                        "sender": sender_login
                    }
                },
                api_key=user_api_key
            )
            print(f"✅ Slack notification sent for change {change_id}")
        except Exception as e:
            print(f"❌ Error sending Slack notification: {e}")
            import traceback
            traceback.print_exc()
    
    # Log high-risk operations
    if risk_score >= 7.0:
        print(f"🚨 HIGH RISK GitHub event detected: {action_type} on {repo_full_name} by {sender_login}")
        print(f"   Risk Score: {risk_score}, Reasons: {', '.join(reasons)}")
        print(f"   Change ID: {change_id} - awaiting approval")
    
    return {
        "status": "event_received",
        "change_id": change_id,
        "risk_score": risk_score,
        "requires_approval": risk_score >= 7.0,
        "message": "Event logged. Check SafeRun dashboard for approval." if risk_score >= 7.0 else "Event logged."
    }


@router.post("/revert/{change_id}")
async def revert_github_action(
    change_id: str,
    request: Request,
    token: Optional[str] = Query(None),  # NEW: Approval token support
    api_key: Optional[str] = Header(None, alias="X-API-Key")  # Now optional for backward compat
):
    """
    Revert a GitHub action (force push, delete, merge)
    
    Authentication (Dual Auth):
    - Method 1: Approval token (?token=tok_xxx) - Preferred, no API key needed
    - Method 2: API key (X-API-Key header) - Backward compatibility
    
    GitHub token retrieval:
    - With approval token: Retrieved from encrypted storage automatically
    - With API key: Must provide github_token in JSON body (old method)
    """
    storage = storage_manager.get_storage()
    github_token = None
    
    # DUAL AUTHENTICATION LOGIC (like approvals.py)
    if token:
        # Method 1: Approval token authentication
        token_info = db.get_approval_token_info(token)
        
        if not token_info:
            raise HTTPException(status_code=401, detail="Invalid or expired approval token")
        
        if token_info.get("used"):
            raise HTTPException(status_code=401, detail="Approval token already used")
        
        if token_info.get("change_id") != change_id:
            raise HTTPException(status_code=403, detail="Token does not match change ID")
        
        # Check token expiration
        expires_at = token_info.get("expires_at")
        if expires_at:
            from datetime import datetime, timezone
            if isinstance(expires_at, str):
                expires_at = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
            if datetime.now(timezone.utc) > expires_at:
                raise HTTPException(status_code=401, detail="Approval token expired")
        
        # Get change record (no ownership check - token grants access)
        change = storage.get_change(change_id)
        if not change:
            raise HTTPException(status_code=404, detail="Change not found")
        
        # Retrieve encrypted GitHub token from change record
        summary_json = change.get("summary_json") or "{}"
        try:
            summary = json.loads(summary_json) if isinstance(summary_json, str) else summary_json
        except (json.JSONDecodeError, TypeError):
            summary = {}
        
        # Check if this is a webhook event (has installation_id)
        installation_id = summary.get("installation_id")
        
        if installation_id:
            # Webhook event: Use GitHub App Installation Token
            from ..services.github import get_github_app_installation_token
            github_token = get_github_app_installation_token(installation_id)
            if not github_token:
                raise HTTPException(status_code=500, detail="Failed to get GitHub App token")
        else:
            # No installation_id: Try fallback methods
            # 1. Try finding installation_id by repository name (for old webhook events)
            repo_name = summary.get("repo_name")
            if repo_name and summary.get("source") == "github_webhook":
                install_record = db.fetchone(
                    "SELECT installation_id FROM github_installations WHERE repositories_json::text LIKE %s LIMIT 1",
                    (f"%{repo_name}%",)
                )
                if install_record:
                    installation_id = install_record.get("installation_id")
                    from ..services.github import get_github_app_installation_token
                    github_token = get_github_app_installation_token(installation_id)
                    if not github_token:
                        raise HTTPException(status_code=500, detail="Failed to get GitHub App token")
                else:
                    raise HTTPException(status_code=400, detail="GitHub App not installed for this repository")
            else:
                # 2. CLI/API event: Use encrypted user token
                encrypted_github_token = summary.get("github_token")
                if not encrypted_github_token:
                    raise HTTPException(status_code=400, detail="GitHub token not found in change record")
                
                # Decrypt GitHub token
                github_token = db.decrypt_token(encrypted_github_token)
        
        # Mark approval token as used (one-time use)
        if token:
            if not db.verify_approval_token(change_id, token):
                raise HTTPException(status_code=403, detail="Token validation failed")
        
    elif api_key:
        # Method 2: API key authentication (backward compatibility)
        change = verify_change_ownership(change_id, api_key, storage)
        
        # Parse JSON body for github_token (old method)
        try:
            body = await request.json()
            github_token = body.get("github_token")
            if not github_token:
                raise HTTPException(status_code=400, detail="github_token required in request body when using API key auth")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid JSON body: {str(e)}")
    else:
        # No authentication provided
        raise HTTPException(status_code=401, detail="Authentication required: provide either ?token=xxx or X-API-Key header")
    
    # ✅ BUG #16 FIX: Check if operation can be reverted
    current_status = change.get("status", "pending")
    
    # Allow revert for executed/applied operations AND pending_review webhook events
    # (webhook events are "pending_review" awaiting user decision, but already executed on GitHub)
    summary_json_check = change.get("summary_json") or "{}"
    try:
        summary_check = json.loads(summary_json_check) if isinstance(summary_json_check, str) else summary_json_check
    except (json.JSONDecodeError, TypeError):
        summary_check = {}
    
    is_webhook_event = summary_check.get("source") == "github_webhook"
    
    if current_status not in {"executed", "applied"}:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot revert: operation is {current_status}. Only executed operations can be reverted."
        )
    
    # Check if already reverted
    if current_status == "reverted":
        raise HTTPException(
            status_code=409,
            detail="Operation already reverted"
        )
    
    # Parse summary_json if not already done (in API key auth path)
    if not github_token or 'summary' not in locals():
        summary_json = change.get("summary_json") or "{}"
        try:
            summary = json.loads(summary_json) if isinstance(summary_json, str) else summary_json
        except (json.JSONDecodeError, TypeError):
            summary = {}
        
        if not isinstance(summary, dict):
            summary = {}
    
    revert_action = summary.get("revert_action")
    
    if not revert_action:
        raise HTTPException(status_code=400, detail="No revert action available for this event")
    
    success = False
    
    if revert_action["type"] == "force_push_revert":
        success = await revert_force_push(
            owner=revert_action["owner"],
            repo=revert_action["repo"],
            branch=revert_action["branch"],
            before_sha=revert_action["before_sha"],
            github_token=github_token
        )
    
    elif revert_action["type"] == "branch_restore":
        if not revert_action.get("sha"):
            raise HTTPException(status_code=400, detail="Cannot restore: SHA not available")
        
        success = await restore_deleted_branch(
            owner=revert_action["owner"],
            repo=revert_action["repo"],
            branch=revert_action["branch"],
            sha=revert_action["sha"],
            github_token=github_token
        )
    
    elif revert_action["type"] == "merge_revert":
        success = await create_revert_commit(
            owner=revert_action["owner"],
            repo=revert_action["repo"],
            branch=revert_action["branch"],
            commit_sha=revert_action["merge_commit_sha"],
            github_token=github_token
        )
    
    elif revert_action["type"] == "repository_unarchive":
        from saferun.app.providers.github_provider import GitHubProvider
        await GitHubProvider.unarchive(
            target_id=f"{revert_action['owner']}/{revert_action['repo']}",
            token=github_token
        )
        success = True
    
    elif revert_action["type"] == "repository_archive":
        from saferun.app.providers.github_provider import GitHubProvider
        await GitHubProvider.archive(
            target_id=f"{revert_action['owner']}/{revert_action['repo']}",
            token=github_token
        )
        success = True
    
    # Additional 7 Critical GitHub Operations
    
    elif revert_action["type"] == "restore_secret":
        # Restore previous secret value (by deleting new one)
        # Note: Cannot restore actual value unless we encrypted and stored it
        from saferun.app.providers.github_provider import GitHubProvider
        await GitHubProvider.delete_secret(
            owner=revert_action["owner"],
            repo=revert_action["repo"],
            secret_name=revert_action["secret_name"],
            token=github_token
        )
        success = True
    
    elif revert_action["type"] == "delete_secret":
        # Delete newly created secret (revert creation)
        from saferun.app.providers.github_provider import GitHubProvider
        await GitHubProvider.delete_secret(
            owner=revert_action["owner"],
            repo=revert_action["repo"],
            secret_name=revert_action["secret_name"],
            token=github_token
        )
        success = True
    
    elif revert_action["type"] == "restore_workflow_file":
        # Restore previous version of workflow file
        from saferun.app.providers.github_provider import GitHubProvider
        
        previous_sha = revert_action.get("sha")
        if not previous_sha:
            raise HTTPException(
                status_code=400,
                detail="Cannot revert: previous file SHA not available"
            )
        
        # Get previous file content using the SHA
        prev_file = await GitHubProvider._request(
            "GET",
            f"/repos/{revert_action['owner']}/{revert_action['repo']}/contents/{revert_action['path']}",
            github_token,
            params={"ref": previous_sha}
        )
        
        # Restore previous version
        import base64
        previous_content = base64.b64decode(prev_file.get("content", "")).decode('utf-8')
        
        await GitHubProvider.update_workflow_file(
            owner=revert_action["owner"],
            repo=revert_action["repo"],
            path=revert_action["path"],
            content=previous_content,
            message="Revert workflow changes via SafeRun",
            token=github_token
        )
        success = True
    
    elif revert_action["type"] == "restore_branch_protection":
        # Restore previous branch protection settings
        from saferun.app.providers.github_provider import GitHubProvider
        
        previous_settings = revert_action.get("settings")
        if not previous_settings:
            raise HTTPException(
                status_code=400,
                detail="Cannot revert: previous protection settings not available"
            )
        
        # Extract settings from previous_settings JSON
        required_pull_request_reviews = previous_settings.get("required_pull_request_reviews", {})
        required_status_checks = previous_settings.get("required_status_checks", {})
        
        required_reviews = required_pull_request_reviews.get("required_approving_review_count")
        dismiss_stale_reviews = required_pull_request_reviews.get("dismiss_stale_reviews")
        require_code_owner_reviews = required_pull_request_reviews.get("require_code_owner_reviews")
        
        status_checks_list = required_status_checks.get("contexts", []) if required_status_checks else None
        enforce_admins = previous_settings.get("enforce_admins", {}).get("enabled")
        
        # Restore protection using previous settings
        await GitHubProvider.update_branch_protection(
            owner=revert_action["owner"],
            repo=revert_action["repo"],
            branch=revert_action["branch"],
            token=github_token,
            required_reviews=required_reviews,
            dismiss_stale_reviews=dismiss_stale_reviews,
            require_code_owner_reviews=require_code_owner_reviews,
            required_status_checks=status_checks_list,
            enforce_admins=enforce_admins
        )
        success = True
    
    elif revert_action["type"] == "restore_visibility":
        # Restore previous repository visibility
        from saferun.app.providers.github_provider import GitHubProvider
        
        await GitHubProvider.change_repository_visibility(
            owner=revert_action["owner"],
            repo=revert_action["repo"],
            private=revert_action["private"],
            token=github_token
        )
        success = True
    
    if success:
        # Update change status
        db.exec(
            "UPDATE changes SET status=%s WHERE change_id=%s",
            ("reverted", change_id)
        )
        
        # Add audit log
        db.insert_audit(change_id, "reverted", {"revert_type": revert_action["type"]})
        
        # Send Slack notification for successful revert via OAuth notifier
        change_api_key = change.get("api_key")
        if change_api_key:
            try:
                # Update change with revert info for notifier
                change["status"] = "reverted"
                await notifier.publish(
                    event="reverted",
                    change=change,
                    extras={
                        "revert_type": revert_action["type"],
                        "revert_action": revert_action
                    },
                    api_key=change_api_key
                )
                print(f"✅ Sent revert success notification to Slack")
            except Exception as e:
                print(f"⚠️ Failed to send Slack notification for revert: {e}")
        
        return {
            "status": "reverted",
            "change_id": change_id,
            "revert_type": revert_action["type"]
        }
    else:
        raise HTTPException(status_code=500, detail="Revert failed")
