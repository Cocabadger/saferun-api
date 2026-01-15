import os, json, hmac, hashlib, asyncio, logging
from typing import Dict, Any, Optional
from datetime import datetime, timezone
import httpx

logger = logging.getLogger(__name__)

# Human-readable risk reason descriptions for Slack notifications
# Maps internal reason codes to clear explanations for security admins
RISK_REASON_DESCRIPTIONS = {
    # ===========================================
    # CLI Git Operations (reset, clean, rebase, etc.)
    # ===========================================
    
    # Reset Hard
    "reset_hard": "Reset --hard discards ALL uncommitted changes and resets history",
    "hard_reset": "Hard reset - working directory and index will be overwritten",
    
    # Force Push (CLI)
    "force_push": "Force push rewrites remote history - other developers may lose work",
    "force_push_main": "Force push to main/master - production branch history at risk",
    "force_push_protected": "Force push to protected branch - bypasses branch protection",
    
    # Branch Delete (CLI)
    "branch_delete": "Branch deletion - local/remote branch will be removed",
    "branch_delete_main": "Deleting main/master branch - critical for team workflow",
    "branch_delete_remote": "Remote branch deletion - affects all collaborators",
    
    # Clean
    "clean": "Git clean removes untracked files permanently",
    "clean_force": "Git clean -f removes untracked files without confirmation",
    "clean_directories": "Git clean -d also removes untracked directories",
    
    # Rebase
    "rebase": "Rebase rewrites commit history - may require force push",
    "rebase_interactive": "Interactive rebase - modifying commit sequence",
    "rebase_onto_main": "Rebasing onto main - history will be rewritten",
    
    # Cherry-pick
    "cherry_pick": "Cherry-pick - copying commit to another branch",
    
    # Destructive operations
    "destructive_history_rewrite": "History rewrite operation - cannot be easily undone",
    
    # ===========================================
    # GitHub API Operations
    # ===========================================
    
    # CRITICAL - Irreversible operations
    "github_irreversible_repo_deletion": "Repository deletion is PERMANENT - all code, issues, PRs will be lost forever",
    "github_repository_deleted": "Repository was deleted - IRREVERSIBLE operation",
    "github_repo_transfer_irreversible": "Repository transfer to another owner - cannot be undone without their consent",
    "github_making_repo_public_permanent": "Making repository PUBLIC - code will be visible to everyone on the internet",
    "github:irreversible_operation": "This operation cannot be easily undone",

    # HIGH - Force push and history rewriting
    "github_force_push": "Force push detected - rewrites Git history, can lose commits",
    "github_force_push_danger": "Force push rewrites commit history - other developers may lose work",
    "github_force_push_to_main": "Force push to main/master - rewrites production branch history",

    # HIGH - Branch operations
    "github_default_branch": "Operation on default/main branch",
    "github_default_branch_deletion": "Deleting the default branch - breaks all clones and CI/CD",
    "github_protected_branch_deletion": "Deleting protected branch (main/master/develop/production)",
    "github_branch_deletion": "Branch deletion",
    "github_delete_main_branch": "Deleting main/master branch - catastrophic for team workflow",
    "github_branch_delete": "Branch deletion - cannot be recovered without reflog",
    "github:main_branch_protection": "Operation affects main branch protection",

    # HIGH - Merge operations
    "github_merge_to_main": "Merge to main/master - changes go directly to production branch",
    "github_merge_without_review": "Merged without code review - no peer verification",
    "github_merge_operation": "Merge operation - combining branch histories",
    "github_merge": "Pull request merge",

    # HIGH - Security-critical operations
    "github_secret_cicd_access": "CI/CD secret modification - could expose credentials or compromise pipeline",
    "github_secret_critical_name": "Modifying production/AWS/database secret",
    "github_secret_deletion": "Deleting CI/CD secret - may break deployments",
    "github_secret_critical_deletion": "Deleting critical production secret",
    "github_workflow_code_execution": "Workflow modification - can execute arbitrary code in CI/CD",
    "github_workflow_suspicious_patterns": "Workflow contains suspicious patterns (curl, eval, exec)",

    # HIGH - Branch protection
    "github_branch_protection_weakening": "Weakening branch protection rules - reduces security guardrails",
    "github_removing_reviews_main_branch": "Removing required reviews on main branch",
    "github_branch_protection_removal": "Removing branch protection entirely",
    "github_removing_protection_main_branch": "Removing protection from main/master branch",

    # MEDIUM - Other operations
    "github_repository_archived": "Repository archived - becomes read-only",
    "github_tag_delete": "Tag deletion - may break release references",
    "github_large_push": "Large push (>10 commits) - significant codebase change",
    "github_making_repo_private": "Making repository private - may break external integrations",
    "github:reversible_operation": "This operation can be reverted",

    # LOW - Heuristics
    "github_name_keywords": "Repository name contains sensitive keywords (prod, infra, deploy)",
    "github_recent_commit": "Recently modified repository",

    # Airtable reasons
    "airtable_title_keywords": "Record contains sensitive business data (customer, contract, pricing)",
    "airtable_recently_edited": "Recently edited record - may have unsaved dependencies",
    "airtable_high_linked_count": "Record has many linked records - deletion cascades to related data",
}


