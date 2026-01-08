from fastapi import APIRouter, Request, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
import json, hmac, hashlib, os
import logging
from .. import storage as storage_manager
from .. import db_adapter as db

router = APIRouter(prefix="/slack", tags=["slack"])
logger = logging.getLogger(__name__)

SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET")
BASE_URL = os.getenv("SAFERUN_API_URL", os.getenv("BASE_URL", "http://localhost:8000"))

# Optional: Admin whitelist - only these Slack user IDs can approve/reject
# Format: comma-separated user IDs, e.g. "U12345,U67890"
SLACK_ADMIN_WHITELIST = os.getenv("SLACK_ADMIN_WHITELIST", "").split(",") if os.getenv("SLACK_ADMIN_WHITELIST") else []

# SECURITY WARNING: Log if admin whitelist is not configured
if not SLACK_ADMIN_WHITELIST or SLACK_ADMIN_WHITELIST == [""]:
    logger.warning(
        "[SECURITY] SLACK_ADMIN_WHITELIST not configured. "
        "Any Slack workspace member can approve/reject operations. "
        "To restrict access, set SLACK_ADMIN_WHITELIST=U12345,U67890"
    )

def verify_slack_signature(request_body: bytes, timestamp: str, signature: str) -> bool:
    """
    Verify request came from Slack using HMAC-SHA256 signature.
    
    SECURITY: In production, SLACK_SIGNING_SECRET MUST be configured.
    Without it, any attacker can forge Slack requests.
    """
    if not SLACK_SIGNING_SECRET:
        # SECURITY FIX: Log warning and reject in production
        # Only allow unsigned requests in development for testing
        import os as os_module
        is_production = os_module.getenv("RAILWAY_ENVIRONMENT") or os_module.getenv("RENDER") or os_module.getenv("VERCEL")
        if is_production:
            logger.error("[SECURITY] SLACK_SIGNING_SECRET not configured in production! Rejecting request.")
            return False
        else:
            logger.warning("[SECURITY] SLACK_SIGNING_SECRET not configured - skipping signature verification (dev mode only)")
            return True
    
    # Check timestamp to prevent replay attacks (5 min window)
    import time
    try:
        request_timestamp = int(timestamp)
        current_time = int(time.time())
        if abs(current_time - request_timestamp) > 300:  # 5 minutes
            logger.warning(f"[SECURITY] Slack request timestamp too old: {abs(current_time - request_timestamp)}s")
            return False
    except (ValueError, TypeError):
        logger.warning("[SECURITY] Invalid Slack timestamp")
        return False

    sig_basestring = f"v0:{timestamp}:{request_body.decode('utf-8')}"
    expected_signature = "v0=" + hmac.new(
        SLACK_SIGNING_SECRET.encode(),
        sig_basestring.encode(),
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(expected_signature, signature)


def is_admin_allowed(user_id: str) -> bool:
    """
    Check if user is allowed to approve/reject changes.
    
    If SLACK_ADMIN_WHITELIST is configured, only listed users can act.
    If not configured, all users can act (default behavior).
    """
    if not SLACK_ADMIN_WHITELIST or SLACK_ADMIN_WHITELIST == [""]:
        return True  # No whitelist = all users allowed
    
    return user_id in SLACK_ADMIN_WHITELIST

@router.post("/interactions")
async def handle_slack_interaction(request: Request, background_tasks: BackgroundTasks):
    """Handle Slack interactive button clicks and URL verification"""

    # Get raw body and headers
    body = await request.body()
    headers = request.headers

    # Try to parse as JSON first (for URL verification challenge)
    try:
        payload = json.loads(body.decode("utf-8"))

        # Handle Slack URL verification challenge
        if payload.get("type") == "url_verification":
            return JSONResponse({"challenge": payload.get("challenge")})
    except json.JSONDecodeError:
        # Not JSON, continue to parse as form-encoded
        pass

    # Verify Slack signature
    timestamp = headers.get("X-Slack-Request-Timestamp", "")
    signature = headers.get("X-Slack-Signature", "")

    if not verify_slack_signature(body, timestamp, signature):
        raise HTTPException(status_code=403, detail="Invalid signature")

    # Parse form-encoded payload (for button interactions)
    from urllib.parse import parse_qs
    params = parse_qs(body.decode("utf-8"))
    payload_json = params.get("payload", [""])[0]

    if not payload_json:
        raise HTTPException(status_code=400, detail="No payload")

    payload = json.loads(payload_json)

    # Extract action info
    action_type = payload.get("type")
    
    # Handle modal submission (revert with token)
    if action_type == "view_submission":
        return await handle_modal_submission(payload)
    
    if action_type != "block_actions":
        return JSONResponse({"ok": True})  # Ignore non-action events

    actions = payload.get("actions", [])
    if not actions:
        return JSONResponse({"ok": True})

    action = actions[0]
    action_id = action.get("action_id")
    change_id = action.get("value")
    user = payload.get("user", {})
    user_id = user.get("id", "")
    user_name = user.get("name", "unknown")
    response_url = payload.get("response_url")
    trigger_id = payload.get("trigger_id")  # For opening modals

    # SECURITY: Check admin whitelist if configured
    if action_id in ("approve_change", "reject_change", "revert_change") or action_id.startswith("revert_action_"):
        if not is_admin_allowed(user_id):
            logger.warning(f"[SECURITY] User {user_name} ({user_id}) not in admin whitelist, rejecting action")
            # Send ephemeral error message to user
            if response_url:
                import httpx
                error_payload = {
                    "response_type": "ephemeral",
                    "replace_original": False,
                    "text": "⛔ You are not authorized to approve/reject SafeRun operations. Contact your admin."
                }
                async with httpx.AsyncClient(timeout=5.0) as client:
                    await client.post(response_url, json=error_payload)
            return JSONResponse({"ok": True})

    # Handle revert action - open modal for GitHub token input
    if action_id.startswith("revert_action_"):
        change_id_from_action = action_id.replace("revert_action_", "")
        return await open_revert_modal(trigger_id, change_id_from_action, payload)

    # Process action
    if action_id == "approve_change":
        success = await approve_change(change_id, user_name)
        message = "✅ Change approved!" if success else "❌ Failed to approve"
    elif action_id == "reject_change":
        success = await reject_change(change_id, user_name)
        message = "❌ Change rejected!" if success else "Failed to reject"
    elif action_id == "revert_change":
        # For revert - schedule background task and return immediately
        background_tasks.add_task(
            execute_revert_in_background,
            change_id=change_id,
            user_name=user_name,
            response_url=response_url
        )
        # Return immediate acknowledgment to Slack (prevents 500 error)
        return JSONResponse({"ok": True})
    else:
        return JSONResponse({"ok": True})

    # Update message using response_url (for approve/reject only - revert handled in background)
    if response_url:
        import httpx
        from datetime import datetime, timezone
        
        # Get change details for better message
        storage = storage_manager.get_storage()
        change = storage.get_change(change_id)
        
        # Banking Grade Audit Trail: Preserve original blocks, remove actions, add decision
        original_blocks = payload.get("message", {}).get("blocks", [])
        
        # Filter out action blocks (buttons) and build new block list
        preserved_blocks = []
        for block in original_blocks:
            if block.get("type") != "actions":
                preserved_blocks.append(block)
        
        # Determine decision status
        if "approved" in message.lower():
            status_emoji = "✅"
            status_text = "APPROVED"
            status_color = "#28a745"  # Green
        else:
            status_emoji = "❌" 
            status_text = "REJECTED"
            status_color = "#dc3545"  # Red
        
        # Add Decision block with timestamp (Audit Trail)
        decision_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        preserved_blocks.append({
            "type": "divider"
        })
        preserved_blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*{status_emoji} {status_text}* by <@{user_id}>\n_Decision recorded at {decision_time}_"
            }
        })
        
        # Update context block to include decision audit
        preserved_blocks.append({
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"🔐 Audit: `{change_id[:12]}...` • {status_text.lower()} by @{user_name}"}
            ]
        })
        
        update_payload = {
            "replace_original": True,
            "text": f"{status_emoji} Change {status_text} by @{user_name}",
            "blocks": preserved_blocks
        }
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(response_url, json=update_payload)

    return JSONResponse({"ok": True})

