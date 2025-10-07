from fastapi import APIRouter, Request, HTTPException
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
async def handle_slack_interaction(request: Request):
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

    # Process action
    if action_id == "approve_change":
        success = await approve_change(change_id, user_name)
        message = "✅ Change approved!" if success else "❌ Failed to approve"
    elif action_id == "reject_change":
        success = await reject_change(change_id, user_name)
        message = "❌ Change rejected!" if success else "Failed to reject"
    elif action_id == "revert_change":
        success, revert_info = await revert_change(change_id, user_name)
        message = "🔄 Change reverted!" if success else "❌ Failed to revert (time expired or already reverted)"
    else:
        return JSONResponse({"ok": True})

    # Update message using response_url
    if response_url:
        import httpx
        
        # Build enhanced message for successful revert
        if action_id == "revert_change" and success and revert_info:
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
            # Default message for approve/reject/failed revert
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
            db.insert_audit(change_id, "revert_failed", {"error": str(e), "reverted_by": user})
            return False, {}

    return False, {}