def generate_command_preview(operation_type: str, metadata: dict, target_id: str = "") -> Optional[str]:
    """
    Generate a human-readable command preview for Slack notifications.
    Shows what command/action is being executed.
    """
    if not operation_type:
        return None

    branch = metadata.get("name") or metadata.get("branch") or ""
    sha = metadata.get("sha") or metadata.get("commit_sha") or ""
    before_sha = metadata.get("before_sha") or ""
    after_sha = metadata.get("after_sha") or ""
    merge_sha = metadata.get("merge_commit_sha") or ""
    source_branch = metadata.get("source_branch") or ""
    target_branch = metadata.get("target_branch") or ""

    # Extract repo from target_id
    repo = target_id.split("#")[0] if "#" in target_id else target_id

    # Truncate SHA to 7 chars for display
    sha_short = sha[:7] if sha else ""
    before_short = before_sha[:7] if before_sha else ""
    after_short = after_sha[:7] if after_sha else ""
    merge_short = merge_sha[:7] if merge_sha else ""

    op = operation_type.lower()

    # Force push
    if "force_push" in op:
        if before_short and after_short:
            return f"`git push --force origin {branch}`\n`{before_short}` → `{after_short}`"
        elif branch:
            return f"`git push --force origin {branch}`"
        return "`git push --force`"

    # Branch delete
    if "branch_delete" in op or "delete_branch" in op:
        if sha_short:
            return f"`git branch -D {branch}`\nLast commit: `{sha_short}`"
        return f"`git branch -D {branch}`"

    # Repository delete
    if "repo_delete" in op or "repository_delete" in op:
        return f"`gh repo delete {repo} --yes`\n*PERMANENT - cannot be undone*"

    # Repository archive
    if "repo_archive" in op or "repository_archive" in op:
        return f"`gh repo archive {repo}`"

    # Repository unarchive
    if "repo_unarchive" in op:
        return f"`gh repo unarchive {repo}`"

    # PR merge
    if "pr_merge" in op or "merge" in op:
        if source_branch and target_branch:
            cmd = f"`git merge {source_branch}` → `{target_branch}`"
            if merge_short:
                cmd += f"\nMerge commit: `{merge_short}`"
            return cmd
        elif merge_short:
            return f"Merge commit: `{merge_short}`"

    # Repository transfer
    if "repo_transfer" in op:
        return f"`gh repo transfer {repo} <new-owner>`"

    # Secret operations
    if "secret" in op:
        secret_name = metadata.get("secret_name", "SECRET_NAME")
        if "delete" in op:
            return f"`gh secret delete {secret_name}`"
        return f"`gh secret set {secret_name}`"

    # Workflow operations
    if "workflow" in op:
        return "`.github/workflows/*.yml` modification"

    # Branch protection
    if "branch_protection" in op:
        if "delete" in op or "removal" in op:
            return f"Remove branch protection rules from `{branch or 'main'}`"
        return f"Modify branch protection rules for `{branch or 'main'}`"

    # Visibility change
    if "visibility" in op or "making_repo" in op:
        if "public" in op:
            return f"`gh repo edit {repo} --visibility public`"
        return f"`gh repo edit {repo} --visibility private`"

    # ===========================================
    # CLI Git Operations (from interceptors)
    # ===========================================
    
    # Check if we have a command in metadata (from CLI)
    command = metadata.get("command", "")
    if command:
        # Already has a command from CLI - use it
        target = metadata.get("target") or target_id
        commits_discarded = metadata.get("commitsDiscarded", 0)
        
        # Reset hard
        if op == "reset_hard" or op == "hard_reset":
            preview = f"`{command}`"
            if commits_discarded and commits_discarded > 0:
                preview += f"\n⚠️ Discards ~{commits_discarded} commit(s)"
            return preview
        
        # Clean
        if op == "clean":
            return f"`{command}`\n⚠️ Removes untracked files permanently"
        
        # Rebase
        if op == "rebase":
            return f"`{command}`\n⚠️ Rewrites commit history"
        
        # Cherry-pick
        if op == "cherry_pick":
            return f"`{command}`"
        
        # Destructive history rewrite
        if "destructive" in op or "history_rewrite" in op:
            return f"`{command}`\nCannot be undone"
        
        # Generic CLI command with command
        return f"`{command}`"
    
    # Fallback for operations without command in metadata
    # Reset hard without explicit command
    if op == "reset_hard" or op == "hard_reset":
        target = metadata.get("target") or target_id
        if target:
            return f"`git reset --hard {target}`"
        return "`git reset --hard`"

    return None

