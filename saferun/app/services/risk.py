from datetime import datetime, timezone
from typing import Tuple, List

KEYWORDS_HIGH = ["roadmap", "customer", "contract", "pricing", "finance", "budget", "clients"]

def compute_risk_airtable(title: str, linked_count: int, edited_age_hours: float) -> tuple[float, list[str]]:
    risk_score = 0.0
    reasons = []
    # debug: compute_risk_airtable diagnostics (removed)

    if title and any(keyword in title.lower() for keyword in ["customer", "contract", "pricing", "invoice"]):
        risk_score += 0.30
        reasons.append("airtable_title_keywords")

    if edited_age_hours < 3:
        risk_score += 0.20
        reasons.append("airtable_recently_edited")

    if linked_count > 5:
        risk_score += 0.10
        reasons.append("airtable_high_linked_count")

    return risk_score, reasons

def compute_risk(provider: str, title: str, blocks_count: int, last_edit: str | None, linked_count: int = 0, metadata: dict = None) -> tuple[float, list[str]]:
    risk_score = 0.0
    reasons = []
    metadata = metadata or {}
    # debug: compute_risk diagnostics (removed)

    edited_age_hours = 1e9 # Default to a very large number
    if last_edit:
        last_edit_dt = datetime.fromisoformat(last_edit.replace("Z", "+00:00"))
        age_delta = datetime.now(timezone.utc) - last_edit_dt
        edited_age_hours = age_delta.total_seconds() / 3600

    if provider == "airtable":
        airtable_risk, airtable_reasons = compute_risk_airtable(title, linked_count, edited_age_hours)
        risk_score += airtable_risk
        reasons.extend(airtable_reasons)
    elif provider == "github":
        # GitHub operation-based risk scoring
        object_type = metadata.get("object")  # "repository", "branch", "merge"
        operation_type = metadata.get("operation_type")  # Custom operation marker
        
        # HIGH RISK: Irreversible operations
        if operation_type == "delete_repo" or object_type == "repository":
            # Repository deletion is PERMANENT and cannot be easily undone
            risk_score += 8.0
            reasons.append("github_irreversible_repo_deletion")
        elif operation_type == "force_push":
            # Force push can lose commit history
            risk_score += 7.0
            reasons.append("github_force_push_danger")
        
        # MEDIUM-HIGH RISK: Merge and branch operations
        elif object_type == "merge":
            # Merge to main/default branch
            if metadata.get("isTargetDefault"):
                risk_score += 5.0
                reasons.append("github_merge_to_main")
            else:
                risk_score += 2.0
                reasons.append("github_merge_operation")
        elif object_type == "branch" and metadata.get("isDefault"):
            # Deleting default/main branch
            risk_score += 6.0
            reasons.append("github_default_branch_deletion")
        
        # Additional 7 Critical GitHub Operations
        
        # CRITICAL: Repository Transfer (IRREVERSIBLE)
        elif operation_type in ["github_repo_transfer", "github.repo.transfer"]:
            risk_score += 10.0
            reasons.append("github_repo_transfer_irreversible")
        
        # CRITICAL: GitHub Actions Secrets (CI/CD Compromise)
        elif operation_type in ["github_secret_create", "github.actions.secret.create", "github_secret_update", "github.actions.secret.update"]:
            risk_score += 9.5
            reasons.append("github_secret_cicd_access")
            
            # Extra risk for critical secret names
            secret_name = metadata.get("secret_name", "").lower()
            if any(keyword in secret_name for keyword in ["prod", "production", "aws", "database", "db", "api_key", "private_key"]):
                risk_score += 0.5
                reasons.append("github_secret_critical_name")
        
        elif operation_type in ["github_secret_delete", "github.actions.secret.delete"]:
            risk_score += 9.0
            reasons.append("github_secret_deletion")
            
            # Extra risk for critical secret names
            secret_name = metadata.get("secret_name", "").lower()
            if any(keyword in secret_name for keyword in ["prod", "production", "aws", "database", "db"]):
                risk_score += 1.0
                reasons.append("github_secret_critical_deletion")
        
        # CRITICAL: Workflow File Modifications (Arbitrary Code Execution)
        elif operation_type in ["github_workflow_update", "github.workflow.update"]:
            risk_score += 9.0
            reasons.append("github_workflow_code_execution")
            
            # Extra risk for suspicious patterns in workflow content
            workflow_content = metadata.get("content", "").lower()
            if any(pattern in workflow_content for pattern in ["curl", "wget", "eval", "exec", "base64", "sh -c"]):
                risk_score += 1.0
                reasons.append("github_workflow_suspicious_patterns")
        
        # HIGH: Branch Protection Changes
        elif operation_type in ["github_branch_protection_update", "github.branch_protection.update"]:
            risk_score += 8.5
            reasons.append("github_branch_protection_weakening")
            
            # Extra risk for disabling reviews on main/master
            branch = metadata.get("branch", "").lower()
            required_reviews = metadata.get("required_reviews")
            if branch in ["main", "master", "prod", "production"] and required_reviews == 0:
                risk_score += 1.5
                reasons.append("github_removing_reviews_main_branch")
        
        elif operation_type in ["github_branch_protection_delete", "github.branch_protection.delete"]:
            risk_score += 9.0
            reasons.append("github_branch_protection_removal")
            
            # Extra risk for deleting protection on main/master
            branch = metadata.get("branch", "").lower()
            if branch in ["main", "master", "prod", "production"]:
                risk_score += 1.0
                reasons.append("github_removing_protection_main_branch")
        
        # CRITICAL: Repository Visibility Change (Public Exposure)
        elif operation_type in ["github_repo_visibility_change", "github.repo.visibility.change"]:
            private = metadata.get("private")
            
            if private is False:  # Making repo public
                risk_score += 10.0
                reasons.append("github_making_repo_public_permanent")
            else:  # Making repo private
                risk_score += 5.0
                reasons.append("github_making_repo_private")
        
        # Additional GitHub heuristics
        if title and any(k in title.lower() for k in ["prod", "infra", "deploy"]):
            risk_score += 0.30
            reasons.append("github_name_keywords")
        if edited_age_hours < 24:
            risk_score += 0.20
            reasons.append("github_recent_commit")
    else:
        # Notion specific heuristics (and general for others if not overridden)
        if title and ("finance" in title.lower() or "budget" in title.lower()):
            risk_score += 0.5
            reasons.append("title_keywords")

        if blocks_count > 100:
            risk_score += 0.2
            reasons.append("large_item")

        if last_edit:
            if edited_age_hours < 24: # Edited in last 24 hours
                risk_score += 0.3
                reasons.append("recently_edited")

    return risk_score, reasons

