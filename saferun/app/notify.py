import os, json, hmac, hashlib, asyncio
from typing import Dict, Any, Optional
import httpx

TIMEOUT = float(os.getenv("NOTIFY_TIMEOUT_MS", "2000")) / 1000.0
RETRY = int(os.getenv("NOTIFY_RETRY", "1"))
SLACK_URL = os.getenv("SLACK_WEBHOOK_URL")
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_CHANNEL = os.getenv("SLACK_CHANNEL", "#saferun-alerts")
WH_URL = os.getenv("GENERIC_WEBHOOK_URL")
WH_SECRET = os.getenv("GENERIC_WEBHOOK_SECRET")
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "0") or 0)
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
SMTP_FROM = os.getenv("SMTP_FROM")
SMTP_TO = os.getenv("SMTP_TO")

class Notifier:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=TIMEOUT)

    async def _retry(self, coro):
        last = None
        for attempt in range(RETRY + 1):
            try:
                result = await coro()
                return result
            except Exception as e:
                last = e
                print(f"[NOTIFY ERROR] Attempt {attempt + 1}/{RETRY + 1} failed: {e}")
                await asyncio.sleep(0.3 * (2 ** attempt))
        # Log final failure
        if last:
            print(f"[NOTIFY FAILED] All retries exhausted: {last}")
        return None

    async def send_slack(self, payload: Dict[str, Any], text: str, api_key: str = None) -> None:
        # Get user-specific settings if api_key provided
        user_settings = None
        if api_key:
            from . import db_adapter as db
            user_settings = db.get_notification_settings(api_key)

        # Use user settings if available and enabled, otherwise fall back to global env vars
        if user_settings and user_settings.get("slack_enabled"):
            bot_token = user_settings.get("slack_bot_token")
            webhook_url = user_settings.get("slack_webhook_url")
            channel = user_settings.get("slack_channel", "#saferun-alerts")

            if bot_token:
                await self._send_slack_bot(payload, text, bot_token, channel)
            elif webhook_url:
                await self._send_slack_webhook(payload, text, webhook_url)
        elif SLACK_BOT_TOKEN or SLACK_URL:
            # Fallback to global env vars
            if SLACK_BOT_TOKEN:
                await self._send_slack_bot(payload, text, SLACK_BOT_TOKEN, SLACK_CHANNEL)
            elif SLACK_URL:
                await self._send_slack_webhook(payload, text, SLACK_URL)

    async def _send_slack_bot(self, payload: Dict[str, Any], text: str, bot_token: str, channel: str) -> None:
        """Send via Slack Bot API with interactive buttons"""
        change_id = payload.get("change_id")
        approve_url = payload.get("approve_url")
        risk_score = payload.get("risk_score", 0.0)
        title = payload.get("title", "Unknown operation")
        provider = payload.get("provider", "unknown")

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "🛡️ SafeRun Approval Required"
                }
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Operation:*\n{title}"},
                    {"type": "mrkdwn", "text": f"*Risk Score:*\n{risk_score:.1f}/10"},
                    {"type": "mrkdwn", "text": f"*Provider:*\n{provider}"},
                    {"type": "mrkdwn", "text": f"*Change ID:*\n`{change_id}`"}
                ]
            }
        ]

        # Add approve URL for web view
        if approve_url:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"<{approve_url}|🌐 View in Dashboard>"
                }
            })

        # Add REAL interactive buttons (value contains change_id for callback)
        if change_id:
            blocks.append({
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "✅ Approve"},
                        "style": "primary",
                        "action_id": "approve_change",
                        "value": change_id
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "❌ Reject"},
                        "style": "danger",
                        "action_id": "reject_change",
                        "value": change_id
                    }
                ]
            })

        body = {
            "channel": channel,
            "text": text,  # Fallback
            "blocks": blocks
        }

        headers = {"Authorization": f"Bearer {bot_token}"}

        async def do():
            return await self.client.post(
                "https://slack.com/api/chat.postMessage",
                json=body,
                headers=headers
            )
        await self._retry(do)

    async def _send_slack_webhook(self, payload: Dict[str, Any], text: str, webhook_url: str) -> None:
        """Fallback: Send via Incoming Webhook (simple, no interactivity)"""
        change_id = payload.get("change_id")
        approve_url = payload.get("approve_url")
        risk_score = payload.get("risk_score", 0.0)
        title = payload.get("title", "Unknown operation")

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "🛡️ SafeRun Approval Required"
                }
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Operation:*\n{title}"},
                    {"type": "mrkdwn", "text": f"*Risk Score:*\n{risk_score:.1f}/10"}
                ]
            }
        ]

        # Add approve URL if available
        if approve_url:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Approval URL:*\n<{approve_url}|View Details>"
                }
            })

        # Webhook only supports URL buttons (not interactive)
        if change_id:
            api_base = os.getenv("APP_BASE_URL", "http://localhost:8500")
            blocks.append({
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "✅ Approve"},
                        "style": "primary",
                        "url": f"{api_base}/approvals/{change_id}",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "❌ Reject"},
                        "style": "danger",
                        "url": f"{api_base}/approvals/{change_id}",
                    }
                ]
            })

        body = {
            "text": text,
            "blocks": blocks
        }

        async def do(): return await self.client.post(webhook_url, json=body)
        await self._retry(do)

    async def send_custom_webhook(self, webhook_url: str, payload: Dict[str, Any]) -> None:
        """Send webhook to custom URL provided by user"""
        if not webhook_url: return
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        async def do(): return await self.client.post(webhook_url, content=body, headers=headers)
        await self._retry(do)

    async def send_webhook(self, payload: Dict[str, Any], api_key: str = None) -> None:
        # Get user-specific webhook settings if api_key provided
        user_webhook_url = None
        user_webhook_secret = None
        if api_key:
            from . import db_adapter as db
            user_settings = db.get_notification_settings(api_key)
            if user_settings and user_settings.get("webhook_enabled"):
                user_webhook_url = user_settings.get("webhook_url")
                user_webhook_secret = user_settings.get("webhook_secret")

        # Use user webhook if available, otherwise fall back to global webhook
        webhook_url = user_webhook_url or WH_URL
        webhook_secret = user_webhook_secret or WH_SECRET

        if not webhook_url:
            return

        body = json.dumps(payload).encode("utf-8")
        headers = {}
        if webhook_secret:
            sig = hmac.new(webhook_secret.encode(), body, hashlib.sha256).hexdigest()
            headers["X-Signature"] = sig
        async def do(): return await self.client.post(webhook_url, content=body, headers=headers)
        await self._retry(do)

    async def send_email(self, payload: Dict[str, Any], subject: str, api_key: str = None) -> None:
        # Get user-specific email settings if api_key provided
        user_email = None
        if api_key:
            from . import db_adapter as db
            user_settings = db.get_notification_settings(api_key)
            if user_settings and user_settings.get("email_enabled"):
                user_email = user_settings.get("email")

        # Use user email if available, otherwise fall back to global SMTP settings
        if user_email and SMTP_HOST and SMTP_FROM:
            # Send to user's email
            to_email = user_email
        elif SMTP_HOST and SMTP_FROM and SMTP_TO:
            # Fallback to global config
            to_email = SMTP_TO
        else:
            return

        try:
            import aiosmtplib
        except Exception:
            return
        msg = f"Subject: {subject}\nFrom: {SMTP_FROM}\nTo: {to_email}\n\n{json.dumps(payload, indent=2)[:9000]}"
        async def do():
            return await aiosmtplib.send(
                msg, hostname=SMTP_HOST, port=SMTP_PORT or 587,
                username=SMTP_USER, password=SMTP_PASS, start_tls=True,
                sender=SMTP_FROM, recipients=[to_email]
            )
        await self._retry(do)

    async def publish(self, event: str, change: Dict[str, Any], extras: Optional[Dict[str, Any]] = None, api_key: str = None) -> None:
        payload = {
            "event": event,
            "change_id": change.get("change_id"),
            "page_id": change.get("page_id"),
            "target_id": change.get("target_id"),
            "provider": change.get("provider"),
            "title": change.get("title"),
            "status": change.get("status"),
            "risk_score": change.get("risk_score", 0.0),
            "requires_approval": bool(change.get("requires_approval")),
            "approve_url": (extras or {}).get("approve_url"),
            "revert_token": (extras or {}).get("revert_token"),
            "ts": change.get("ts") or change.get("created_at"),
            "meta": (extras or {}).get("meta", {}),
        }

        # Add user-specific webhook if provided
        webhook_url = change.get("webhook_url")

        text_map = {
            "dry_run": ":rotating_light: [SafeRun] High-risk DRY-RUN → approval needed",
            "applied": ":white_check_mark: [SafeRun] Applied",
            "reverted": ":rewind: [SafeRun] Reverted",
            "expired": ":hourglass_flowing_sand: [SafeRun] Expired",
        }
        text = text_map.get(event, f"[SafeRun] {event}")

        # Fan-out concurrently with api_key for user-specific settings
        tasks = [
            self.send_slack(payload, text, api_key),
            self.send_webhook(payload, api_key),
            self.send_email(payload, subject=text.replace(":", ""), api_key=api_key)
        ]

        # Add custom webhook if URL provided
        if webhook_url:
            tasks.append(self.send_custom_webhook(webhook_url, payload))

        await asyncio.gather(*tasks, return_exceptions=True)

notifier = Notifier()