TIMEOUT = float(os.getenv("NOTIFY_TIMEOUT_MS", "2000")) / 1000.0
RETRY = int(os.getenv("NOTIFY_RETRY", "1"))
# REMOVED: SLACK_URL/SLACK_WEBHOOK_URL - legacy webhook approach (security risk)
# All Slack notifications now use OAuth tokens via slack_installations table
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")  # Global fallback for testing only
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
        """
        Send Slack notification using OAuth bot token from slack_installations.
        
        Priority:
        1. OAuth token from slack_installations (new flow via "Add to Slack")
        2. Legacy: user_notification_settings (manual token entry - deprecated)
        3. Fallback: global env vars (for testing)
        """
        from . import db_adapter as db
        
        bot_token = None
        channel = None
        
        if api_key:
            # Priority 1: OAuth installation (new flow)
            slack_installation = db.get_slack_installation(api_key)
            if slack_installation:
                bot_token = slack_installation.get("bot_token")
                channel = slack_installation.get("channel_id")
                team_name = slack_installation.get('team_name')
                if not channel:
                    # Bot installed but not invited to any channel - find first available
                    logger.warning(f"[SLACK] No channel_id stored for {team_name} - bot may need to be invited to a channel")
                logger.info(f"[SLACK] Using OAuth bot token for {team_name}, channel={channel}")
            else:
                # Priority 2: Legacy user settings (deprecated)
                user_settings = db.get_notification_settings(api_key)
                if user_settings and user_settings.get("slack_enabled"):
                    bot_token = user_settings.get("slack_bot_token")
                    channel = user_settings.get("slack_channel", "#saferun-alerts")
                    if bot_token:
                        logger.info("[SLACK] Using legacy bot token from user settings")
        
        # Priority 3: Global env var (testing/fallback)
        if not bot_token and SLACK_BOT_TOKEN:
            bot_token = SLACK_BOT_TOKEN
            channel = SLACK_CHANNEL
            logger.info("[SLACK] Using global env SLACK_BOT_TOKEN")
        
        if bot_token and channel:
            await self._send_slack_bot(payload, text, bot_token, channel, event_type)
        elif bot_token and not channel:
            logger.warning("[SLACK] Bot token available but no channel configured - invite bot to a channel")
        else:
            logger.warning("[SLACK] No bot token available - notification not sent")

    async def _send_slack_bot(self, payload: Dict[str, Any], text: str, bot_token: str, channel: str, event_type: str = "dry_run") -> None:
        """Send via Slack Bot API with interactive buttons - Banking Grade format"""
        change_id = payload.get("change_id")
        approve_url = payload.get("approve_url")
        revert_url = payload.get("revert_url")
        revert_window_hours = payload.get("revert_window_hours") or 24
        risk_score = payload.get("risk_score", 0.0)
        title = payload.get("title", "Unknown operation")
        provider = payload.get("provider", "unknown")
        target_id = payload.get("target_id", "")
        
        # Banking Grade: Extract risk_reasons from payload
        risk_reasons = payload.get("risk_reasons", [])
        summary_json = payload.get("summary_json", {})
        
        # Try to get metadata from various sources
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
        
        # Parse summary_json if string
        if isinstance(summary_json, str):
            try:
                summary_json = json.loads(summary_json)
            except Exception:
                summary_json = {}
        
        # ===========================================
        # MINIMALIST FORMAT for executed_with_revert
        # Designed for engineers with ADHD - scan in 1 second
        # ===========================================
        if event_type == "executed_with_revert" and change_id:
            # Extract key info
            operation_type = summary_json.get("operation_type", "") if isinstance(summary_json, dict) else ""
            branch_name = summary_json.get("branch_name", "") if isinstance(summary_json, dict) else ""
            repo_name = target_id or summary_json.get("repo_name", "repository")
            revert_action = summary_json.get("revert_action") if isinstance(summary_json, dict) else None
            
            # Clean operation name
            op_display = operation_type.replace("github_", "").replace("_", " ").title() if operation_type else "Operation"
            if branch_name:
                op_display = f"{op_display} → {branch_name}"
            
            # Minimal blocks - show Revert button ONLY if operation is revertable
            if revert_action:
                # Revertable operation - show with Revert button
                blocks = [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"✓ *Executed:* {op_display}\n`{repo_name}` • {revert_window_hours}h to revert"
                        },
                        "accessory": {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "🔄 Revert"},
                            "style": "danger",
                            "action_id": "revert_change",
                            "value": change_id
                        }
                    }
                ]
            else:
                # Non-revertable operation - just confirmation, no button
                blocks = [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"✓ *Executed:* {op_display}\n`{repo_name}`"
                        }
                    }
                ]
            
            # Send minimalist message
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    "https://slack.com/api/chat.postMessage",
                    headers={
                        "Authorization": f"Bearer {bot_token}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "channel": channel,
                        "text": f"✓ Executed: {op_display}",
                        "blocks": blocks
                    }
                )
                data = resp.json()
                if not data.get("ok"):
                    logger.error(f"[SLACK] Bot API error: {data.get('error')}")
                else:
                    # Store message_ts for future updates
                    if change_id:
                        self._message_ts_cache[change_id] = data.get("ts")
                    logger.info(f"[SLACK] Minimalist executed message sent for {change_id[:8]}...")
            return  # Early return - don't use complex format
        
        # ===========================================
        # REACTIVE GOVERNANCE: executed_high_risk
        # For webhooks - operation ALREADY HAPPENED, show Revert option
        # Red alert card but with Revert button, NOT approval buttons
        # ===========================================
        if event_type == "executed_high_risk" and change_id:
            # Extract key info
            operation_type = summary_json.get("operation_type", "") if isinstance(summary_json, dict) else ""
            branch_name = summary_json.get("branch_name", "") if isinstance(summary_json, dict) else ""
            repo_name = target_id or summary_json.get("repo_name", "repository")
            revert_action = summary_json.get("revert_action") if isinstance(summary_json, dict) else None
            
            # Clean operation name
            op_display = operation_type.replace("github_", "").replace("_", " ").title() if operation_type else "Operation"
            if branch_name:
                op_display = f"{op_display} → {branch_name}"
            
            # Build blocks - HIGH RISK styling with Revert button
            if revert_action:
                revert_type = revert_action.get("type", "") if isinstance(revert_action, dict) else ""
                
                # BANKING GRADE: Archive requires manual unarchive via GitHub Settings
                # We do NOT request 'Administration' permissions - principle of least privilege
                if revert_type == "repository_unarchive":
                    owner = revert_action.get("owner", "")
                    repo = revert_action.get("repo", "")
                    settings_url = f"https://github.com/{owner}/{repo}/settings"
                    
                    blocks = [
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f"🚨 *HIGH RISK Executed:* Repository Archived\n`{repo_name}`"
                            }
                        },
                        {
                            "type": "context",
                            "elements": [
                                {
                                    "type": "mrkdwn",
                                    "text": "🛡️ SafeRun does not request 'Administration' permissions to keep your infrastructure secure. Please unarchive manually if needed."
                                }
                            ]
                        },
                        {
                            "type": "actions",
                            "elements": [
                                {
                                    "type": "button",
                                    "text": {"type": "plain_text", "text": "⚙️ Open Settings to Unarchive"},
                                    "url": settings_url,
                                    "style": "primary"
                                }
                            ]
                        }
                    ]
                else:
                    # Other high risk operations - standard Revert button
                    blocks = [
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f"⚠️ *HIGH RISK Executed:* {op_display}\n`{repo_name}` • *{revert_window_hours}h to revert*"
                            },
                            "accessory": {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "🔄 Revert"},
                                "style": "danger",
                                "action_id": "revert_change",
                                "value": change_id
                            }
                        }
                    ]
            else:
                # High risk, not revertable - just alert, no button
                blocks = [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"⚠️ *HIGH RISK Executed:* {op_display}\n`{repo_name}` • No automatic revert available"
                        }
                    }
                ]
            
            # Send high risk alert
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    "https://slack.com/api/chat.postMessage",
                    headers={
                        "Authorization": f"Bearer {bot_token}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "channel": channel,
                        "text": f"⚠️ HIGH RISK Executed: {op_display}",
                        "blocks": blocks
                    }
                )
                data = resp.json()
                if not data.get("ok"):
                    logger.error(f"[SLACK] Bot API error: {data.get('error')}")
                else:
                    # Store message_ts for future updates
                    if change_id:
                        self._message_ts_cache[change_id] = data.get("ts")
                    logger.info(f"[SLACK] HIGH RISK alert sent for {change_id[:8]}...")
            return  # Early return - don't use complex format
        
        # Also check summary_json for additional metadata (CLI operations store metadata there)
        if isinstance(summary_json, dict):
            # For Git CLI operations, metadata is nested in summary_json.metadata
            summary_metadata = summary_json.get("metadata", {})
            if isinstance(summary_metadata, dict):
                # Merge summary_json.metadata into metadata (summary takes precedence for CLI)
                if not metadata:
                    metadata = summary_metadata
                else:
                    # Merge: summary_metadata values override if metadata is sparse
                    for key, value in summary_metadata.items():
                        if key not in metadata or not metadata.get(key):
                            metadata[key] = value
            
            # Merge risk_reasons from summary_json if not in payload
            if not risk_reasons and summary_json.get("reasons"):
                risk_reasons = summary_json.get("reasons", [])
        
        # Determine operation type and repository from metadata/payload
        operation_display = title  # Default to title
        repository_name = title
        branch_name = None
        git_author = None
        source_type = "cli"  # Default to CLI
        
        # ===========================================
        # Handle Git CLI Operations (provider == "git")
        # ===========================================
        if provider == "git":
            # Get operation details from metadata (sent by CLI interceptors)
            operation_type = metadata.get("operation_type") or summary_json.get("operation_type", "")
            command = metadata.get("command") or summary_json.get("command", "")
            
            # Extract repo from metadata or target
            repo = metadata.get("repo") or ""
            if not repo and target_id:
                # target_id format: "owner/repo@ref" or just "ref"
                if "@" in target_id:
                    repo = target_id.split("@")[0]
                elif "/" in target_id:
                    repo = target_id.split("#")[0] if "#" in target_id else target_id
            repository_name = repo if repo else "local repo"
            
            # Extract target ref (branch, commit, etc.)
            target_ref = metadata.get("target") or ""
            if not target_ref and "@" in target_id:
                target_ref = target_id.split("@")[1]
            branch_name = target_ref if target_ref else None
            
            # Get author and source
            git_author = metadata.get("git_author") or metadata.get("author")
            source_type = metadata.get("source", "cli")
            
            # Operation display based on operation_type
            op_lower = operation_type.lower() if operation_type else ""
            if op_lower == "reset_hard" or op_lower == "hard_reset":
                commits = metadata.get("commitsDiscarded", 0)
                if commits > 0:
                    operation_display = f"Reset --hard ({commits} commits)"
                else:
                    operation_display = "Reset --hard"
            elif op_lower == "force_push":
                operation_display = "Force Push"
            elif op_lower == "branch_delete":
                operation_display = "⚠️ Delete Branch"
            elif op_lower == "clean":
                operation_display = "⚠️ Git Clean"
            elif op_lower == "rebase":
                operation_display = "⚠️ Rebase"
            elif op_lower == "cherry_pick":
                operation_display = "Cherry-pick"
            elif "destructive" in op_lower:
                operation_display = "Destructive Operation"
            else:
                # Format operation_type as title
                operation_display = operation_type.replace("_", " ").title() if operation_type else title
        
        # ===========================================
        # Handle GitHub API Operations (provider == "github")
        # ===========================================
        elif provider == "github":
            object_type = metadata.get("object")
            operation_type = metadata.get("operation_type")
            item_type = metadata.get("type")  # For bulk operations
            
            # Banking Grade: Extract author and source
            git_author = metadata.get("git_author") or metadata.get("author") or metadata.get("sender")
            source_type = metadata.get("source", "cli")  # cli, agent, sdk, webhook
            branch_name = metadata.get("name") or metadata.get("branch")
            
            # Extract repo name from target_id (format: owner/repo or owner/repo#branch)
            if target_id:
                if "#" in target_id:
                    repository_name = target_id.split("#")[0]
                    # Also extract branch from target_id if not in metadata
                    if not branch_name:
                        branch_name = target_id.split("#")[1] if "#" in target_id else None
                elif "/" in target_id:
                    repository_name = target_id
            
            # Determine operation display text based on operation_type or object_type
            # Check full operation_type first (github_force_push, github_pr_merge, etc.)
            if operation_type == "delete_repo" or operation_type == "github_repo_delete":
                operation_display = "Repository DELETE (PERMANENT)"
            elif operation_type == "github_force_push" or operation_type == "force_push":
                operation_display = "Force Push"
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
                    operation_display = "Delete Branch"
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
                operation_display = f"Git Operation: {title}"

        # Provider emoji mapping
        provider_emoji = {
            "github": "",
            "git": "",
            "notion": "📝",
            "airtable": "🗂️"
        }.get(provider.lower(), "")
        
        # Source badge mapping
        source_badge = {
            "cli": "Git CLI",
            "agent": "🤖 AI Agent",
            "sdk": "📦 SafeRun SDK",
            "webhook": "GitHub Webhook",
            "gemini": "🤖 Gemini CLI",
            "claude": "🤖 Claude Code"
        }.get(source_type.lower(), source_type)
        
        # Banking Grade: header emoji based on risk_score
        if risk_score > 0.8:
            header_emoji = "🚨"  # Critical risk
        else:
            header_emoji = "🛡️"  # Normal protection

        # Different header based on event type and risk level
        if event_type == "executed_with_revert":
            header_text = "✅ Action Executed"
        elif event_type == "failed":
            header_text = "❌ Operation Failed"
        elif risk_score > 0.8:
            header_text = f"{header_emoji} CRITICAL RISK - Immediate Review Required"
        elif risk_score >= 0.7:
            header_text = "HIGH RISK - Approval Required"
        elif risk_score >= 0.4:
            header_text = "Medium Risk - Approval Required"
        else:
            header_text = f"{header_emoji} SafeRun Approval Required"

        # Build fields - Banking Grade format
        fields = [
            {"type": "mrkdwn", "text": f"*Provider:*\n{provider_emoji} {provider.capitalize()}"},
            {"type": "mrkdwn", "text": f"*Repository:*\n`{repository_name}`"},
            {"type": "mrkdwn", "text": f"*Operation:*\n{operation_display}"},
            {"type": "mrkdwn", "text": f"*Risk Score:*\n{risk_score * 10:.1f}/10"},  # risk_score stored as 0-1, display as 0-10
        ]
        
        # Add branch if available
        if branch_name:
            fields.append({"type": "mrkdwn", "text": f"*Branch:*\n`{branch_name}`"})
        
        # Add source
        fields.append({"type": "mrkdwn", "text": f"*Source:*\n{source_badge}"})
        
        # Add author if available
        if git_author:
            fields.append({"type": "mrkdwn", "text": f"*Author:*\n@{git_author}"})

        # Add client hostname if available (from CLI/SDK)
        client_hostname = metadata.get("client_hostname") if metadata else None
        client_username = metadata.get("client_username") if metadata else None
        if client_hostname:
            host_display = f"`{client_hostname}`"
            if client_username:
                host_display = f"`{client_username}@{client_hostname}`"
            fields.append({"type": "mrkdwn", "text": f"*Host:*\n{host_display}"})

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
        
        # Banking Grade: Add risk reasons as detailed bullet points
        if risk_reasons:
            formatted_reasons = []
            for reason in risk_reasons:
                # Use human-readable description if available
                if reason in RISK_REASON_DESCRIPTIONS:
                    formatted_reasons.append(f"• {RISK_REASON_DESCRIPTIONS[reason]}")
                elif reason.startswith("policy:"):
                    # Format policy reasons specially
                    policy_rule = reason.replace("policy:", "").replace("_", " ").title()
                    formatted_reasons.append(f"• Policy: {policy_rule}")
                elif reason.startswith("commits_discarded:"):
                    # Dynamic reason: commits_discarded:N
                    try:
                        count = int(reason.split(":")[1])
                        formatted_reasons.append(f"• Will discard {count} commit(s)")
                    except (ValueError, IndexError):
                        formatted_reasons.append(f"• Will discard commits")
                elif reason.startswith("commits_over_limit:"):
                    # Dynamic reason: commits_over_limit:N
                    try:
                        limit = int(reason.split(":")[1])
                        formatted_reasons.append(f"• Exceeds safe limit of {limit} commits")
                    except (ValueError, IndexError):
                        formatted_reasons.append(f"• Exceeds safe commit limit")
                else:
                    # Fallback: clean up unknown reasons
                    clean_reason = reason.replace("github:", "").replace("github_", "").replace("_", " ")
                    formatted_reasons.append(f"• {clean_reason.title()}")

            reasons_text = "\n".join(formatted_reasons)
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*⚠️ Risk Factors:*\n{reasons_text}"
                }
            })

        # Add blast radius context if available
        records_affected = metadata.get("records_affected") if metadata else None
        if not records_affected and summary_json:
            records_affected = summary_json.get("records_affected") or summary_json.get("affected_count")

        if records_affected and int(records_affected) > 1:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*💥 Blast Radius:* Affects *{records_affected}* items"
                }
            })

        # Add command preview (what's being executed)
        operation_type = metadata.get("operation_type") if metadata else None
        command_preview = generate_command_preview(operation_type, metadata or {}, target_id)
        if command_preview:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Command:*\n{command_preview}"
                }
            })

        # Web UI dashboard link removed - all approvals happen in Slack
        
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
                # Get approval URL with token from extras (includes authentication)
                approve_url = payload.get("approve_url")
                
                # Interactive buttons - no redirect to browser needed!
                # Approve/Reject happens directly in Slack via action_id
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
                
                # Web UI link removed - approvals happen directly via Slack buttons above
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
                
                # Show Revert button only if operation is revertable
                revert_action = summary_json.get("revert_action") if isinstance(summary_json, dict) else None
                
                if revert_action:
                    # Revertable - show with button
                    blocks.append({
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"{success_msg}\nYou have *{revert_window_hours or 24} hours* to revert this action if needed."
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
                else:
                    # Non-revertable - just confirmation
                    blocks.append({
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": success_msg
                        }
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

        # Banking Grade: Context Block (Audit Trail footer)
        # Shows author, provider, timestamp for compliance tracking
        context_elements = []
        
        # Add provider icon + name
        context_elements.append({
            "type": "mrkdwn",
            "text": f"{provider_emoji} {provider.capitalize()}"
        })
        
        # Add author if available
        if git_author:
            context_elements.append({
                "type": "mrkdwn",
                "text": f"👤 {git_author}"
            })
        
        # Add source badge
        context_elements.append({
            "type": "mrkdwn",
            "text": source_badge
        })
        
        # Add change_id for audit reference
        if change_id:
            context_elements.append({
                "type": "mrkdwn",
                "text": f"📋 `{change_id[:12]}...`"
            })
        
        blocks.append({
            "type": "context",
            "elements": context_elements
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
        # Parse summary_json if it's a JSON string
        summary_json = change.get("summary_json")
        if isinstance(summary_json, str):
            try:
                summary_json = json.loads(summary_json)
            except Exception:
                summary_json = {}
        elif not summary_json:
            summary_json = {}
        
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
            # Banking Grade fields from summary_json
            "risk_reasons": summary_json.get("reasons", []),
            "summary_json": summary_json,
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


# =============================================================================
# LEGACY CODE REMOVED (Security Fix)
# =============================================================================
# The following functions were removed as part of the Cloud-First security migration:
#
# - send_to_slack(webhook_url, message) - REMOVED
#   Reason: Webhook URLs are a security risk (can be leaked, no auth)
#   Replacement: Use notifier.publish() which uses OAuth tokens from slack_installations
#
# - format_slack_message(action, ...) - REMOVED  
#   Reason: Slack messages are now formatted in _send_slack_bot() with Banking Grade format
#   Replacement: Pass change data to notifier.publish() which handles all formatting
#
# Migration path for callers:
#   OLD: await send_to_slack(webhook_url, format_slack_message(action, ...))
#   NEW: await notifier.publish(event="dry_run", change=change_data, api_key=user_api_key)
# =============================================================================
