from typing import Dict, Any, List, Tuple

DEFAULT_POLICY = {
    "version": "1.0",
    "rules": [
        {"type": "max_risk", "value": 0.7, "action": "require_approval"},
        {"type": "block_keywords", "value": ["contract", "pricing"], "action": "require_approval"},
        {"type": "edited_within_hours", "value": 2, "action": "require_approval"},
        {"type": "max_blocks", "value": 200, "action": "require_approval"},
    ],
    "mode": "ANY"  # ANY | ALL
}

def evaluate(artifact: Dict[str, Any], ctx: Dict[str, Any], policy: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Return (requires_approval, reasons)"""
    rules = policy.get("rules", [])
    mode = policy.get("mode", "ANY").upper()
    hits: List[str] = []

    risk = float(ctx.get("risk_score", 0.0))
    title = (ctx.get("title") or "").lower()
    blocks = int(ctx.get("blocks_count") or 0)
    edited_age_h = float(ctx.get("edited_age_hours") or 1e9)

    for r in rules:
        t, v, act = r.get("type"), r.get("value"), r.get("action", "require_approval")
        matched = False
        if t == "max_risk" and risk > float(v): matched = True
        elif t == "block_keywords" and any(k.lower() in title for k in v or []): matched = True
        elif t == "edited_within_hours" and edited_age_h <= float(v): matched = True
        elif t == "max_blocks" and blocks > int(v): matched = True
        elif t == "min_blocks" and blocks < int(v): matched = True
        elif t == "require_db_parent" and ctx.get("parent_type") != "database": matched = True

        if matched and act == "require_approval":
            hits.append(f"{t}:{v}")

    if mode == "ALL":
        return (len(hits) == len(rules) and len(rules) > 0, hits)
    # ANY (default)
    return (len(hits) > 0, hits)