async def approve_change(change_id: str, user: str) -> bool:
    """Approve a pending change"""
    # Try git operations first
    from ..services.git_operations import get_git_operation_status, confirm_git_operation
    try:
        git_op = get_git_operation_status(change_id)
        if git_op:
            confirm_git_operation(change_id, "approved", {"approved_by": user, "approved_via": "slack"})
            return True
    except ValueError:
        pass  # Not a git operation, try regular change

    # Fallback to regular changes
    storage = storage_manager.get_storage()
    change = storage.get_change(change_id)

    if not change:
        return False

    storage.set_change_status(change_id, "approved")
    db.insert_audit(change_id, "approved", {"approved_by": user, "approved_via": "slack"})
    return True

async def reject_change(change_id: str, user: str) -> bool:
    """Reject a pending change"""
    # Try git operations first
    from ..services.git_operations import get_git_operation_status, confirm_git_operation
    try:
        git_op = get_git_operation_status(change_id)
        if git_op:
            confirm_git_operation(change_id, "rejected", {"rejected_by": user, "rejected_via": "slack"})
            return True
    except ValueError:
        pass  # Not a git operation, try regular change

    # Fallback to regular changes
    storage = storage_manager.get_storage()
    change = storage.get_change(change_id)

    if not change:
        return False

    storage.set_change_status(change_id, "rejected")
    db.insert_audit(change_id, "rejected", {"rejected_by": user, "rejected_via": "slack"})
    return True

