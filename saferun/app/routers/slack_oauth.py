"""
Slack OAuth Router for SafeRun
Handles "Add to Slack" OAuth flow with CSRF protection via state parameter.

Flow:
1. CLI/Landing → GET /auth/slack/start?session=xxx (encrypted session token)
2. Backend decrypts session, generates state (UUID), stores in DB, redirects to Slack
3. User clicks "Allow" in Slack
4. Slack → GET /auth/slack/callback?code=xxx&state=xxx
5. Backend verifies state, exchanges code for bot_token, stores encrypted in DB
"""
import os
import uuid
import json
import base64
import httpx
import logging
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, HTMLResponse
from .. import db_adapter as db
from .. import crypto

router = APIRouter(prefix="/auth/slack", tags=["slack-oauth"])
logger = logging.getLogger(__name__)

# Slack OAuth configuration
SLACK_CLIENT_ID = os.getenv("SLACK_CLIENT_ID")
SLACK_CLIENT_SECRET = os.getenv("SLACK_CLIENT_SECRET")
SLACK_REDIRECT_URI = os.getenv(
    "SLACK_REDIRECT_URI",
    "https://saferun-api.up.railway.app/auth/slack/callback"  # No /api prefix!
)

# Scopes needed for SafeRun:
# - chat:write: Send messages to channels (bot must be invited to channel)
# Channel detection: via member_joined_channel event when bot is /invite'd
SLACK_SCOPES = "chat:write"


from fastapi import Header
from pydantic import BaseModel

class SlackOAuthUrlResponse(BaseModel):
    url: str
    state: str
    expires_in: int = 600  # 10 minutes


@router.post("/session")
async def create_slack_oauth_url(
    api_key: str = Header(..., alias="X-API-Key", description="SafeRun API key")
):
    """
    Generate Slack OAuth URL with short state token.
    
    API key is passed in header (secure), returned URL has short UUID state.
    State is stored in DB and links back to api_key.
    """
    if not SLACK_CLIENT_ID:
        raise HTTPException(
            status_code=503,
            detail="Slack OAuth not configured"
        )
    
    # Verify API key exists
    key_data = db.get_api_key(api_key)
    if not key_data:
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    # Generate short state UUID (stored in DB, links to api_key)
    # TTL = 30 minutes to allow time for unified setup (Slack + GitHub)
    state = str(uuid.uuid4())
    db.store_oauth_state(state, api_key, expires_minutes=30)
    
    base_url = os.getenv("SAFERUN_API_URL", "https://saferun-api.up.railway.app")
    
    return SlackOAuthUrlResponse(
        url=f"{base_url}/auth/slack/start?state={state}",
        state=state,
        expires_in=1800  # 30 minutes
    )


@router.get("/start")
async def slack_oauth_start_with_state(
    state: str = Query(..., description="State UUID from /session endpoint")
):
    """
    Start Slack OAuth flow using state from DB.
    
    State was created by POST /session and links to user's api_key.
    """
    if not SLACK_CLIENT_ID:
        raise HTTPException(status_code=503, detail="Slack OAuth not configured")
    
    # Verify state exists and is valid
    oauth_state = db.verify_oauth_state(state)
    if not oauth_state:
        raise HTTPException(status_code=401, detail="Invalid or expired state")
    
    # Build Slack OAuth URL (reuse same state)
    slack_auth_url = (
        "https://slack.com/oauth/v2/authorize"
        f"?client_id={SLACK_CLIENT_ID}"
        f"&scope={SLACK_SCOPES}"
        f"&redirect_uri={SLACK_REDIRECT_URI}"
        f"&state={state}"
    )
    
    logger.info(f"Starting Slack OAuth with state={state[:8]}...")
    
    return RedirectResponse(url=slack_auth_url)


# Legacy endpoint - REMOVED for security (api_key should not be in URL)
# Use POST /auth/slack/session instead


