from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List
from .auth import verify_api_key
from .. import db_adapter as db

router = APIRouter(prefix="/v1/settings", tags=["settings"])

def mask_secret(value: str) -> Optional[str]:
    """Mask secret values for security - only show if configured."""
    if not value:
        return None
    # Return masked indicator - never expose actual secrets via API
    if value.startswith("https://hooks.slack.com/"):
        return "https://hooks.slack.com/services/***"
    if value.startswith("xoxb-"):
        return "xoxb-***"
    if value.startswith("http://") or value.startswith("https://"):
        return "https://***"
    return "***"

class NotificationSettings(BaseModel):
    slack_webhook_url: Optional[str] = None
    slack_bot_token: Optional[str] = None
    slack_channel: str = "#saferun-alerts"
    slack_enabled: bool = False
    webhook_url: Optional[str] = None
    webhook_secret: Optional[str] = None
    webhook_enabled: bool = False
    notification_channels: List[str] = Field(default_factory=lambda: ["slack"])

class NotificationSettingsResponse(NotificationSettings):
    api_key: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

@router.get("/notifications", response_model=NotificationSettingsResponse)
async def get_notification_settings(api_key: str = Depends(verify_api_key)):
    """Get notification settings for the authenticated user (secrets masked for security)."""
    settings = db.get_notification_settings(api_key)

    if not settings:
        # Return default settings if none exist
        return NotificationSettingsResponse(
            api_key=api_key,
            slack_enabled=False,
            webhook_enabled=False,
            notification_channels=["slack"]
        )

    # ⚠️ SECURITY: Mask sensitive secrets before returning (uses module-level mask_secret)
    if settings.get("slack_webhook_url"):
        settings["slack_webhook_url"] = mask_secret(settings["slack_webhook_url"])
    
    if settings.get("slack_bot_token"):
        settings["slack_bot_token"] = mask_secret(settings["slack_bot_token"])
    
    if settings.get("webhook_url"):
        settings["webhook_url"] = mask_secret(settings["webhook_url"])  # ← ADD: mask generic webhook too
    
    if settings.get("webhook_secret"):
        settings["webhook_secret"] = mask_secret(settings["webhook_secret"])

    # Parse notification_channels JSON string
    import json
    if isinstance(settings.get("notification_channels"), str):
        settings["notification_channels"] = json.loads(settings["notification_channels"])

    # Convert integer booleans to actual booleans
    settings["slack_enabled"] = bool(settings.get("slack_enabled"))
    settings["webhook_enabled"] = bool(settings.get("webhook_enabled"))

    # Convert datetime objects to ISO strings
    if settings.get("created_at"):
        settings["created_at"] = db.iso_z(settings["created_at"])
    if settings.get("updated_at"):
        settings["updated_at"] = db.iso_z(settings["updated_at"])

    return NotificationSettingsResponse(**settings)

@router.put("/notifications")
async def update_notification_settings(
    settings: NotificationSettings,
    api_key: str = Depends(verify_api_key)
):
    """Update notification settings for the authenticated user."""

    # Auto-enable Slack if webhook/token provided
    if settings.slack_webhook_url or settings.slack_bot_token:
        settings.slack_enabled = True
    
    # Auto-enable generic webhook if URL provided
    if settings.webhook_url:
        settings.webhook_enabled = True

    # Validate at least one notification channel is enabled
    enabled_channels = []
    if settings.slack_enabled:
        enabled_channels.append("slack")
    if settings.webhook_enabled:
        enabled_channels.append("webhook")

    if not enabled_channels:
        raise HTTPException(
            status_code=400,
            detail="At least one notification channel must be enabled"
        )

    # Validate Slack settings if enabled
    if settings.slack_enabled:
        if not settings.slack_webhook_url and not settings.slack_bot_token:
            raise HTTPException(
                status_code=400,
                detail="Either slack_webhook_url or slack_bot_token is required when Slack is enabled"
            )

    # Validate webhook settings if enabled
    if settings.webhook_enabled and not settings.webhook_url:
        raise HTTPException(
            status_code=400,
            detail="webhook_url is required when webhook notifications are enabled"
        )

    # Save settings
    db.upsert_notification_settings(api_key, settings.dict())

    return {
        "success": True,
        "message": "Notification settings updated successfully",
        "enabled_channels": enabled_channels
    }

