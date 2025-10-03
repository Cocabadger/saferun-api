from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
import json, hmac, hashlib, os
from ..db import get_db, set_db, GIT_CHANGE_PREFIX

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
    """Handle Slack interactive button clicks"""

    # Get raw body and headers
    body = await request.body()
    headers = request.headers

    # Verify Slack signature
    timestamp = headers.get("X-Slack-Request-Timestamp", "")
    signature = headers.get("X-Slack-Signature", "")

    if not verify_slack_signature(body, timestamp, signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    # Parse form-encoded payload
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
    db = await get_db()
    key = f"{GIT_CHANGE_PREFIX}{change_id}"
    change = db.get(key)

    if not change:
        return False

    change["status"] = "approved"
    change["approved_by"] = user
    change["approved_via"] = "slack"
    await set_db(key, change)
    return True

async def reject_change(change_id: str, user: str) -> bool:
    """Reject a pending change"""
    db = await get_db()
    key = f"{GIT_CHANGE_PREFIX}{change_id}"
    change = db.get(key)

    if not change:
        return False

    change["status"] = "rejected"
    change["rejected_by"] = user
    change["rejected_via"] = "slack"
    await set_db(key, change)
    return True
