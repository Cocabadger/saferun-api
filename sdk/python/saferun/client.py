"""SafeRun API client."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional
import time

import requests

from .constants import (
    APPLY_ENDPOINT,
    DEFAULT_API_URL,
    DEFAULT_MAX_RETRIES,
    DEFAULT_TIMEOUT,
    DRY_RUN_ENDPOINTS,
    REVERT_ENDPOINT,
)
from .exceptions import SafeRunAPIError, SafeRunApprovalTimeout
from .models import ApplyResult, ApprovalStatus, DryRunResult, RevertResult


class SafeRunClient:
    """Client for interacting with SafeRun API."""

    def __init__(
        self,
        api_key: str,
        api_url: str = DEFAULT_API_URL,
        timeout: int = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        self.api_key = api_key
        self.api_url = api_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Content-Type": "application/json",
                "X-API-Key": api_key,
            }
        )

    def archive_github_repo(
        self,
        repo: str,
        github_token: str,
        webhook_url: Optional[str] = None,
        policy: Optional[Dict[str, Any]] = None,
    ) -> DryRunResult:
        payload = {
            "token": github_token,
            "target_id": repo,
            "webhook_url": webhook_url,
            "policy": policy,
        }
        return self.dry_run("github_archive_repo", payload)

    def delete_github_branch(
        self,
        repo: str,
        branch: str,
        github_token: str,
        webhook_url: Optional[str] = None,
        policy: Optional[Dict[str, Any]] = None,
    ) -> DryRunResult:
        payload = {
            "token": github_token,
            "target_id": f"{repo}#{branch}",
            "webhook_url": webhook_url,
            "policy": policy,
        }
        return self.dry_run("github_delete_branch", payload)

    def bulk_close_github_prs(
        self,
        repo: str,
        github_token: str,
        view: Optional[str] = None,
        webhook_url: Optional[str] = None,
        policy: Optional[Dict[str, Any]] = None,
    ) -> DryRunResult:
        target = f"{repo}@{view}" if view else repo
        payload = {
            "token": github_token,
            "target_id": target,
            "webhook_url": webhook_url,
            "policy": policy,
        }
        return self.dry_run("github_bulk_close_prs", payload)

    def archive_notion_page(
        self,
        page_id: str,
        notion_token: str,
        webhook_url: Optional[str] = None,
        policy: Optional[Dict[str, Any]] = None,
    ) -> DryRunResult:
        payload = {
            "notion_token": notion_token,
            "page_id": page_id,
            "webhook_url": webhook_url,
            "policy": policy,
        }
        return self.dry_run("notion_archive_page", payload)

    def dry_run(self, operation: str, payload: Dict[str, Any]) -> DryRunResult:
        endpoint = DRY_RUN_ENDPOINTS.get(operation)
        if not endpoint:
            raise ValueError(f"Unsupported operation: {operation}")
        data = self._post(endpoint, payload)
        return self._parse_dry_run(data)

    def apply_change(self, change_id: str, approval: bool = True) -> ApplyResult:
        payload = {"change_id": change_id, "approval": approval}
        data = self._post(APPLY_ENDPOINT, payload)
        return self._parse_apply(data)

    def revert_change(self, revert_token: str) -> RevertResult:
        payload = {"revert_token": revert_token}
        data = self._post(REVERT_ENDPOINT, payload)
        return self._parse_revert(data)

    def get_approval_status(self, change_id: str) -> ApprovalStatus:
        raise NotImplementedError("Approval status endpoint not yet implemented")

    def wait_for_approval(
        self,
        change_id: str,
        timeout: int = 300,
        poll_interval: int = 2,
    ) -> ApprovalStatus:
        elapsed = 0
        while elapsed < timeout:
            try:
                result = self.apply_change(change_id, approval=True)
                return ApprovalStatus(
                    approved=result.status in {"applied", "already_applied"},
                    rejected=False,
                    expired=False,
                    pending=False,
                )
            except SafeRunAPIError as exc:
                if exc.status_code in (403, 409):
                    time.sleep(poll_interval)
                    elapsed += poll_interval
                    continue
                raise
        raise SafeRunApprovalTimeout(change_id, timeout)

    def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.api_url}{path}"
        attempt = 0
        last_error: Exception | None = None
        while attempt < self.max_retries:
            try:
                response = self.session.post(url, json=payload, timeout=self.timeout)
                if response.status_code >= 400:
                    raise SafeRunAPIError(response.status_code, response.text)
                return response.json()
            except Exception as exc:
                last_error = exc
                attempt += 1
                if attempt >= self.max_retries:
                    raise exc
                time.sleep(min(5, 2 ** attempt))
        if last_error:
            raise last_error
        raise RuntimeError("Unexpected error performing SafeRun request")

    def _parse_dry_run(self, data: Dict[str, Any]) -> DryRunResult:
        return DryRunResult(
            change_id=data.get("change_id", ""),
            needs_approval=data.get("requires_approval", False),
            approval_url=data.get("approve_url"),
            reject_url=data.get("reject_url"),
            risk_score=float(data.get("risk_score", 0.0)),
            reasons=data.get("reasons", []),
            human_preview=data.get("human_preview", ""),
            expires_at=self._parse_datetime(data.get("expires_at")),
            _client=self,
        )

    def _parse_apply(self, data: Dict[str, Any]) -> ApplyResult:
        return ApplyResult(
            change_id=data.get("change_id", ""),
            status=data.get("status", ""),
            revert_token=data.get("revert_token"),
            applied_at=self._parse_datetime(data.get("applied_at")),
            _client=self,
        )

    def _parse_revert(self, data: Dict[str, Any]) -> RevertResult:
        return RevertResult(
            revert_token=data.get("revert_token", ""),
            status=data.get("status", ""),
            reverted_at=self._parse_datetime(data.get("reverted_at")),
        )

    @staticmethod
    def _parse_datetime(value: Optional[str]) -> datetime:
        if not value:
            return datetime.now(timezone.utc)
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return datetime.now(timezone.utc)
