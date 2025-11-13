import os, json, hmac, hashlib, asyncio, logging
from typing import Dict, Any, Optional
from datetime import datetime, timezone
import httpx

logger = logging.getLogger(__name__)

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
                logger.error(f"[NOTIFY ERROR] Attempt {attempt + 1}/{RETRY + 1} failed: {e}")
                await asyncio.sleep(0.3 * (2 ** attempt))
        # Log final failure
        if last:
            logger.error(f"[NOTIFY FAILED] All retries exhausted: {last}")
        return None

    async def send_slack(self, payload: Dict[str, Any], text: str, api_key: str = None, event_type: str = "dry_run") -> None:
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
                await self._send_slack_bot(payload, text, bot_token, channel, event_type)
            elif webhook_url:
                await self._send_slack_webhook(payload, text, webhook_url, event_type)
        elif SLACK_BOT_TOKEN or SLACK_URL:
            # Fallback to global env vars
            if SLACK_BOT_TOKEN:
                await self._send_slack_bot(payload, text, SLACK_BOT_TOKEN, SLACK_CHANNEL, event_type)
            elif SLACK_URL:
                await self._send_slack_webhook(payload, text, SLACK_URL, event_type)

    async def _send_slack_bot(self, payload: Dict[str, Any], text: str, bot_token: str, channel: str, event_type: str = "dry_run") -> None:
        """Send via Slack Bot API with interactive buttons"""
        change_id = payload.get("change_id")
        approve_url = payload.get("approve_url")
        revert_url = payload.get("revert_url")
        revert_window_hours = payload.get("revert_window_hours")
        risk_score = payload.get("risk_score", 0.0)
        title = payload.get("title", "Unknown operation")
        provider = payload.get("provider", "unknown")
        target_id = payload.get("target_id", "")
        
        # Determine operation type and repository from metadata/payload
        operation_display = title  # Default to title
        repository_name = title
        
        # For GitHub, parse operation type from metadata (stored in change_data or extras)
        if provider == "github":
            # Try to get metadata from change record first, then from extras
            metadata = payload.get("metadata", {})
            if not metadata:
                extras = payload.get("extras", {})
                metadata = extras.get("metadata", {})
            
            # Parse metadata if it's a JSON string from storage
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except Exception:
                    metadata = {}
            
            object_type = metadata.get("object")
            operation_type = metadata.get("operation_type")
            item_type = metadata.get("type")  # For bulk operations
            
            # Extract repo name from target_id (format: owner/repo or owner/repo#branch)
            if target_id:
                if "#" in target_id:
                    repository_name = target_id.split("#")[0]
                elif "/" in target_id:
                    repository_name = target_id
            
            # Determine operation display text based on operation_type or object_type
            # Check full operation_type first (github_force_push, github_pr_merge, etc.)
            if operation_type == "delete_repo" or operation_type == "github_repo_delete":
                operation_display = "Repository DELETE (PERMANENT)"
            elif operation_type == "github_force_push" or operation_type == "force_push":
                branch_name = metadata.get("name") or metadata.get("branch", "branch")
                operation_display = f"Force Push: {branch_name}"
            elif operation_type == "github_pr_merge" or object_type == "merge":
                # Check if merging to main/default
                if metadata.get("isTargetDefault"):
                    operation_display = "Merge to Main Branch"
                else:
                    target_branch = metadata.get("target_branch", "branch")
                    operation_display = f"Merge to {target_branch}"
            elif operation_type == "github_branch_delete" or (object_type == "branch" and operation_type != "github_force_push"):
                if metadata.get("isDefault"):
                    operation_display = "Delete Main Branch"
                else:
                    branch_name = metadata.get("name") or metadata.get("branch", "branch")
                    operation_display = f"Delete Branch: {branch_name}"
            elif object_type == "repository":
                # Check operation_type for archive vs unarchive
                if operation_type == "github_repo_unarchive":
                    operation_display = "Unarchive Repository"
                elif operation_type == "github_repo_archive":
                    operation_display = "Archive Repository"
                else:
                    operation_display = "Repository Operation"
            elif item_type == "bulk_pr":
                # Bulk PR operations
                records_affected = metadata.get("records_affected", 0)
                operation_display = f"Close {records_affected} Pull Requests"
            else:
                operation_display = f"GitHub Operation: {title}"

        # Provider emoji mapping
        provider_emoji = {
            "github": "🐙",
            "notion": "📝",
            "airtable": "🗂️"
        }.get(provider.lower(), "🔧")

        # Different header based on event type
        if event_type == "executed_with_revert":
            header_text = "✅ Action Executed"
        elif event_type == "failed":
            header_text = "❌ Operation Failed"
        else:
            header_text = "🛡️ SafeRun Approval Required"

        # Build fields based on provider
        fields = []
        if provider == "github" and repository_name != operation_display:
            # For GitHub, show Provider, Repository, Operation separately
            fields.extend([
                {"type": "mrkdwn", "text": f"*Provider:*\n{provider_emoji} {provider.capitalize()}"},
                {"type": "mrkdwn", "text": f"*Repository:*\n{repository_name}"},
                {"type": "mrkdwn", "text": f"*Operation:*\n{operation_display}"},
                {"type": "mrkdwn", "text": f"*Risk Score:*\n{risk_score * 10:.1f}/10"}  # risk_score stored as 0-1, display as 0-10
            ])
        else:
            # For other providers or fallback, use original layout
            fields.extend([
                {"type": "mrkdwn", "text": f"*Provider:*\n{provider_emoji} {provider.capitalize()}"},
                {"type": "mrkdwn", "text": f"*Operation:*\n{operation_display}"},
                {"type": "mrkdwn", "text": f"*Risk Score:*\n{risk_score * 10:.1f}/10"},  # risk_score stored as 0-1, display as 0-10
                {"type": "mrkdwn", "text": f"*Change ID:*\n`{change_id}`"}
            ])

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": header_text
                }
            },
            {
                "type": "section",
                "fields": fields
            }
        ]

        # Add approve URL for web view (only for dry_run events, not approval_required)
        if approve_url and event_type == "dry_run":
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"<{approve_url}|🌐 View in Dashboard>"
                }
            })
        
        # Add expiration info for approval-required operations
        if event_type in ("dry_run", "approval_required"):
            expires_at = payload.get("expires_at")
            if expires_at:
                # Parse expires_at timestamp
                if isinstance(expires_at, str):
                    try:
                        expires_dt = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
                    except ValueError:
                        expires_dt = None
                elif hasattr(expires_at, 'timestamp'):
                    expires_dt = expires_at
                else:
                    expires_dt = None
                
                if expires_dt:
                    # Calculate remaining time
                    now = datetime.now(timezone.utc)
                    if expires_dt.tzinfo is None:
                        expires_dt = expires_dt.replace(tzinfo=timezone.utc)
                    remaining = expires_dt - now
                    remaining_minutes = int(remaining.total_seconds() / 60)
                    
                    if remaining_minutes > 0:
                        blocks.append({
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f"⏰ *Expires in:* {remaining_minutes} minutes"
                            }
                        })

        # Add buttons based on event type
        if change_id:
            if event_type in ("approval_required", "dry_run"):  # Add buttons for both CLI and API approval flows
                # Show Approve/Reject buttons that link to Landing page
                api_base = os.environ.get("APP_BASE_URL") or os.environ.get("RAILWAY_PUBLIC_DOMAIN", "https://saferun-api.up.railway.app")
                if api_base and not api_base.startswith("http"):
                    api_base = f"https://{api_base}"
                approval_page_url = f"{api_base}/approvals/{change_id}"
                
                # Add single "Approval URL" section with direct link to approval page
                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Approval URL:*\n<{approval_page_url}|View Details>"
                    }
                })
                
                # Add Approve/Reject buttons linking to approval page (with change_id)
                blocks.append({
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "✅ Approve"},
                            "style": "primary",
                            "url": approval_page_url
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "❌ Reject"},
                            "style": "danger",
                            "url": approval_page_url
                        }
                    ]
                })
            elif event_type == "executed_with_revert":
                # Determine success message based on operation type and item type
                item_type = payload.get("item_type", "repository")
                
                # Get metadata to determine actual operation
                metadata = payload.get("metadata", {})
                if not metadata:
                    extras = payload.get("extras", {})
                    metadata = extras.get("metadata", {})
                if isinstance(metadata, str):
                    try:
                        metadata = json.loads(metadata)
                    except Exception:
                        metadata = {}
                
                operation_type = metadata.get("operation_type")
                
                # Determine success message based on operation_type
                if operation_type == "github_force_push":
                    success_msg = "*Force push executed successfully.*"
                elif operation_type == "github_branch_delete":
                    success_msg = "*Branch deleted successfully.*"
                elif operation_type == "github_pr_merge":
                    success_msg = "*Pull request merged successfully.*"
                elif operation_type == "github_repo_archive":
                    success_msg = "*Repository archived successfully.*"
                elif operation_type == "github_repo_unarchive":
                    success_msg = "*Repository unarchived successfully.*"
                elif operation_type == "github_repo_delete":
                    success_msg = "*Repository deleted successfully. (PERMANENT)*"
                elif item_type == "branch":
                    # Fallback for branch operations
                    success_msg = "*Branch operation completed successfully.*"
                elif item_type == "repo":
                    success_msg = "*Repository operation completed successfully.*"
                else:
                    success_msg = "*Operation completed successfully.*"
                
                # Show Revert button only
                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"{success_msg}\nYou have *{revert_window_hours} hours* to revert this action if needed."
                    }
                })
                blocks.append({
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "🔄 Revert Action"},
                            "style": "danger",
                            "action_id": "revert_change",
                            "value": change_id
                        }
                    ]
                })
            elif event_type == "failed":
                # Show error details for failed operations
                error_message = payload.get("extras", {}).get("error_message", "Unknown error")
                suggestion = payload.get("extras", {}).get("suggestion")
                
                error_text = f"*Error:* {error_message}"
                if suggestion:
                    error_text += f"\n\n*💡 Suggestion:*\n{suggestion}"
                
                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": error_text
                    }
                })

        body = {
            "channel": channel,
            "text": text,  # Fallback
            "blocks": blocks
        }

        headers = {"Authorization": f"Bearer {bot_token}"}

        # Check if we should update an existing message or create a new one
        # For "failed" and "executed_with_revert" events, ALWAYS create new message (don't update)
        # because the message structure is completely different (no approval buttons, different content)
        existing_message_ts = None
        if change_id and event_type not in ["failed", "executed_with_revert"]:
            from . import db_adapter as db
            existing_message_ts = db.get_slack_message_ts(change_id)

        if existing_message_ts:
            # UPDATE existing message (only for approval_required events)
            body["ts"] = existing_message_ts
            api_url = "https://slack.com/api/chat.update"
            logger.info(f"[SLACK] Updating existing message {existing_message_ts} for change {change_id}")
        else:
            # CREATE new message
            api_url = "https://slack.com/api/chat.postMessage"
            logger.info(f"[SLACK] Creating new message for change {change_id} (event: {event_type})")

        async def do():
            resp = await self.client.post(
                api_url,
                json=body,
                headers=headers
            )
            # Check Slack API response
            result = resp.json()
            if not result.get("ok"):
                error_msg = result.get("error", "unknown_error")
                logger.error(f"[SLACK ERROR] API returned: {error_msg}, full response: {result}")
                raise Exception(f"Slack API error: {error_msg}")
            
            # Save message timestamp for future updates (only for new messages)
            if change_id and not existing_message_ts:
                message_ts = result.get("ts")
                if message_ts:
                    from . import db_adapter as db
                    db.set_slack_message_ts(change_id, message_ts)
                    logger.info(f"[SLACK] Saved message_ts={message_ts} for change {change_id}")
            
            logger.info(f"[SLACK SUCCESS] Message {'updated' if existing_message_ts else 'sent'} to {channel}")
            return resp
        await self._retry(do)

    async def _send_slack_webhook(self, payload: Dict[str, Any], text: str, webhook_url: str, event_type: str = "dry_run") -> None:
        """Fallback: Send via Incoming Webhook (simple, no interactivity)"""
        change_id = payload.get("change_id")
        approve_url = payload.get("approve_url")
        revert_url = payload.get("revert_url")
        revert_window_hours = payload.get("revert_window_hours")
        risk_score = payload.get("risk_score", 0.0)
        title = payload.get("title", "Unknown operation")
        provider = payload.get("provider", "unknown")
        target_id = payload.get("target_id", "")
        
        # Determine operation type and repository from metadata/payload
        operation_display = title  # Default to title
        repository_name = title
        
        # For GitHub, parse operation type from metadata
        if provider == "github":
            metadata = payload.get("metadata", {})
            if not metadata:
                extras = payload.get("extras", {})
                metadata = extras.get("metadata", {})
            
            # Parse metadata if it's a JSON string from storage
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except Exception:
                    metadata = {}
            
            object_type = metadata.get("object")
            
            # Extract repo name from target_id
            if target_id:
                if "#" in target_id:
                    repository_name = target_id.split("#")[0]
                elif "/" in target_id:
                    repository_name = target_id
            
            # Determine operation display text - check operation_type first!
            op_type = metadata.get("operation_type", "")
            
            if object_type == "repository":
                # Check operation_type to distinguish between archive, unarchive and delete
                if op_type == "delete_repo" or op_type == "github_repo_delete":
                    operation_display = "🔴 Repository Deletion (PERMANENT)"
                elif op_type == "github_repo_unarchive":
                    operation_display = "Unarchive Repository"
                elif op_type == "github_repo_archive":
                    operation_display = "Archive Repository"
                else:
                    operation_display = "Repository Operation"
            elif object_type == "branch":
                branch_name = metadata.get("name") or metadata.get("branch", "branch")
                # Check operation_type to distinguish between delete and force push
                if op_type == "github_force_push":
                    operation_display = f"Force Push: {branch_name}"
                elif op_type == "github_branch_delete":
                    operation_display = f"Delete Branch: {branch_name}"
                else:
                    # Fallback - check if it looks like delete
                    operation_display = f"Branch Operation: {branch_name}"
            elif object_type == "merge" or op_type == "github_pr_merge":
                if metadata.get("isTargetDefault"):
                    operation_display = "Merge to Main Branch"
                else:
                    operation_display = "Merge to Branch"
            else:
                operation_display = f"GitHub Operation: {title}"

        # Header text based on event type
        if event_type == "executed_with_revert":
            header_text = "✅ Action Executed"
        else:
            header_text = "🛡️ SafeRun Approval Required"

        # Build fields based on provider
        fields = []
        if provider == "github" and repository_name != operation_display:
            # For GitHub, show Provider, Repository, Operation separately
            fields = [
                {"type": "mrkdwn", "text": f"*Provider:*\n🐙 {provider.capitalize()}"},
                {"type": "mrkdwn", "text": f"*Repository:*\n{repository_name}"},
                {"type": "mrkdwn", "text": f"*Operation:*\n{operation_display}"},
                {"type": "mrkdwn", "text": f"*Risk Score:*\n{risk_score * 10:.1f}/10"}  # risk_score stored as 0-1, display as 0-10
            ]
        else:
            # For other providers or fallback
            fields = [
                {"type": "mrkdwn", "text": f"*Operation:*\n{operation_display}"},
                {"type": "mrkdwn", "text": f"*Risk Score:*\n{risk_score * 10:.1f}/10"}  # risk_score stored as 0-1, display as 0-10
            ]
        
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": header_text
                }
            },
            {
                "type": "section",
                "fields": fields
            }
        ]

        # Add CRITICAL WARNING for repository deletion
        if provider == "github":
            metadata = payload.get("metadata", {})
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except Exception:
                    metadata = {}
            op_type = metadata.get("operation_type", "")
            if op_type == "delete_repo":
                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            "🔴 *CRITICAL WARNING - PERMANENT OPERATION*\n\n"
                            "*This operation is IRREVERSIBLE:*\n"
                            "• All repository data will be permanently deleted\n"
                            "• All issues, pull requests, and wikis will be lost\n"
                            "• All Git history will be destroyed\n"
                            "• Repository cannot be recovered after deletion\n\n"
                            "⚠️ *Note:* This operation requires `delete_repo` scope in GitHub PAT\n"
                            "If PAT lacks this permission, the operation will fail with 403/404 error."
                        )
                    }
                })

        # For executed_with_revert, show revert instructions
        if event_type == "executed_with_revert" and revert_url:
            # Success message based on operation_type (not display text!)
            op_type = metadata.get("operation_type", "")
            
            if op_type == "github_repo_archive":
                success_msg = "*Repository archived successfully.*"
            elif op_type == "github_repo_unarchive":
                success_msg = "*Repository unarchived successfully.*"
            elif op_type == "github_branch_delete":
                success_msg = "*Branch deleted successfully.*"
            elif op_type == "github_force_push":
                success_msg = "*Force push executed successfully.*"
            elif op_type == "github_pr_merge":
                success_msg = "*Pull request merged successfully.*"
            elif op_type == "github_repo_delete":
                success_msg = "*Repository deleted successfully. (PERMANENT)*"
            else:
                # Fallback - check display text
                if "Archive" in operation_display:
                    success_msg = "*Repository archived successfully.*"
                elif "Unarchive" in operation_display:
                    success_msg = "*Repository unarchived successfully.*"
                else:
                    success_msg = "*Operation completed successfully.*"
            
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"{success_msg}\nYou have *{revert_window_hours} hours* to revert this action if needed."
                }
            })
            
            # Add revert instructions with curl command
            revert_operation = "Repository Unarchive" if "Archive" in operation_display else "Branch Restore"
            
            # Create proper curl command with API key requirement
            curl_command = f"curl -X POST '{revert_url}' \\\n  -H 'x-api-key: YOUR_SAFERUN_API_KEY' \\\n  -H 'Content-Type: application/json' \\\n  -d '{{\"github_token\": \"YOUR_GITHUB_TOKEN\"}}'"
            
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*:arrows_counterclockwise: Revert Available:* {revert_operation}\n\n```{curl_command}```\n\n:warning: *Important:* Use the same SafeRun API key from your original request"
                }
            })
        elif approve_url:
            # Add expiration info BEFORE approval URL for dry_run/approval_required events
            expires_at = payload.get("expires_at")
            if expires_at and event_type in ("dry_run", "approval_required"):
                try:
                    # Parse expires_at timestamp
                    if isinstance(expires_at, str):
                        expires_dt = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
                    else:
                        expires_dt = expires_at
                    
                    if expires_dt:
                        # Calculate remaining time
                        now = datetime.now(timezone.utc)
                        if expires_dt.tzinfo is None:
                            expires_dt = expires_dt.replace(tzinfo=timezone.utc)
                        remaining = expires_dt - now
                        remaining_minutes = int(remaining.total_seconds() / 60)
                        
                        if remaining_minutes > 0:
                            hours = remaining_minutes // 60
                            minutes = remaining_minutes % 60
                            time_str = f"{hours}h {minutes}m" if hours > 0 else f"{minutes} minutes"
                            
                            blocks.append({
                                "type": "section",
                                "text": {
                                    "type": "mrkdwn",
                                    "text": f"⏰ *Expires in:* {time_str}"
                                }
                            })
                except Exception as e:
                    print(f"⚠️ Failed to parse expires_at in CLI notification: {e}")
            
            # Add approve URL for dry_run events
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Approval URL:*\n<{approve_url}|View Details>"
                }
            })

        # Webhook only supports URL buttons (not interactive)
        if change_id and event_type != "executed_with_revert":
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
            "revert_url": (extras or {}).get("revert_url"),
            "revert_window_hours": (extras or {}).get("revert_window_hours"),
            "revert_token": (extras or {}).get("revert_token"),
            "expires_at": change.get("expires_at"),  # Add expiration time for approval notifications
            "metadata": change.get("metadata"),  # Add metadata from change_data
            "extras": extras,  # Include full extras for fallback metadata access
            "ts": change.get("ts") or change.get("created_at"),
            "meta": (extras or {}).get("meta", {}),
        }

        # Add user-specific webhook if provided
        webhook_url = change.get("webhook_url")

        text_map = {
            "dry_run": ":rotating_light: [SafeRun] High-risk API Request → approval needed",
            "applied": ":white_check_mark: [SafeRun] Applied",
            "reverted": ":rewind: [SafeRun] Reverted",
            "expired": ":hourglass_flowing_sand: [SafeRun] Expired",
            "executed_with_revert": ":white_check_mark: [SafeRun] Action Executed (revert available)",
            "failed": ":x: [SafeRun] Operation Failed",
        }
        text = text_map.get(event, f"[SafeRun] {event}")

        # Fan-out concurrently with api_key for user-specific settings and event_type for Slack
        tasks = [
            self.send_slack(payload, text, api_key, event),
            self.send_webhook(payload, api_key)
        ]

        # Add custom webhook if URL provided
        if webhook_url:
            tasks.append(self.send_custom_webhook(webhook_url, payload))

        await asyncio.gather(*tasks, return_exceptions=True)