async def revert_change(change_id: str, user: str) -> tuple[bool, dict]:
    """Revert an executed change (unarchive, restore branch, reopen PRs)
    Returns: (success: bool, info: dict with provider, target_id, operation)
    """
    storage = storage_manager.get_storage()
    change = storage.get_change(change_id)

    if not change:
        return False, {}

    # Check if change is in executed status
    if change.get("status") != "executed":
        return False, {}

    # Check if revert window has expired
    from datetime import datetime, timezone
    revert_expires = change.get("revert_expires_at")
    if revert_expires:
        # Handle both datetime objects (from DB) and ISO strings (from API)
        if isinstance(revert_expires, datetime):
            expires_dt = revert_expires
            # Ensure timezone-aware for comparison
            if expires_dt.tzinfo is None:
                expires_dt = expires_dt.replace(tzinfo=timezone.utc)
        else:
            expires_dt = datetime.fromisoformat(revert_expires.replace("Z", "+00:00"))
        if datetime.now(timezone.utc) > expires_dt:
            return False, {}  # Revert window expired

    # Prepare revert info
    revert_info = {
        "provider": change.get("provider"),
        "target_id": change.get("target_id"),
        "operation": change.get("title", "Operation")
    }

    # Execute revert based on operation type
    provider = change.get("provider")
    if provider == "github":
        from ..providers import factory as provider_factory
        import json
        try:
            provider_instance = provider_factory.get_provider(provider)
            token = change.get("token")
            target_id = change.get("target_id")
            metadata = change.get("metadata", {})
            # Metadata might be JSON string from storage
            if isinstance(metadata, str):
                metadata = json.loads(metadata) if metadata else {}
            object_type = metadata.get("object") or metadata.get("type")
            
            # Get summary_json which contains revert data (SHA, PR numbers)
            summary_json = change.get("summary_json", {})
            if isinstance(summary_json, str):
                summary_json = json.loads(summary_json) if summary_json else {}
            
            # FALLBACK 1: Infer object_type from revert_action for old records
            if not object_type:
                revert_action = summary_json.get("revert_action", {})
                revert_type = revert_action.get("type", "")
                if revert_type == "force_push_revert":
                    object_type = "force_push"
                elif revert_type == "branch_restore":
                    object_type = "branch"
                elif revert_type == "merge_revert":
                    object_type = "merge"
                elif revert_type == "repository_unarchive":
                    object_type = "repository"
            
            # If no token, try to get GitHub App installation token
            if not token:
                installation_id = summary_json.get("installation_id")
                
                # FALLBACK 2: Find installation_id from github_installations by repo name
                if not installation_id:
                    repo_name = summary_json.get("repo_name") or target_id
                    if repo_name:
                        install_record = db.fetchone(
                            "SELECT installation_id FROM github_installations WHERE repositories_json::text LIKE %s LIMIT 1",
                            (f"%{repo_name}%",)
                        )
                        if install_record:
                            installation_id = install_record.get("installation_id")
                
                if installation_id:
                    from ..services.github import get_github_app_installation_token
                    token = get_github_app_installation_token(installation_id)
                    if not token:
                        raise RuntimeError("Failed to get GitHub App token for revert")
                else:
                    raise RuntimeError("No installation_id found for GitHub App token")
            
            # Determine revert action based on object type
            if object_type == "repository":
                # Unarchive repository
                await provider_instance.unarchive(target_id, token)
            elif object_type == "branch":
                # Restore deleted branch using saved SHA from summary_json
                sha = summary_json.get("github_restore_sha")
                if not sha:
                    # Try revert_action from summary_json
                    revert_action = summary_json.get("revert_action", {})
                    sha = revert_action.get("sha")
                if not sha:
                    raise RuntimeError("Missing branch SHA for restore in summary_json")
                await provider_instance.restore_branch(target_id, token, sha)
            elif object_type == "force_push":
                # Revert force push by restoring previous SHA
                from ..services.github import revert_force_push
                revert_action = summary_json.get("revert_action", {})
                
                # FALLBACK 3: Try multiple sources for before_sha
                before_sha = revert_action.get("before_sha")
                if not before_sha:
                    # Try raw webhook payload
                    payload = summary_json.get("payload", {})
                    before_sha = payload.get("before")
                if not before_sha:
                    # Try branch_head_sha from change record (saved during webhook)
                    before_sha = change.get("branch_head_sha")
                
                branch = summary_json.get("branch_name") or revert_action.get("branch")
                owner = revert_action.get("owner") or target_id.split("/")[0]
                repo = revert_action.get("repo") or target_id.split("/")[1]
                
                if not before_sha:
                    raise RuntimeError(f"Missing before_sha for force push revert (change_id={change_id})")
                if not branch:
                    raise RuntimeError(f"Missing branch name for force push revert (change_id={change_id})")
                
                success = await revert_force_push(owner, repo, branch, before_sha, token)
                if not success:
                    raise RuntimeError("GitHub API rejected force push revert")
            elif object_type == "merge":
                # Revert merge commit by creating revert commit
                from ..services.github import create_revert_commit
                revert_action = summary_json.get("revert_action", {})
                merge_commit_sha = revert_action.get("merge_commit_sha")
                branch = revert_action.get("branch") or summary_json.get("branch_name")
                owner = revert_action.get("owner") or target_id.split("/")[0]
                repo = revert_action.get("repo") or target_id.split("/")[1]
                
                if not merge_commit_sha:
                    raise RuntimeError("Missing merge_commit_sha for merge revert")
                if not branch:
                    raise RuntimeError("Missing branch name for merge revert")
                
                success = await create_revert_commit(owner, repo, branch, merge_commit_sha, token)
                if not success:
                    raise RuntimeError("GitHub API rejected merge revert")
            elif object_type == "bulk_pr":
                # Reopen closed PRs using PR numbers from summary_json
                pr_numbers = summary_json.get("github_bulk_pr_numbers", [])
                if not pr_numbers:
                    raise RuntimeError("Missing PR numbers for reopen in summary_json")
                await provider_instance.bulk_reopen_prs(target_id, [int(n) for n in pr_numbers], token)
            else:
                raise RuntimeError(f"Unsupported revert operation for type: {object_type}")
            
            # Update status
            storage.set_change_status(change_id, "reverted")
            db.insert_audit(change_id, "reverted", {"reverted_by": user, "reverted_via": "slack", "object_type": object_type})
            return True, revert_info
        except Exception as e:
            print(f"❌ Revert failed: {str(e)}")
            import traceback
            traceback.print_exc()
            return False, {}

