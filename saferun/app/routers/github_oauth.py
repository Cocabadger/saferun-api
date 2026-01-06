"""
GitHub App OAuth Router for SafeRun
Handles GitHub App installation callback and unified setup status.

Flow:
1. User starts setup via CLI → gets state UUID
2. User installs GitHub App on github.com
3. GitHub redirects to GET /auth/github/callback?installation_id=xxx&state=xxx
4. Backend links installation to user's api_key via state
5. CLI polls GET /auth/setup/status to detect completion
"""
import os
import logging
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from .. import db_adapter as db

router = APIRouter(prefix="/auth", tags=["github-oauth"])
logger = logging.getLogger(__name__)

# GitHub App configuration
GITHUB_APP_NAME = os.getenv("GITHUB_APP_NAME", "saferun-ai")
GITHUB_APP_URL = f"https://github.com/apps/{GITHUB_APP_NAME}/installations/new"


@router.get("/github/callback")
async def github_app_callback(
    installation_id: int = Query(None, description="GitHub App installation ID"),
    setup_action: str = Query(None, description="GitHub setup action (install/update)"),
    state: str = Query(None, description="State UUID from setup session"),
    error: str = Query(None, description="Error from GitHub")
):
    """
    Handle GitHub App installation callback.
    
    GitHub redirects here after user installs the app.
    Links installation_id to user's api_key via state parameter.
    
    SECURITY: Uses atomic transaction to prevent race conditions.
    """
    # Handle errors from GitHub
    if error:
        logger.warning(f"GitHub App callback error: {error}")
        return HTMLResponse(
            content=_error_page(f"GitHub App installation failed: {error}"),
            status_code=400
        )
    
    if not installation_id:
        return HTMLResponse(
            content=_error_page("Missing installation_id parameter"),
            status_code=400
        )
    
    if not state:
        # No state = user installed directly from GitHub, not via CLI
        # Still record the installation, but can't link to api_key
        logger.info(f"GitHub App installed without state (direct install): installation_id={installation_id}")
        return HTMLResponse(
            content=_success_page_no_state(installation_id),
            status_code=200
        )
    
    # Atomic completion: link installation to api_key
    try:
        api_key, error_message = db.complete_github_installation(state, installation_id)
        
        if error_message:
            logger.warning(f"GitHub installation completion failed: {error_message}")
            return HTMLResponse(
                content=_error_page(error_message),
                status_code=400
            )
        
        logger.info(f"GitHub App installation linked: installation_id={installation_id}, api_key={api_key[:10]}...")
        
    except Exception as e:
        logger.error(f"Failed to complete GitHub installation: {e}")
        return HTMLResponse(
            content=_error_page("Failed to save GitHub App installation. Please try again."),
            status_code=500
        )
    
    return HTMLResponse(content=_success_page(installation_id))


@router.get("/github/status")
async def github_installation_status(
    request: Request,
    api_key: str = Query(None, description="SafeRun API key"),
    validate: bool = Query(False, description="Validate installation is still active via GitHub API")
):
    """
    Check if GitHub App is installed for an API key.
    
    If validate=true, will verify installation is still active via GitHub API.
    """
    header_key = request.headers.get("X-API-Key")
    key = header_key or api_key
    
    if not key:
        raise HTTPException(status_code=401, detail="API key required")
    
    key_data = db.get_api_key(key)
    if not key_data:
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    installation_id = key_data.get("github_installation_id")
    
    if not installation_id:
        return {"installed": False}
    
    # Get installation details from github_installations table
    installation = db.fetchone(
        "SELECT account_login, repositories_json FROM github_installations WHERE installation_id = %s",
        (installation_id,)
    )
    
    result = {
        "installed": True,
        "installation_id": installation_id,
        "account_login": installation.get("account_login") if installation else None,
        "valid": True  # Assume valid unless we check
    }
    
    # Optionally validate installation is still active
    if validate:
        try:
            from ..services.github import get_github_app_installation_token
            # If we can get a token, the installation is still valid
            token = get_github_app_installation_token(installation_id)
            if not token:
                result["valid"] = False
                result["installed"] = False
                result["error"] = "installation_removed"
                logger.warning(f"GitHub App installation {installation_id} no longer valid")
        except Exception as e:
            logger.warning(f"Failed to validate GitHub installation: {e}")
            result["valid"] = False
            result["installed"] = False
            result["error"] = str(e)
    
    return result


