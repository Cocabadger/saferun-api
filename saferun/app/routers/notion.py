from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
import asyncio
from ..notify import notifier
from ..models.contracts import DryRunNotionArchiveRequest, DryRunNotionArchiveResponse
from ..services.dryrun import build_dryrun
from .. import db_adapter as db
from .. import storage as storage_manager
# Expose runtime wrappers for notion helpers so tests can monkeypatch either
# the service functions or these wrappers directly.
async def get_page_last_edited(page_id: str, token: str, notion_version: str | None = None):
    from ..services.notion_api import get_page_last_edited as _get
    return await _get(page_id, token, notion_version)


async def patch_page_archive(page_id: str, token: str, archived: bool, notion_version: str | None = None):
    from ..services.notion_api import patch_page_archive as _patch
    return await _patch(page_id, token, archived, notion_version)
import uuid
from datetime import datetime, timezone

from .auth import verify_api_key

router = APIRouter(prefix="/v1", tags=["Archive"], dependencies=[Depends(verify_api_key)]) 


@router.post("/dry-run/notion.page.archive", response_model=DryRunNotionArchiveResponse)
async def dry_run_notion_archive(payload: DryRunNotionArchiveRequest, api_key: str = Depends(verify_api_key)):
    if not payload.notion_token or not payload.page_id:
        raise HTTPException(status_code=400, detail="notion_token and page_id are required")
    try:
        from ..models.contracts import DryRunArchiveRequest
        generic = DryRunArchiveRequest(
            token=payload.notion_token,
            target_id=payload.page_id,
            provider="notion",
            policy=payload.policy,
            webhook_url=payload.webhook_url
        )
        resp = await build_dryrun(generic, api_key=api_key)
        return resp
    except Exception as e:
        msg = str(e)
        if 'object_not_found' in msg or 'Could not find block with ID' in msg:
            # Return a structured non-error response so client can surface actionable remediation
            from ..models.contracts import DryRunArchiveResponse, TargetRef, Summary, DiffUnit
            from ..models.contracts import new_change_id, expiry
            return DryRunArchiveResponse(
                status="not_shared",
                change_id=new_change_id(),
                target=TargetRef(provider="notion", target_id=payload.page_id, type="page"),
                summary=Summary(title=None),
                diff=[],
                risk_score=0.0,
                reasons=["notion_page_not_shared"],
                requires_approval=False,
                human_preview="Notion page not shared with integration. Share the page to the integration then retry.",
                telemetry={"note":"notion:not_shared"},
                apply=False,
                note="Page not shared with integration",
                expires_at=expiry(),
            )
        raise HTTPException(status_code=502, detail=f"Notion API error: {e}")