notifier = Notifier()


async def send_to_slack(webhook_url: str, message: Dict[str, Any]) -> bool:
    """
    Helper function to send formatted message to Slack webhook
    Used by GitHub webhooks router
    
    Args:
        webhook_url: Slack webhook URL
        message: Formatted Slack message payload
    
    Returns:
        bool: True if successful
    """
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.post(webhook_url, json=message)
            return response.status_code == 200
    except Exception as e:
        logger.error(f"Failed to send to Slack: {e}")
        return False


def format_slack_message(action, user_email: str, source: str = "github_webhook", event_type: str = "push") -> Dict[str, Any]:
    """
    Format GitHub webhook event into Slack message
    
    Args:
        action: Action model instance
        user_email: User email
        source: Source of event (github_webhook, sdk, cli)
        event_type: GitHub event type (push, delete, pull_request, etc)
    
    Returns:
        Dict: Formatted Slack message payload
    """
    metadata = action.metadata or {}
    revert_action = metadata.get("revert_action", {})
    event_payload = metadata.get("payload", {})
    sender = metadata.get("sender", "unknown")
    
    # Build operation description
    operation_desc = action.operation_type.replace("github_", "").replace("_", " ").title()
    
    # Special formatting for specific operations
    if "repository" in action.operation_type.lower() and event_type == "repository":
        # Get repository action type from payload
        repository_action = event_payload.get("action", "")
        if repository_action == "unarchived":
            operation_desc = "Repository Unarchived"
        elif repository_action == "archived":
            operation_desc = "Repository Archived"
        elif repository_action == "deleted":
            operation_desc = "🔴 Repository Deletion (PERMANENT)"
    
    # Special handling for delete repository operation via API/SDK
    if "repo.delete" in action.operation_type.lower() or "repo_delete" in action.operation_type.lower():
        operation_desc = "🔴 Repository Deletion (PERMANENT)"
    
    # Risk level emoji
    risk_emoji = "🔴" if action.risk_score >= 7.0 else "🟡" if action.risk_score >= 4.0 else "🟢"
    
    # Source badge
    source_badge = {
        "github_webhook": "🌐 GitHub Webhook",
        "sdk": "📦 SafeRun SDK",
        "cli": "💻 Git CLI"
    }.get(source, source)
    
    message = {
        "text": f"🚨 SafeRun Alert - GitHub Event Detected",
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{risk_emoji} SafeRun Alert - GitHub Event Detected"
                }
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Operation:*\n{operation_desc}"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Repository:*\n`{action.repo_name}`"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Author:*\n@{sender}"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Risk Score:*\n{action.risk_score * 10:.1f}/10"  # risk_score stored as 0-1, display as 0-10
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Source:*\n{source_badge}"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*User:*\n{user_email}"
                    }
                ]
            }
        ]
    }
    
    # Add branch info if available
    if action.branch_name:
        message["blocks"][1]["fields"].insert(2, {
            "type": "mrkdwn",
            "text": f"*Branch:*\n`{action.branch_name}`"
        })
    
    # Add risk reasons if available
    if action.risk_reasons:
        reasons_text = "\n".join([f"• {r.replace('github_', '').replace('_', ' ').title()}" for r in action.risk_reasons])
        message["blocks"].append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*⚠️ Risk Factors:*\n{reasons_text}"
            }
        })
    
    # Add CRITICAL warning for repository deletion
    if "repo.delete" in action.operation_type.lower() or "repo_delete" in action.operation_type.lower():
        message["blocks"].append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "🔴 *CRITICAL WARNING - PERMANENT OPERATION*\n\n"
                    "*This operation is IRREVERSIBLE:*\n"
                    "• All repository data will be permanently deleted\n"
                    "• All issues, pull requests, and wikis will be lost\n"
                    "• All Git history will be destroyed\n"
                    "• Repository cannot be recovered after deletion\n\n"
                    "⚠️ *Note:* This operation requires `delete_repo` scope in GitHub PAT\n"
                    "If PAT lacks this permission, the operation will fail with 403/404 error."
                )
            }
        })
    
    # Add warning for bypassed protection (only for high-risk operations)
    if source == "github_webhook" and action.risk_score >= 4.0:
        message["blocks"].append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": ":warning: *Event bypassed CLI/SDK protection*\nThis operation was performed directly via GitHub API or Web UI."
            }
        })
    
    # Add revert information if available
    if revert_action:
        revert_type = revert_action.get("type", "").replace("_", " ").title()
        revert_url = f"https://saferun-api.up.railway.app/webhooks/github/revert/{action.id}"
        
        # Special handling for merge revert (limited revert with warnings)
        if revert_action.get("type") == "merge_revert":
            repo_name = metadata.get("repo_name", "")
            owner, repo = repo_name.split("/") if "/" in repo_name else ("", repo_name)
            branch_protection_url = f"https://github.com/{owner}/{repo}/settings/branches" if owner else ""
            
            warning_text = (
                f"*⚠️ Limited Revert Available:*\n"
                f"{revert_type} (force-updates branch to pre-merge state)\n\n"
                f"*⚠️ Limitations & Consequences:*\n"
                f"• Merge commit will be REMOVED from history (destructive)\n"
                f"• Team members who pulled the merge will have diverged history\n"
                f"• Temporal window existed - code may have been deployed\n"
                f"• Does NOT prevent future unauthorized merges\n\n"
                f"*To revert changes (via curl):*\n"
                f"```curl -X POST '{revert_url}' \\\n  -H 'x-api-key: YOUR_SAFERUN_API_KEY' \\\n  -H 'Content-Type: application/json' \\\n  -d '{{\"github_token\": \"YOUR_GITHUB_TOKEN\"}}'```\n\n"
                f":warning: *Important:* Use the same SafeRun API key from your original request"
            )
            
            if branch_protection_url:
                warning_text += (
                    f"\n\n*🛡️ RECOMMENDED: Enable Branch Protection*\n"
                    f"Prevent merges without review:\n"
                    f"{branch_protection_url}\n\n"
                    f"Required settings:\n"
                    f"✅ Require pull request reviews before merging\n"
                    f"✅ Dismiss stale pull request approvals\n"
                    f"❌ Allow force pushes (keep disabled)"
                )
            
            message["blocks"].append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": warning_text
                }
            })
        else:
            # Standard revert message for other operations
            message["blocks"].append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*:arrows_counterclockwise: Revert Available:*\n{revert_type}\n\n```curl -X POST '{revert_url}' \\\n  -H 'x-api-key: YOUR_SAFERUN_API_KEY' \\\n  -H 'Content-Type: application/json' \\\n  -d '{{\"github_token\": \"YOUR_GITHUB_TOKEN\"}}'```\n\n:warning: *Important:* Use the same SafeRun API key from your original request"
                }
            })
    
    # Add approval requirement for high-risk
    if action.risk_score >= 7.0:
        message["blocks"].append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":rotating_light: *Approval Required*\nAction ID: `{action.id}` - Check SafeRun dashboard"
            }
        })
        
        # Add expiration time for approval-required operations
        if action.expires_at:
            try:
                # Parse expires_at timestamp
                if isinstance(action.expires_at, str):
                    expires_dt = datetime.fromisoformat(action.expires_at.replace('Z', '+00:00'))
                else:
                    expires_dt = action.expires_at
                
                if expires_dt:
                    # Calculate remaining time
                    from datetime import timezone
                    now = datetime.now(timezone.utc)
                    if expires_dt.tzinfo is None:
                        expires_dt = expires_dt.replace(tzinfo=timezone.utc)
                    remaining = expires_dt - now
                    remaining_minutes = int(remaining.total_seconds() / 60)
                    
                    if remaining_minutes > 0:
                        hours = remaining_minutes // 60
                        minutes = remaining_minutes % 60
                        time_str = f"{hours}h {minutes}m" if hours > 0 else f"{minutes} minutes"
                        
                        message["blocks"].append({
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f"⏰ *Expires in:* {time_str}"
                            }
                        })
            except Exception as e:
                print(f"⚠️ Failed to parse expires_at: {e}")
        
        # Add Approve/Reject buttons for webhook high-risk events
        api_base = os.environ.get("APP_BASE_URL") or os.environ.get("RAILWAY_PUBLIC_DOMAIN", "https://saferun-api.up.railway.app")
        if api_base and not api_base.startswith("http"):
            api_base = f"https://{api_base}"
        
        # Use action.id as change_id for webhook events
        approval_page_url = f"{api_base}/approvals/{action.id}"
        
        message["blocks"].append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "✅ Approve"},
                    "style": "primary",
                    "url": approval_page_url
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "❌ Reject"},
                    "style": "danger",
                    "url": approval_page_url
                }
            ]
        })
    
    message["blocks"].append({"type": "divider"})
    
    return message