async def open_revert_modal(trigger_id: str, change_id: str, payload: dict) -> JSONResponse:
    """Open Slack modal for GitHub token input"""
    
    # Get SLACK_BOT_TOKEN from env
    slack_bot_token = os.getenv("SLACK_BOT_TOKEN")
    if not slack_bot_token:
        print("❌ SLACK_BOT_TOKEN not configured")
        return JSONResponse({"ok": False, "error": "Slack bot token not configured"})
    
    # Fetch change details
    change = db.fetchone("SELECT * FROM changes WHERE change_id=%s", (change_id,))
    if not change:
        return JSONResponse({"ok": False, "error": "Change not found"})
    
    summary_json = json.loads(change.get("summary_json", "{}"))
    operation_type = summary_json.get("operation_type", "Unknown Operation")
    repo_name = summary_json.get("repo_name", "Unknown Repo")
    branch_name = summary_json.get("branch_name", "")
    
    # Build modal view
    modal_view = {
        "type": "modal",
        "callback_id": f"revert_modal_{change_id}",
        "title": {
            "type": "plain_text",
            "text": "🔄 Revert Operation"
        },
        "submit": {
            "type": "plain_text",
            "text": "Revert"
        },
        "close": {
            "type": "plain_text",
            "text": "Cancel"
        },
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Operation:* {operation_type}\n*Repository:* `{repo_name}`" + (f"\n*Branch:* `{branch_name}`" if branch_name else "")
                }
            },
            {
                "type": "divider"
            },
            {
                "type": "input",
                "block_id": "github_token_block",
                "element": {
                    "type": "plain_text_input",
                    "action_id": "github_token_input",
                    "placeholder": {
                        "type": "plain_text",
                        "text": "ghp_YourGitHubPersonalAccessToken"
                    }
                },
                "label": {
                    "type": "plain_text",
                    "text": "GitHub Personal Access Token (with repo permissions)"
                }
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": "🔒 Your token will be used once and not stored."
                    }
                ]
            }
        ]
    }
    
    # Open modal using Slack API
    import httpx
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            "https://slack.com/api/views.open",
            headers={
                "Authorization": f"Bearer {slack_bot_token}",
                "Content-Type": "application/json"
            },
            json={
                "trigger_id": trigger_id,
                "view": modal_view
            }
        )
        
        result = response.json()
        if not result.get("ok"):
            print(f"❌ Failed to open modal: {result.get('error')}")
            return JSONResponse({"ok": False, "error": result.get("error")})
    
    return JSONResponse({"ok": True})