def human_preview(provider: str, title: str | None, item_type: str, blocks_count: int, last_edited_time: str | None, score: float, reasons: list[str], linked_count: int = 0, operation_type: str | None = None) -> str:
    preview = ""
    if provider == "airtable":
        preview += f"⚠️ ARCHIVE PREVIEW (Airtable)\n"
        preview += f"Record: \"{title or '(untitled)'}\"\n"
        preview += f"Linked fields: ~{linked_count}\n"
        if last_edited_time:
            preview += f"Last modified: {last_edited_time}\n"
        preview += f"Risk Score: {score:.2f} ({'HIGH' if score > 0.5 else 'MEDIUM' if score > 0.2 else 'LOW'})\n"
    elif provider == "github":
        # Show operation-specific header
        op_labels = {
            "branch_delete": "🗑️ DELETE BRANCH",
            "force_push": "⚠️ FORCE PUSH",
            "delete_repo": "🔴 DELETE REPOSITORY",
            "merge": "🔀 MERGE",
            "archive": "📦 ARCHIVE REPO",
        }
        op_label = op_labels.get(operation_type or "", "⚠️ GITHUB OPERATION")
        preview += f"{op_label}\n"
        preview += f"Target: {title or '(unknown)'}\n"
        if last_edited_time:
            preview += f"Last activity: {last_edited_time}\n"
        preview += f"Risk Score: {score:.2f} ({'HIGH' if score > 0.5 else 'MEDIUM' if score > 0.2 else 'LOW'})\n"
    else:
        preview += f"⚠️ ARCHIVE PREVIEW ({item_type.upper()})\n"
        preview += f"Title: \"{title or '(untitled)'}\"\n"
        preview += f"Blocks: ~{blocks_count}\n"
        if last_edited_time:
            preview += f"Last modified: {last_edited_time}\n"
        preview += f"Risk Score: {score:.2f} ({'HIGH' if score > 0.5 else 'MEDIUM' if score > 0.2 else 'LOW'})\n"

    if reasons:
        preview += f"Reasons: {', '.join(reasons)}\n"
    return preview


def requires_approval(score: float, max_risk: float | None) -> bool:
    if max_risk is None:
        return score >= 0.75
    return score > float(max_risk)
