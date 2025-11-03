from fastapi import APIRouter, Request, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
import json, hmac, hashlib, os
import logging
from .. import storage as storage_manager
from .. import db_adapter as db

router = APIRouter(prefix="/slack", tags=["slack"])
logger = logging.getLogger(__name__)

SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET")

def verify_slack_signature(request_body: bytes, timestamp: str, signature: str) -> bool:
    """Verify request came from Slack"""
    if not SLACK_SIGNING_SECRET:
        return True  # Skip verification if no secret configured

    sig_basestring = f"v0:{timestamp}:{request_body.decode('utf-8')}"
    expected_signature = "v0=" + hmac.new(
        SLACK_SIGNING_SECRET.encode(),
        sig_basestring.encode(),
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(expected_signature, signature)

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
        raise HTTPException(status_code=401, detail="Invalid signature")

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
    user_name = user.get("name", "unknown")
    response_url = payload.get("response_url")
    trigger_id = payload.get("trigger_id")  # For opening modals

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
        
        # Default message for approve/reject
        update_payload = {
            "replace_original": True,
            "text": f"{message} (by @{user_name})",
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*{message}*\nActioned by: @{user_name}\nChange ID: `{change_id}`"
                    }
                }
            ]
        }
        
        async with httpx.AsyncClient() as client:
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
            
            # Determine revert action based on object type
            if object_type == "repository":
                # Unarchive repository
                await provider_instance.unarchive(target_id, token)
            elif object_type == "branch":
                # Restore deleted branch using saved SHA from summary_json
                sha = summary_json.get("github_restore_sha")
                if not sha:
                    raise RuntimeError("Missing branch SHA for restore in summary_json")
                await provider_instance.restore_branch(target_id, token, sha)
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
    async with httpx.AsyncClient() as client:
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
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"https://saferun-api.up.railway.app/webhooks/github/revert/{change_id}",
                json={"github_token": github_token},
                timeout=30.0
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
    """
    import httpx
    
    try:
        # Execute the revert operation (this may take 5-30 seconds)
        success, revert_info = await revert_change(change_id, user_name)
        
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
            # Revert failed (window expired or other error)
            update_payload = {
                "replace_original": True,
                "text": f"❌ Revert Failed",
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*❌ Failed to revert*\n\nRevert window may have expired or operation already reverted.\n\nActioned by: @{user_name}\nChange ID: `{change_id}`"
                        }
                    }
                ]
            }
        
        # Send update to Slack
        async with httpx.AsyncClient(timeout=30.0) as client:
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