async def handle_modal_submission(payload: dict) -> JSONResponse:
    """Handle modal submission (user entered GitHub token)"""
    
    view = payload.get("view", {})
    callback_id = view.get("callback_id", "")
    
    # Extract change_id from callback_id (format: revert_modal_{change_id})
    if not callback_id.startswith("revert_modal_"):
        return JSONResponse({"ok": False})
    
    change_id = callback_id.replace("revert_modal_", "")
    
    # Extract GitHub token from modal input
    state_values = view.get("state", {}).get("values", {})
    github_token_block = state_values.get("github_token_block", {})
    github_token_input = github_token_block.get("github_token_input", {})
    github_token = github_token_input.get("value", "").strip()
    
    if not github_token:
        return JSONResponse({
            "response_action": "errors",
            "errors": {
                "github_token_block": "GitHub token is required"
            }
        })
    
    # Get user info
    user = payload.get("user", {})
    user_name = user.get("name", "unknown")
    
    # Call revert endpoint with github_token
    import httpx
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{BASE_URL}/webhooks/github/revert/{change_id}",
                json={"github_token": github_token}
            )
            
            if response.status_code == 200:
                result = response.json()
                # Slack will close modal and show success message
                return JSONResponse({
                    "response_action": "clear"
                })
            else:
                error_detail = response.json().get("detail", "Unknown error")
                return JSONResponse({
                    "response_action": "errors",
                    "errors": {
                        "github_token_block": f"Revert failed: {error_detail}"
                    }
                })
                
    except Exception as e:
        return JSONResponse({
            "response_action": "errors",
            "errors": {
                "github_token_block": f"Error: {str(e)}"
            }
        })


