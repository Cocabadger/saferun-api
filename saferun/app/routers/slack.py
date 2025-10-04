from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
import json, hmac, hashlib, os
from .. import storage as storage_manager
from .. import db_adapter as db

router = APIRouter(prefix="/slack", tags=["slack"])

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

    # Process action
    if action_id == "approve_change":
        success = await approve_change(change_id, user_name)
        message = "✅ Change approved!" if success else "❌ Failed to approve"
    elif action_id == "reject_change":
        success = await reject_change(change_id, user_name)
        message = "❌ Change rejected!" if success else "Failed to reject"
    else:
        return JSONResponse({"ok": True})

    # Update Slack message to show it was handled
    return JSONResponse({
        "response_type": "in_channel",
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
    })

async def approve_change(change_id: str, user: str) -> bool:
    """Approve a pending change"""
    storage = storage_manager.get_storage()
    change = storage.get_change(change_id)

    if not change:
        return False

    storage.set_change_status(change_id, "approved")
    db.insert_audit(change_id, "approved", {"approved_by": user, "approved_via": "slack"})
    return True

async def reject_change(change_id: str, user: str) -> bool:
    """Reject a pending change"""
    storage = storage_manager.get_storage()
    change = storage.get_change(change_id)

    if not change:
        return False

    storage.set_change_status(change_id, "rejected")
    db.insert_audit(change_id, "rejected", {"rejected_by": user, "rejected_via": "slack"})
    return True