@router.get("/callback")
async def slack_oauth_callback(
    code: str = Query(None, description="Authorization code from Slack"),
    state: str = Query(None, description="CSRF state parameter"),
    error: str = Query(None, description="Error from Slack")
):
    """
    Handle Slack OAuth callback.
    
    SECURITY: Uses atomic transaction to prevent race conditions.
    State verification + token storage happen in single DB transaction.
    """
    # Handle errors from Slack
    if error:
        logger.warning(f"Slack OAuth error: {error}")
        return HTMLResponse(
            content=_error_page(f"Slack authorization failed: {error}"),
            status_code=400
        )
    
    if not code or not state:
        return HTMLResponse(
            content=_error_page("Missing code or state parameter"),
            status_code=400
        )
    
    if not SLACK_CLIENT_ID or not SLACK_CLIENT_SECRET:
        return HTMLResponse(
            content=_error_page("Slack OAuth not configured on server"),
            status_code=503
        )
    
    # Exchange code for access token FIRST (before consuming state)
    # This way if Slack rejects the code, we haven't consumed the state yet
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                "https://slack.com/api/oauth.v2.access",
                data={
                    "client_id": SLACK_CLIENT_ID,
                    "client_secret": SLACK_CLIENT_SECRET,
                    "code": code,
                    "redirect_uri": SLACK_REDIRECT_URI
                }
            )
            
            data = response.json()
            
            if not data.get("ok"):
                error_msg = data.get("error", "Unknown error")
                logger.error(f"Slack OAuth token exchange failed: {error_msg}")
                # Map known errors to user-friendly messages
                user_message = {
                    "invalid_code": "Authorization code expired. Please try again.",
                    "code_already_used": "Authorization already completed. Please try again.",
                    "invalid_client_id": "Server configuration error. Please contact support.",
                }.get(error_msg, "Failed to complete authorization. Please try again.")
                return HTMLResponse(
                    content=_error_page(user_message),
                    status_code=400
                )
            
            # Extract token and team info
            access_token = data.get("access_token")  # Bot token (xoxb-...)
            team_info = data.get("team", {})
            team_id = team_info.get("id")
            team_name = team_info.get("name")
            bot_user_id = data.get("bot_user_id")
            
            # Get channel from incoming_webhook if provided during OAuth
            incoming_webhook = data.get("incoming_webhook", {})
            channel_id = incoming_webhook.get("channel_id")
            channel_name = incoming_webhook.get("channel")
            
            logger.info(f"Slack OAuth success: team={team_name} ({team_id})")
            
    except httpx.TimeoutException:
        logger.error("Timeout during Slack OAuth token exchange")
        return HTMLResponse(
            content=_error_page("Slack is responding slowly. Please try again."),
            status_code=504
        )
    except httpx.HTTPError as e:
        logger.error(f"HTTP error during Slack OAuth: {e}")
        return HTMLResponse(
            content=_error_page("Network error while contacting Slack. Please try again."),
            status_code=502
        )
    
    # SECURITY FIX: Atomic state consumption + installation storage
    # This prevents race conditions where two requests could use the same state
    try:
        api_key, error_message = db.complete_slack_oauth(
            state=state,
            team_id=team_id,
            team_name=team_name,
            bot_token=access_token,
            bot_user_id=bot_user_id,
            channel_id=channel_id
        )
        
        if error_message:
            logger.warning(f"OAuth completion failed: {error_message}")
            return HTMLResponse(
                content=_error_page(error_message),
                status_code=400 if "expired" in error_message.lower() else 409
            )
        
        logger.info(f"Slack installation stored atomically for api_key={api_key[:10]}..., team={team_name}")
        
    except Exception as e:
        logger.error(f"Failed to complete Slack OAuth: {e}")
        return HTMLResponse(
            content=_error_page("Failed to save Slack connection. Please try again."),
            status_code=500
        )
    
    # Success page
    return HTMLResponse(content=_success_page(team_name, channel_name))


