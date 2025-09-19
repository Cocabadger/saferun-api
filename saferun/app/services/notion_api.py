import httpx
import time
from typing import Dict, Any, Optional, Tuple

NOTION_API = "https://api.notion.com/v1"
DEFAULT_VERSION = "2025-09-03"

async def _timed(client_call):
    t0 = time.perf_counter()
    resp = await client_call()
    t1 = time.perf_counter()
    return resp, int((t1 - t0) * 1000)


async def get_page(page_id: str, token: str, notion_version: Optional[str] = None) -> Tuple[Dict[str, Any], int]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": notion_version or DEFAULT_VERSION,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        def _call():
            return client.get(f"{NOTION_API}/pages/{page_id}", headers=headers)
        r, ms = await _timed(_call)
        if r.status_code >= 400:
            raise RuntimeError(f"Notion get_page {r.status_code}: {r.text}")
        return r.json(), ms


async def get_children_count(page_id: str, token: str, notion_version: Optional[str] = None, limit: int = 50) -> Tuple[int, int]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": notion_version or DEFAULT_VERSION,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        def _call():
            return client.get(f"{NOTION_API}/blocks/{page_id}/children", params={"page_size": limit}, headers=headers)
        r, ms = await _timed(_call)
        if r.status_code >= 400:
            raise RuntimeError(f"Notion get_children {r.status_code}: {r.text}")
        data = r.json()
        results = data.get("results", [])
        return len(results), ms


async def patch_page_archive(page_id: str, token: str, archived: bool, notion_version: str | None = None) -> Tuple[Dict[str, Any], int]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": notion_version or DEFAULT_VERSION,
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        def _call():
            return client.patch(f"{NOTION_API}/pages/{page_id}", headers=headers, json={"archived": archived})
        r, ms = await _timed(_call)
        if r.status_code >= 400:
            raise RuntimeError(f"Notion patch_page {r.status_code}: {r.text}")
        return r.json(), ms


async def get_page_last_edited(page_id: str, token: str, notion_version: str | None = None) -> Tuple[Optional[str], int]:
    data, ms = await get_page(page_id, token, notion_version)
    return (data or {}).get("last_edited_time"), ms