@router.get("/setup/status")
async def unified_setup_status(
    request: Request,
    state: str = Query(None, description="Setup session state UUID"),
    api_key: str = Query(None, description="SafeRun API key (fallback)")
):
    """
    Get unified setup status for CLI polling.
    
    Returns status of all configured providers:
    - slack: Whether Slack OAuth completed
    - github: Whether GitHub App was installed
    - ready: True when ALL required providers are connected
    
    CLI should poll this endpoint until ready=true.
    """
    # Get state from query or api_key
    header_key = request.headers.get("X-API-Key")
    key = header_key or api_key
    
    # If state provided, check setup session directly
    if state:
        session = db.get_setup_session_status(state)
        if not session:
            raise HTTPException(status_code=404, detail="Setup session not found or expired")
        
        slack_connected = session.get("is_slack_connected", False)
        github_installed = session.get("is_github_installed", False)
        
        return {
            "state": state,
            "slack": slack_connected,
            "github": github_installed,
            "ready": slack_connected and github_installed,
            "expires_at": session.get("expires_at").isoformat() if session.get("expires_at") else None
        }
    
    # Fallback: check by api_key (for existing installations)
    if not key:
        raise HTTPException(status_code=401, detail="state or API key required")
    
    key_data = db.get_api_key(key)
    if not key_data:
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    # Check Slack installation
    slack_installation = db.get_slack_installation(key)
    slack_connected = slack_installation is not None
    
    # Check GitHub installation
    github_installation_id = key_data.get("github_installation_id")
    github_installed = github_installation_id is not None
    
    return {
        "api_key": key[:10] + "...",
        "slack": slack_connected,
        "slack_team": slack_installation.get("team_name") if slack_installation else None,
        "github": github_installed,
        "github_installation_id": github_installation_id,
        "ready": slack_connected and github_installed
    }


def _success_page(installation_id: int) -> str:
    """Generate success HTML page for GitHub App installation."""
    return f"""
<!DOCTYPE html>
<html>
<head>
    <title>SafeRun - GitHub App Installed</title>
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
        .installation-id {{
            color: #4ade80;
            font-family: monospace;
            background: rgba(74,222,128,0.1);
            padding: 4px 8px;
            border-radius: 4px;
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
        <h1>GitHub App Installed!</h1>
        <p>
            SafeRun GitHub App is now protecting your repositories.
            <br><br>
            Installation ID: <span class="installation-id">{installation_id}</span>
        </p>
        <p class="close-hint">You can close this window and return to your terminal.</p>
    </div>
</body>
</html>
"""


def _success_page_no_state(installation_id: int) -> str:
    """Success page when installed without state (direct from GitHub)."""
    return f"""
<!DOCTYPE html>
<html>
<head>
    <title>SafeRun - GitHub App Installed</title>
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
            max-width: 450px;
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
        .installation-id {{
            color: #4ade80;
            font-family: monospace;
            background: rgba(74,222,128,0.1);
            padding: 4px 8px;
            border-radius: 4px;
        }}
        .warning {{
            color: #fbbf24;
            background: rgba(251,191,36,0.1);
            padding: 12px;
            border-radius: 8px;
            font-size: 14px;
        }}
        code {{
            background: rgba(255,255,255,0.1);
            padding: 2px 6px;
            border-radius: 4px;
            font-family: monospace;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="success-icon">✅</div>
        <h1>GitHub App Installed!</h1>
        <p>
            Installation ID: <span class="installation-id">{installation_id}</span>
        </p>
        <p class="warning">
            ⚠️ To link this installation to your SafeRun account, 
            run <code>saferun setup</code> in your terminal.
        </p>
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
    <title>SafeRun - Installation Failed</title>
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
        <h1>Installation Failed</h1>
        <p class="error-message">{error_message}</p>
        <p>
            Please <a href="javascript:history.back()">go back</a> and try again,
            or run <code>saferun setup</code> to restart.
        </p>
    </div>
</body>
</html>
"""
