from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List
from .auth import verify_api_key
from .. import db_adapter as db

router = APIRouter(prefix="/v1/settings", tags=["settings"])

class NotificationSettings(BaseModel):
    slack_webhook_url: Optional[str] = None
    slack_bot_token: Optional[str] = None
    slack_channel: str = "#saferun-alerts"
    slack_enabled: bool = False
    email: Optional[str] = None
    email_enabled: bool = True
    webhook_url: Optional[str] = None
    webhook_secret: Optional[str] = None
    webhook_enabled: bool = False
    notification_channels: List[str] = Field(default_factory=lambda: ["email"])

class NotificationSettingsResponse(NotificationSettings):
    api_key: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

@router.get("/notifications", response_model=NotificationSettingsResponse)
async def get_notification_settings(api_key: str = Depends(verify_api_key)):
    """Get notification settings for the authenticated user."""
    settings = db.get_notification_settings(api_key)

    if not settings:
        # Return default settings if none exist
        return NotificationSettingsResponse(
            api_key=api_key,
            slack_enabled=False,
            email_enabled=True,
            webhook_enabled=False,
            notification_channels=["email"]
        )

    # Parse notification_channels JSON string
    import json
    if isinstance(settings.get("notification_channels"), str):
        settings["notification_channels"] = json.loads(settings["notification_channels"])

    # Convert integer booleans to actual booleans
    settings["slack_enabled"] = bool(settings.get("slack_enabled"))
    settings["email_enabled"] = bool(settings.get("email_enabled"))
    settings["webhook_enabled"] = bool(settings.get("webhook_enabled"))

    return NotificationSettingsResponse(**settings)

@router.put("/notifications")
async def update_notification_settings(
    settings: NotificationSettings,
    api_key: str = Depends(verify_api_key)
):
    """Update notification settings for the authenticated user."""

    # Validate at least one notification channel is enabled
    enabled_channels = []
    if settings.slack_enabled:
        enabled_channels.append("slack")
    if settings.email_enabled:
        enabled_channels.append("email")
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
        "provider": "saferun",
        "approve_url": "https://saferun-landing.vercel.app"
    }

    try:
        # Temporarily override Slack settings for this test
        import os
        original_token = os.environ.get("SLACK_BOT_TOKEN")
        original_webhook = os.environ.get("SLACK_WEBHOOK_URL")
        original_channel = os.environ.get("SLACK_CHANNEL")

        if settings.get("slack_bot_token"):
            os.environ["SLACK_BOT_TOKEN"] = settings["slack_bot_token"]
            os.environ["SLACK_CHANNEL"] = settings.get("slack_channel", "#saferun-alerts")
        elif settings.get("slack_webhook_url"):
            os.environ["SLACK_WEBHOOK_URL"] = settings["slack_webhook_url"]

        await notifier.send_slack(test_payload, "🧪 SafeRun Test Notification")

        # Restore original env vars
        if original_token:
            os.environ["SLACK_BOT_TOKEN"] = original_token
        elif "SLACK_BOT_TOKEN" in os.environ:
            del os.environ["SLACK_BOT_TOKEN"]

        if original_webhook:
            os.environ["SLACK_WEBHOOK_URL"] = original_webhook
        elif "SLACK_WEBHOOK_URL" in os.environ:
            del os.environ["SLACK_WEBHOOK_URL"]

        if original_channel:
            os.environ["SLACK_CHANNEL"] = original_channel
        elif "SLACK_CHANNEL" in os.environ:
            del os.environ["SLACK_CHANNEL"]

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
