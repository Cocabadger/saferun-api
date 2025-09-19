import os, json, hmac, hashlib, asyncio
from typing import Dict, Any, Optional
import httpx

TIMEOUT = float(os.getenv("NOTIFY_TIMEOUT_MS", "2000")) / 1000.0
RETRY = int(os.getenv("NOTIFY_RETRY", "1"))
SLACK_URL = os.getenv("SLACK_WEBHOOK_URL")
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
                return await coro()
            except Exception as e:
                last = e
                await asyncio.sleep(0.3 * (2 ** attempt))
        # swallow error (non-blocking), could log
        return None

    async def send_slack(self, payload: Dict[str, Any], text: str) -> None:
        if not SLACK_URL: return
        body = {"text": text, "attachments": [{"text": json.dumps(payload)[:9500]}]}
        async def do(): return await self.client.post(SLACK_URL, json=body)
        await self._retry(do)

    async def send_webhook(self, payload: Dict[str, Any]) -> None:
        if not WH_URL: return
        body = json.dumps(payload).encode("utf-8")
        headers = {}
        if WH_SECRET:
            sig = hmac.new(WH_SECRET.encode(), body, hashlib.sha256).hexdigest()
            headers["X-Signature"] = sig
        async def do(): return await self.client.post(WH_URL, content=body, headers=headers)
        await self._retry(do)

    async def send_email(self, payload: Dict[str, Any], subject: str) -> None:
        # optional: implement later via aiosmtplib; keep no-op if SMTP not configured
        if not (SMTP_HOST and SMTP_FROM and SMTP_TO): return
        try:
            import aiosmtplib
        except Exception:
            return
        msg = f"Subject: {subject}\nFrom: {SMTP_FROM}\nTo: {SMTP_TO}\n\n{json.dumps(payload, indent=2)[:9000]}"
        async def do():
            return await aiosmtplib.send(
                msg, hostname=SMTP_HOST, port=SMTP_PORT or 587,
                username=SMTP_USER, password=SMTP_PASS, start_tls=True,
                sender=SMTP_FROM, recipients=[SMTP_TO]
            )
        await self._retry(do)

    async def publish(self, event: str, change: Dict[str, Any], extras: Optional[Dict[str, Any]] = None) -> None:
        payload = {
            "event": event,
            "change_id": change.get("change_id"),
            "page_id": change.get("page_id"),
            "title": change.get("title"),
            "status": change.get("status"),
            "risk_score": change.get("risk_score", 0.0),
            "requires_approval": bool(change.get("requires_approval")),
            "approve_url": (extras or {}).get("approve_url"),
            "revert_token": (extras or {}).get("revert_token"),
            "ts": change.get("ts") or change.get("created_at"),
            "meta": (extras or {}).get("meta", {}),
        }
        text_map = {
            "dry_run": ":rotating_light: [SafeRun] High-risk DRY-RUN → approval needed",
            "applied": ":white_check_mark: [SafeRun] Applied",
            "reverted": ":rewind: [SafeRun] Reverted",
            "expired": ":hourglass_flowing_sand: [SafeRun] Expired",
        }
        text = text_map.get(event, f"[SafeRun] {event}")
        # fan-out concurrently
        await asyncio.gather(
            self.send_slack(payload, text),
            self.send_webhook(payload),
            self.send_email(payload, subject=text.replace(":", "")) ,
            return_exceptions=True
        )

notifier = Notifier()