async def execute_revert_in_background(change_id: str, user_name: str, response_url: str):
    """
    Execute revert operation in background and update Slack message via response_url.
    This prevents Slack 500 error by allowing immediate acknowledgment.
    
    Timeouts:
    - Revert execution: 5 minutes (300s) - enough for slow GitHub API on large repos
    - Slack response: 30 seconds - just for sending status message
    """
    import httpx
    import asyncio
    
    REVERT_TIMEOUT_SECONDS = 300  # 5 minutes for GitHub operations
    SLACK_RESPONSE_TIMEOUT = 30   # 30 seconds to send Slack message
    
    try:
        # Execute the revert operation with timeout (may take 5-30 seconds, max 5 min)
        try:
            success, revert_info = await asyncio.wait_for(
                revert_change(change_id, user_name),
                timeout=REVERT_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            logger.error(f"Revert operation timed out after {REVERT_TIMEOUT_SECONDS}s for change {change_id}")
            success = False
            revert_info = {"timeout": True}
        
        if success and revert_info:
            # Build success message
            provider = revert_info.get("provider", "unknown")
            target_id = revert_info.get("target_id", "")
            operation = revert_info.get("operation", "Operation")
            
            # Generate verification link for GitHub
            verification_link = ""
            if provider == "github" and "#" in target_id:
                repo, branch = target_id.split("#", 1)
                if "→" not in branch:  # Branch restore (not merge)
                    verification_link = f"\n\n*Verify on GitHub:*\n<https://github.com/{repo}/tree/{branch}|View restored branch>"
            
            update_payload = {
                "replace_original": True,
                "text": f"✅ Action Reverted",
                "blocks": [
                    {
                        "type": "header",
                        "text": {"type": "plain_text", "text": "✅ Action Reverted"}
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*{operation} reverted successfully!*\n\n*Actioned by:* @{user_name}\n*Change ID:* `{change_id}`\n*Provider:* {provider}{verification_link}"
                        }
                    }
                ]
            }
        else:
            # Revert failed (window expired, timeout, or other error)
            if revert_info and revert_info.get("timeout"):
                error_reason = "Operation timed out after 5 minutes. GitHub may be slow - check manually."
            else:
                error_reason = "Revert window may have expired or operation already reverted."
            
            update_payload = {
                "replace_original": True,
                "text": f"❌ Revert Failed",
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*❌ Failed to revert*\n\n{error_reason}\n\nActioned by: @{user_name}\nChange ID: `{change_id}`"
                        }
                    }
                ]
            }
        
        # Send update to Slack
        async with httpx.AsyncClient(timeout=SLACK_RESPONSE_TIMEOUT) as client:
            response = await client.post(response_url, json=update_payload)
            if response.status_code != 200:
                logger.error(f"Failed to update Slack message: {response.text}")
            
    except Exception as e:
        logger.error(f"Background revert task failed: {str(e)}")
        import traceback
        traceback.print_exc()
        
        # Try to send error message to Slack
        try:
            error_payload = {
                "replace_original": True,
                "text": f"❌ Revert Error",
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*❌ Revert operation failed*\n\nError: {str(e)}\n\nActioned by: @{user_name}\nChange ID: `{change_id}`"
                        }
                    }
                ]
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(response_url, json=error_payload)
        except:
            pass  # If we can't even send error message, just log it


