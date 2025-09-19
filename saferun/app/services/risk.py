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

def compute_risk(provider: str, title: str, blocks_count: int, last_edit: str | None, linked_count: int = 0) -> tuple[float, list[str]]:
    risk_score = 0.0
    reasons = []
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
        # GitHub heuristics
        if title and any(k in title.lower() for k in ["prod", "infra", "deploy"]):
            risk_score += 0.30
            reasons.append("github_name_keywords")
        # We pass default branch as blocks_count sentinel -1? Keep separate: rely on reasons injection elsewhere.
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

def human_preview(provider: str, title: str | None, item_type: str, blocks_count: int, last_edited_time: str | None, score: float, reasons: list[str], linked_count: int = 0) -> str:
    preview = ""
    if provider == "airtable":
        preview += f"⚠️ ARCHIVE PREVIEW (Airtable)\n"
        preview += f"Record: \"{title or '(untitled)'}\"\n"
        preview += f"Linked fields: ~{linked_count}\n"
        if last_edited_time:
            preview += f"Last modified: {last_edited_time}\n"
        preview += f"Risk Score: {score:.2f} ({'HIGH' if score > 0.5 else 'MEDIUM' if score > 0.2 else 'LOW'})\n"
    elif provider == "github":
        preview += f"⚠️ ARCHIVE PREVIEW (GitHub)\n"
        # For repos, title is repo name; for branches include branch in reasons context
        preview += f"Repo: {title or '(unknown)'}\n"
        if last_edited_time:
            preview += f"Last pushed/commit: {last_edited_time}\n"
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
