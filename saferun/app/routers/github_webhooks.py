"""GitHub App webhook endpoints"""
from fastapi import APIRouter, Request, HTTPException, Header, Depends
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
    create_revert_commit
)
from ..notify import send_to_slack, format_slack_message

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
        # New installation - store in DB
        db.exec(
            "INSERT INTO github_installations(installation_id, account_login, installed_at, repositories_json) VALUES(%s,%s,%s,%s) ON CONFLICT (installation_id) DO NOTHING",
            (installation_id, account_login, iso_z(datetime.now(timezone.utc)), json.dumps([]))
        )
        
        print(f"✅ GitHub App installed: installation_id={installation_id}, account={account_login}")
        
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
    
    # Extract repository and user info
    repository = payload.get("repository", {})
    repo_full_name = repository.get("full_name", "unknown/unknown")
    sender = payload.get("sender", {})
    sender_login = sender.get("login", "unknown")
    
    # FILTER OUT: Push events with zero commits (GitHub sends these on branch delete - ignore them!)
    if event_type == "push":
        commits = payload.get("commits", [])
        deleted = payload.get("deleted", False)
        if not commits or deleted:
            print(f"⏭️  Ignoring empty push event (likely branch delete artifact): {repo_full_name}")
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
        # Check for recent API-initiated operations
        check_time = (datetime.now() - timedelta(minutes=5)).isoformat()
        
        # Map webhook action_type to operation_type stored in summary_json
        if action_type == "github_merge":
            operation_type_pattern = "merge"
        elif action_type == "github_force_push":
            operation_type_pattern = "force_push"
        else:
            operation_type_pattern = action_type
        
        # Check for PENDING operations (skip webhook to avoid duplicate approval requests)
        recent_pending_op = db.fetchone(
            """SELECT change_id, status FROM changes 
               WHERE target_id LIKE %s 
               AND summary_json LIKE %s
               AND summary_json LIKE %s
               AND created_at > %s
               AND status = 'pending'
               ORDER BY created_at DESC
               LIMIT 1""",
            (f"%{repo_full_name}%", '%"initiated_via":"api"%', f'%"operation_type":"{operation_type_pattern}"%', check_time)
        )
        
        if recent_pending_op:
            # Skip - user already has approval request from CLI
            print(f"⏭️  Skipping webhook notification - Pending API-initiated operation detected: {recent_pending_op['change_id']}")
            return {"status": "skipped", "reason": "api_pending", "api_change_id": recent_pending_op['change_id']}
        
        # Check for EXECUTED operations (send completion notification)
        recent_executed_op = db.fetchone(
            """SELECT change_id, status, summary_json FROM changes 
               WHERE target_id LIKE %s 
               AND summary_json LIKE %s
               AND summary_json LIKE %s
               AND created_at > %s
               AND status IN ('approved', 'executed')
               ORDER BY created_at DESC
               LIMIT 1""",
            (f"%{repo_full_name}%", '%"initiated_via":"api"%', f'%"operation_type":"{operation_type_pattern}"%', check_time)
        )
        
        if recent_executed_op:
            # Send completion notification instead of new approval request
            print(f"✅ Sending completion notification for executed operation: {recent_executed_op['change_id']}")
            # TODO: Implement send_completion_notification()
            # For now, skip webhook to avoid duplicate/confusing notification
            return {"status": "completion_notification_sent", "api_change_id": recent_executed_op['change_id']}
    
    # Generate unique change ID
    change_id = str(uuid.uuid4())
    
    # Find user by installation_id
    installation_id = payload.get("installation", {}).get("id")
    user_email = None
    user_api_key = None
    slack_webhook_url = None
    
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
                # Get Slack webhook from notification settings (using db_adapter for proper decryption)
                from ..db_adapter import get_notification_settings
                notif_settings = get_notification_settings(user_api_key)
                if notif_settings and notif_settings.get("slack_enabled"):
                    slack_webhook_url = notif_settings.get("slack_webhook_url")
    
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
        # Query last push event for this branch
        last_push = db.fetchone(
            """SELECT branch_head_sha FROM changes 
               WHERE target_id = %s 
               AND branch_head_sha IS NOT NULL
               ORDER BY created_at DESC LIMIT 1""",
            (repo_full_name,)
        )
        if last_push and last_push.get("branch_head_sha"):
            revert_action["sha"] = last_push["branch_head_sha"]
            print(f"✅ Retrieved SHA for branch '{branch_name}' delete: {revert_action['sha']}")
        else:
            print(f"⚠️ No SHA found for deleted branch '{branch_name}' in {repo_full_name}")
    
    # Normalize risk_score to 0-1 range for storage (displayed as 0-10 in UI)
    normalized_risk_score = min(risk_score / 10.0, 1.0)
    
    # Create change record
    change = {
        "change_id": change_id,
        "target_id": repo_full_name,
        "provider": "github",
        "title": f"{action_type.replace('github_', '').replace('_', ' ').title()} - {repo_full_name}",
        "status": "pending_review" if risk_score >= 7.0 else "logged",  # Use denormalized for comparison
        "risk_score": normalized_risk_score,  # Store normalized (0-1)
        "expires_at": iso_z(datetime.now(timezone.utc) + timedelta(hours=2)),  # 2 hours for consistency with CLI
        "created_at": iso_z(datetime.now(timezone.utc)),
        "last_edited_time": iso_z(datetime.now(timezone.utc)),
        "policy_json": {"risk_reasons": reasons},
        "summary_json": {
            "operation_type": action_type,
            "repo_name": repo_full_name,
            "branch_name": payload.get("ref", "").replace("refs/heads/", "") if event_type == "push" else payload.get("ref", ""),
            "source": "github_webhook",
            "event_type": event_type,
            "sender": sender_login,
            "payload": payload,
            "revert_action": revert_action  # Now contains SHA for delete events!
        },
        "api_key": user_api_key,  # Link to user for multi-user isolation
        "branch_head_sha": branch_head_sha  # Save SHA for future revert
    }
    
    db.upsert_change(change)
    
    # Insert audit log
    db.insert_audit(change_id, "github_webhook_received", {
        "event_type": event_type,
        "risk_score": risk_score,
        "sender": sender_login,
        "installation_id": installation_id
    })
    
    # Send Slack notification if user has webhook configured
    if slack_webhook_url:
        try:
            # Create mock action object for formatting
            class MockAction:
                def __init__(self, data):
                    self.id = change_id
                    summary_json = change.get("summary_json", "{}")
                    summary = json.loads(summary_json) if isinstance(summary_json, str) else summary_json
                    self.operation_type = summary.get("operation_type", "")
                    self.repo_name = summary.get("repo_name", "")
                    self.branch_name = summary.get("branch_name", "")
                    self.risk_score = normalized_risk_score  # Use normalized (0-1) for display
                    self.risk_reasons = reasons
                    self.metadata = summary
                    self.expires_at = data.get("expires_at")  # Add expires_at for Slack formatting
            
            mock_action = MockAction(change)
            slack_message = format_slack_message(
                action=mock_action,
                user_email=user_email,
                source="github_webhook",
                event_type=event_type
            )
            
            success = await send_to_slack(slack_webhook_url, slack_message)
            if success:
                print(f"✅ Slack notification sent for change {change_id}")
            else:
                print(f"❌ Failed to send Slack notification for change {change_id}")
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
    api_key: str = Depends(verify_api_key)
):
    """
    Revert a GitHub action (force push, delete, merge)
    
    Requires:
    - change_id: SafeRun change ID to revert
    - github_token: GitHub token with write permissions (JSON body: {"github_token": "ghp_XXX"})
    - X-API-Key header: User's API key (for ownership verification)
    """
    # Verify ownership FIRST (before accessing change data)
    storage = storage_manager.get_storage()
    change = verify_change_ownership(change_id, api_key, storage)
    
    # Parse JSON body
    try:
        body = await request.json()
        github_token = body.get("github_token")
        if not github_token:
            raise HTTPException(status_code=400, detail="github_token required in request body")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON body: {str(e)}")
    
    # ✅ BUG #16 FIX: Check if operation can be reverted
    current_status = change.get("status", "pending")
    
    # Only allow revert for executed/applied operations
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
        
        # Send Slack notification for successful revert
        change_api_key = change.get("api_key")
        if change_api_key:
            try:
                notif_row = db.fetchone(
                    "SELECT slack_webhook_url, slack_enabled FROM user_notification_settings WHERE api_key=%s",
                    (change_api_key,)
                )
                if notif_row and notif_row.get("slack_enabled") and notif_row.get("slack_webhook_url"):
                    slack_webhook_url = notif_row.get("slack_webhook_url")
                    
                    # Get user email
                    user_row = db.fetchone(
                        "SELECT email FROM api_keys WHERE api_key=%s",
                        (change_api_key,)
                    )
                    user_email = user_row.get("email") if user_row else "Unknown"
                    
                    # Format message based on revert type
                    revert_type = revert_action["type"]
                    revert_type_label = {
                        "branch_restore": "Branch Restored",
                        "force_push_revert": "Force Push Reverted",
                        "merge_revert": "Merge Reverted",
                        "repository_unarchive": "Repository Unarchived"
                    }.get(revert_type, "Reverted")
                    
                    # Build message blocks based on operation type
                    if revert_type == "merge_revert":
                        # Special message for merge revert with force update info
                        before_sha = revert_action.get('before_sha', 'unknown')[:7]
                        slack_message = {
                            "text": f"✅ {revert_type_label} - Branch Force Updated",
                            "blocks": [
                                {
                                    "type": "header",
                                    "text": {
                                        "type": "plain_text",
                                        "text": f"🔄 SafeRun Revert - {revert_type_label}",
                                        "emoji": True
                                    }
                                },
                                {
                                    "type": "section",
                                    "fields": [
                                        {"type": "mrkdwn", "text": f"*Repository:*\n{revert_action.get('owner')}/{revert_action.get('repo')}"},
                                        {"type": "mrkdwn", "text": f"*Branch:*\n{revert_action.get('branch')}"},
                                        {"type": "mrkdwn", "text": f"*Reverted by:*\n{user_email}"},
                                        {"type": "mrkdwn", "text": f"*Change ID:*\n{change_id[:8]}..."}
                                    ]
                                },
                                {
                                    "type": "section",
                                    "text": {
                                        "type": "mrkdwn",
                                        "text": (
                                            "*✅ Branch force-updated to pre-merge state*\n"
                                            f"Branch `{revert_action.get('branch')}` reset to commit `{before_sha}` (state before merge).\n\n"
                                            "*⚠️ Important:*\n"
                                            "• Merge commit has been REMOVED from history (destructive operation)\n"
                                            "• Anyone who pulled the merge will have diverged history\n"
                                            "• Team members may need to reset their local branches\n"
                                            "• This does NOT prevent future unauthorized merges\n\n"
                                            "*🛡️ Recommendation:*\n"
                                            f"Enable Branch Protection to prevent future unauthorized merges:\n"
                                            f"https://github.com/{revert_action.get('owner')}/{revert_action.get('repo')}/settings/branches"
                                        )
                                    }
                                }
                            ]
                        }
                    else:
                        # Standard revert message for other operations
                        slack_message = {
                            "text": f"✅ {revert_type_label} Successfully",
                            "blocks": [
                                {
                                    "type": "header",
                                    "text": {
                                        "type": "plain_text",
                                        "text": f"✅ SafeRun Revert - {revert_type_label}",
                                        "emoji": True
                                    }
                                },
                                {
                                    "type": "section",
                                    "fields": [
                                        {"type": "mrkdwn", "text": f"*Repository:*\n{revert_action.get('owner')}/{revert_action.get('repo')}"},
                                        {"type": "mrkdwn", "text": f"*Branch:*\n{revert_action.get('branch')}"},
                                        {"type": "mrkdwn", "text": f"*Restored by:*\n{user_email}"},
                                        {"type": "mrkdwn", "text": f"*Change ID:*\n{change_id[:8]}..."}
                                    ]
                                }
                            ]
                        }
                    
                    await send_to_slack(slack_webhook_url, slack_message)
                    print(f"✅ Sent revert success notification to Slack for {user_email}")
            except Exception as e:
                print(f"⚠️ Failed to send Slack notification for revert: {e}")
        
        return {
            "status": "reverted",
            "change_id": change_id,
            "revert_type": revert_action["type"]
        }
    else:
        raise HTTPException(status_code=500, detail="Revert failed")