@router.post("/events")
async def handle_slack_events(request: Request):
    """
    Handle Slack Events API callbacks.
    
    Used to detect when bot is added to a channel (member_joined_channel).
    This allows zero-config channel detection - user just /invite @SafeRun
    """
    body = await request.body()
    headers = request.headers
    
    # Verify signature
    timestamp = headers.get("X-Slack-Request-Timestamp", "")
    signature = headers.get("X-Slack-Signature", "")
    
    if not verify_slack_signature(body, timestamp, signature):
        logger.warning("[SLACK EVENTS] Invalid signature")
        raise HTTPException(status_code=403, detail="Forbidden")
    
    try:
        payload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    
    # Handle URL verification challenge
    if payload.get("type") == "url_verification":
        return JSONResponse({"challenge": payload.get("challenge")})
    
    # Handle event callbacks
    if payload.get("type") == "event_callback":
        event = payload.get("event", {})
        event_type = event.get("type")
        team_id = payload.get("team_id")
        
        logger.info(f"[SLACK EVENTS] Received event: {event_type} for team {team_id}")
        
        if event_type == "member_joined_channel":
            # Bot was added to a channel
            user_id = event.get("user")  # User who joined (could be the bot)
            channel_id = event.get("channel")
            
            # Check if it's our bot that joined (not another user)
            # We need to check if user_id matches our bot_user_id
            slack_installation = db.get_slack_installation_by_team(team_id)
            
            if slack_installation:
                bot_user_id = slack_installation.get("bot_user_id")
                
                if user_id == bot_user_id:
                    # Our bot was added to a channel - save it!
                    logger.info(f"[SLACK EVENTS] Bot joined channel {channel_id} in team {team_id}")
                    
                    success = db.update_slack_channel(team_id, channel_id)
                    if success:
                        logger.info(f"[SLACK EVENTS] Updated channel_id to {channel_id} for team {team_id}")
                        
                        # Send welcome message to the channel
                        try:
                            bot_token = slack_installation.get("bot_token")
                            if bot_token:
                                import httpx
                                welcome_blocks = [
                                    {
                                        "type": "section",
                                        "text": {
                                            "type": "mrkdwn",
                                            "text": "👋 *SafeRun is now active in this channel!*\n\nI'll send approval requests here when dangerous git operations are detected:\n• `git push --force`\n• `git reset --hard`\n• `git branch -D`\n• Branch deletions"
                                        }
                                    },
                                    {
                                        "type": "context",
                                        "elements": [
                                            {
                                                "type": "mrkdwn",
                                                "text": "💡 To move me to another channel, just `/invite @SafeRun` there"
                                            }
                                        ]
                                    }
                                ]
                                
                                async with httpx.AsyncClient() as client:
                                    await client.post(
                                        "https://slack.com/api/chat.postMessage",
                                        headers={"Authorization": f"Bearer {bot_token}"},
                                        json={
                                            "channel": channel_id,
                                            "blocks": welcome_blocks,
                                            "text": "SafeRun is now active in this channel!"
                                        }
                                    )
                                logger.info(f"[SLACK EVENTS] Sent welcome message to channel {channel_id}")
                        except Exception as e:
                            logger.warning(f"[SLACK EVENTS] Failed to send welcome message: {e}")
                    else:
                        logger.warning(f"[SLACK EVENTS] Failed to update channel_id for team {team_id}")
        
        elif event_type == "app_uninstalled":
            # App was uninstalled from workspace
            logger.info(f"[SLACK EVENTS] App uninstalled from team {team_id}")
            # Optionally: mark installation as inactive in DB
    
    # Always return 200 OK to acknowledge receipt
    return JSONResponse({"ok": True})
