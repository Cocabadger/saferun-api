from .base import Provider
from typing import Dict, Any, Optional, Tuple
import httpx
import time

NOTION_API = "https://api.notion.com/v1"
DEFAULT_VERSION = "2022-06-28"

async def _timed_httpx(client_call):
    t0 = time.perf_counter()
    resp = await client_call()
    t1 = time.perf_counter()
    ms = int((t1 - t0) * 1000)
    if resp.status_code >= 400:
        raise RuntimeError(f"Notion API Error {resp.status_code}: {resp.text}")
    return resp.json(), ms

def parent_type_from(page_json: dict) -> str:
    p = page_json.get("parent", {})
    if "workspace" in p and p["workspace"]: return "workspace"
    if "database_id" in p: return "database"
    if "page_id" in p: return "page"
    return "unknown"

def detect_type_from(page_json: dict) -> str:
    p = page_json.get("parent", {})
    return "db_item" if "database_id" in p else "page"

def extract_title(page_json: dict) -> str | None:
    props = page_json.get("properties", {})
    for v in props.values():
        if isinstance(v, dict) and v.get("type") == "title":
            rich = v.get("title") or []
            if rich and isinstance(rich, list):
                plain = "".join([x.get("plain_text", "") for x in rich])
                return plain or None
    return None

class NotionProvider(Provider):
    async def _get_page_raw(self, target_id: str, token: str) -> Tuple[Dict[str, Any], int]:
        headers = {
            "Authorization": f"Bearer {token}",
            "Notion-Version": DEFAULT_VERSION,
        }
        async with httpx.AsyncClient(timeout=15) as client:
            return await _timed_httpx(lambda: client.get(f"{NOTION_API}/pages/{target_id}", headers=headers))

    async def get_metadata(self, target_id: str, token: str) -> Dict[str, Any]:
        page_data, _ = await self._get_page_raw(target_id, token)
        return page_data

    async def get_children_count(self, target_id: str, token: str) -> int:
        headers = {
            "Authorization": f"Bearer {token}",
            "Notion-Version": DEFAULT_VERSION,
        }
        async with httpx.AsyncClient(timeout=15) as client:
            data, _ = await _timed_httpx(lambda: client.get(f"{NOTION_API}/blocks/{target_id}/children", params={"page_size": 50}, headers=headers))
            return len(data.get("results", []))

    async def _patch_page(self, target_id: str, token: str, payload: Dict[str, Any]) -> None:
        headers = {
            "Authorization": f"Bearer {token}",
            "Notion-Version": DEFAULT_VERSION,
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=15) as client:
            await _timed_httpx(lambda: client.patch(f"{NOTION_API}/pages/{target_id}", headers=headers, json=payload))

    async def archive(self, target_id: str, token: str) -> None:
        await self._patch_page(target_id, token, {"archived": True})

    async def unarchive(self, target_id: str, token: str) -> None:
        await self._patch_page(target_id, token, {"archived": False})