@router.post("/notifications/test/slack")
async def test_slack_notification(api_key: str = Depends(verify_api_key)):
    """Send a test notification to Slack to verify configuration."""
    settings = db.get_notification_settings(api_key)

    if not settings or not settings.get("slack_enabled"):
        raise HTTPException(
            status_code=400,
            detail="Slack notifications are not enabled"
        )

    # Send test notification
    from ..notify import notifier

    test_payload = {
        "change_id": "test-notification",
        "title": "🧪 Test Notification",
        "risk_score": 5.0,
        "provider": "saferun"
    }

    try:
        # Use user's settings from database (new architecture)
        await notifier.send_slack(test_payload, "🧪 SafeRun Test Notification", api_key=api_key)

        return {
            "success": True,
            "message": "Test notification sent to Slack successfully"
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to send test notification: {str(e)}"
        )

@router.delete("/notifications")
async def delete_notification_settings(api_key: str = Depends(verify_api_key)):
    """Reset notification settings to defaults."""
    db.delete_notification_settings(api_key)
    return {
        "success": True,
        "message": "Notification settings reset to defaults"
    }


@router.get("/github-app/check/{owner}/{repo}")
async def check_github_app_installation(
    owner: str,
    repo: str,
    api_key: str = Depends(verify_api_key)
):
    """
    Check if GitHub App is installed on a specific repository.
    
    Returns:
    - installed: bool - whether the app is installed
    - installation_id: int - the installation ID if installed
    - account: str - the account where app is installed
    """
    import json
    
    full_repo = f"{owner}/{repo}"
    
    # Check if we have an installation for this account
    installation = db.fetchone(
        "SELECT installation_id, account_login, repositories_json FROM github_installations WHERE account_login = %s",
        (owner,)
    )
    
    if not installation:
        return {
            "installed": False,
            "repo": full_repo,
            "message": "GitHub App not installed on this account"
        }
    
    # Check if this specific repo is in the installation
    repos_json = installation.get("repositories_json", "[]")
    try:
        repos = json.loads(repos_json) if repos_json else []
    except:
        repos = []
    
    # If repos is empty, it might mean "All repositories" was selected
    # In that case, we consider it installed
    is_installed = len(repos) == 0 or full_repo in repos
    
    return {
        "installed": is_installed,
        "repo": full_repo,
        "installation_id": installation.get("installation_id"),
        "account": installation.get("account_login"),
        "all_repos": len(repos) == 0,
        "message": "GitHub App is installed" if is_installed else "Repository not in installation scope"
    }


# ============================================
# Protected Branches Settings (Banking Grade)
# ============================================

class ProtectedBranchesRequest(BaseModel):
    branches: str = Field(..., description="Comma-separated branch patterns (e.g., 'main,master,release/*')")

class ProtectedBranchesResponse(BaseModel):
    protected_branches: str
    patterns: List[str]
    message: str


@router.get("/protected-branches", response_model=ProtectedBranchesResponse)
async def get_protected_branches(api_key: str = Depends(verify_api_key)):
    """Get protected branches configuration."""
    branches = db.get_protected_branches(api_key)
    patterns = [p.strip() for p in branches.split(",") if p.strip()]
    
    return ProtectedBranchesResponse(
        protected_branches=branches,
        patterns=patterns,
        message=f"Notifications enabled for {len(patterns)} branch pattern(s)"
    )


@router.put("/protected-branches", response_model=ProtectedBranchesResponse)
async def update_protected_branches(
    request: ProtectedBranchesRequest,
    api_key: str = Depends(verify_api_key)
):
    """
    Update protected branches configuration.
    
    Supports wildcards:
    - main, master (exact match)
    - release/* (matches release/v1.0, release/2024-01)
    - hotfix-* (matches hotfix-123, hotfix-urgent)
    """
    # Validate: at least one branch required
    branches = request.branches.strip()
    if not branches:
        raise HTTPException(status_code=400, detail="At least one branch pattern is required")
    
    # Parse and validate patterns
    patterns = [p.strip() for p in branches.split(",") if p.strip()]
    if not patterns:
        raise HTTPException(status_code=400, detail="At least one valid branch pattern is required")
    
    # Get old value for audit
    old_value = db.get_protected_branches(api_key)
    
    # Update with audit log (Banking Grade)
    db.update_protected_branches(api_key, branches, old_value)
    
    return ProtectedBranchesResponse(
        protected_branches=branches,
        patterns=patterns,
        message=f"Protected branches updated. Notifications now enabled for {len(patterns)} pattern(s)"
    )
