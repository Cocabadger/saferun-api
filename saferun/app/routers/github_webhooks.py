"""GitHub App webhook endpoints"""
from fastapi import APIRouter, Request, HTTPException, Header
import json
import uuid
from typing import Optional
from datetime import datetime, timezone, timedelta

from .. import db_adapter as db
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
                # Get Slack webhook from notification settings
                notif_row = db.fetchone(
                    "SELECT slack_webhook_url FROM user_notification_settings WHERE api_key=%s", 
                    (user_api_key,)
                )
                if notif_row:
                    slack_webhook_url = notif_row.get("slack_webhook_url")
    
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
    
    # Create change record
    change = {
        "change_id": change_id,
        "target_id": repo_full_name,
        "provider": "github",
        "title": f"{action_type.replace('github_', '').replace('_', ' ').title()} - {repo_full_name}",
        "status": "pending_review" if risk_score >= 7.0 else "logged",
        "risk_score": risk_score,
        "expires_at": iso_z(datetime.now(timezone.utc) + timedelta(hours=24)),
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
                    self.risk_score = risk_score
                    self.risk_reasons = reasons
                    self.metadata = summary
            
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
    request: Request
):
    """
    Revert a GitHub action (force push, delete, merge)
    
    Requires:
    - change_id: SafeRun change ID to revert
    - github_token: GitHub token with write permissions (JSON body: {"github_token": "ghp_XXX"})
    """
    # Parse JSON body
    try:
        body = await request.json()
        github_token = body.get("github_token")
        if not github_token:
            raise HTTPException(status_code=400, detail="github_token required in request body")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON body: {str(e)}")
    
    change = db.fetchone("SELECT * FROM changes WHERE change_id=%s", (change_id,))
    
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    
    # SECURITY: Verify user owns this change (multi-user isolation)
    # For old records (api_key=NULL), allow revert (backward compatibility)
    # For new records, verify ownership via API key from GitHub token or request header
    change_api_key = change.get("api_key")
    if change_api_key:
        # Get user's API key from request header (if available)
        request_api_key = request.headers.get("X-API-Key")
        
        # TODO: Alternatively, could derive api_key from github_token by looking up installations
        # For now, if api_key is set but doesn't match, reject (prevents cross-user reverts)
        if request_api_key and request_api_key != change_api_key:
            raise HTTPException(
                status_code=403, 
                detail="Forbidden: You don't have permission to revert this change"
            )
        elif not request_api_key:
            print(f"⚠️ Revert attempted without API key for change with api_key={change_api_key[:10]}...")
            # Allow for now (backward compat), but log warning
    
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
    
    if success:
        # Update change status
        db.exec(
            "UPDATE changes SET status=%s WHERE change_id=%s",
            ("reverted", change_id)
        )
        
        # Add audit log
        db.insert_audit(change_id, "reverted", {"revert_type": revert_action["type"]})
        
        # Send Slack notification for successful revert
        if change_api_key:
            try:
                notif_row = db.fetchone(
                    "SELECT slack_webhook_url FROM user_notification_settings WHERE api_key=%s",
                    (change_api_key,)
                )
                if notif_row and notif_row.get("slack_webhook_url"):
                    slack_webhook_url = notif_row.get("slack_webhook_url")
                    
                    # Get user email
                    user_row = db.fetchone(
                        "SELECT email FROM api_keys WHERE api_key=%s",
                        (change_api_key,)
                    )
                    user_email = user_row.get("email") if user_row else "Unknown"
                    
                    # Format message
                    revert_type_label = {
                        "branch_restore": "Branch Restored",
                        "force_push_revert": "Force Push Reverted",
                        "merge_revert": "Merge Reverted",
                        "repository_unarchive": "Repository Unarchived"
                    }.get(revert_action["type"], "Reverted")
                    
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