@router.get("/status")
async def slack_oauth_status(
    request: Request,
    api_key: str = Query(None, description="SafeRun API key"),
    validate: bool = Query(False, description="Validate token is still active")
):
    """
    Check if Slack is connected for an API key.
    
    Used by CLI polling to detect when OAuth flow completes.
    API key can be provided via query param or X-API-Key header.
    
    If validate=true, will test the token against Slack API.
    """
    # Get API key from header or query param
    header_key = request.headers.get("X-API-Key")
    key = header_key or api_key
    
    if not key:
        raise HTTPException(status_code=401, detail="API key required")
    
    key_data = db.get_api_key(key)
    if not key_data:
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    installation = db.get_slack_installation(key)
    
    if installation:
        result = {
            "connected": True,
            "team_name": installation.get("team_name"),
            "team_id": installation.get("team_id"),
            "channel_id": installation.get("channel_id"),
            "valid": True  # Assume valid unless we check
        }
        
        # Optionally validate token is still active
        if validate and installation.get("bot_token"):
            import httpx
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.post(
                        "https://slack.com/api/auth.test",
                        headers={"Authorization": f"Bearer {installation.get('bot_token')}"}
                    )
                    data = resp.json()
                    if not data.get("ok"):
                        # Token revoked or invalid
                        result["valid"] = False
                        result["connected"] = False
                        result["error"] = data.get("error", "token_invalid")
                        logger.warning(f"Slack token invalid for team {installation.get('team_name')}: {data.get('error')}")
            except Exception as e:
                logger.warning(f"Failed to validate Slack token: {e}")
                # Don't mark as invalid on network error
        
        return result
    else:
        return {
            "connected": False
        }


def _success_page(team_name: str, channel_name: str = None) -> str:
    """Generate success HTML page."""
    channel_info = f" to #{channel_name}" if channel_name else ""
    return f"""
<!DOCTYPE html>
<html>
<head>
    <title>SafeRun - Slack Connected</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            margin: 0;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: white;
        }}
        .container {{
            text-align: center;
            padding: 40px;
            background: rgba(255,255,255,0.1);
            border-radius: 16px;
            backdrop-filter: blur(10px);
            max-width: 400px;
        }}
        .success-icon {{
            font-size: 64px;
            margin-bottom: 20px;
        }}
        h1 {{
            margin: 0 0 16px 0;
            font-size: 24px;
        }}
        p {{
            margin: 0 0 24px 0;
            color: rgba(255,255,255,0.8);
            line-height: 1.5;
        }}
        .team-name {{
            color: #4ade80;
            font-weight: 600;
        }}
        .close-hint {{
            font-size: 14px;
            color: rgba(255,255,255,0.5);
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="success-icon">✅</div>
        <h1>Slack Connected!</h1>
        <p>
            SafeRun is now connected to <span class="team-name">{team_name}</span>{channel_info}.
            You'll receive approval notifications directly in Slack.
        </p>
        <p class="close-hint">You can close this window and return to your terminal.</p>
    </div>
</body>
</html>
"""


def _error_page(error_message: str) -> str:
    """Generate error HTML page."""
    return f"""
<!DOCTYPE html>
<html>
<head>
    <title>SafeRun - Connection Failed</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            margin: 0;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: white;
        }}
        .container {{
            text-align: center;
            padding: 40px;
            background: rgba(255,255,255,0.1);
            border-radius: 16px;
            backdrop-filter: blur(10px);
            max-width: 400px;
        }}
        .error-icon {{
            font-size: 64px;
            margin-bottom: 20px;
        }}
        h1 {{
            margin: 0 0 16px 0;
            font-size: 24px;
        }}
        p {{
            margin: 0 0 24px 0;
            color: rgba(255,255,255,0.8);
            line-height: 1.5;
        }}
        .error-message {{
            color: #f87171;
            background: rgba(248,113,113,0.1);
            padding: 12px;
            border-radius: 8px;
            font-family: monospace;
            font-size: 14px;
        }}
        a {{
            color: #60a5fa;
            text-decoration: none;
        }}
        a:hover {{
            text-decoration: underline;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="error-icon">❌</div>
        <h1>Connection Failed</h1>
        <p class="error-message">{error_message}</p>
        <p>
            Please <a href="javascript:history.back()">go back</a> and try again,
            or contact support if the issue persists.
        </p>
    </div>
</body>
</html>
"""
