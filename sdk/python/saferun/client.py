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

    def delete_github_repo(
        self,
        repo: str,
        github_token: str,
        reason: Optional[str] = None,
        webhook_url: Optional[str] = None,
        policy: Optional[Dict[str, Any]] = None,
    ) -> DryRunResult:
        payload = {
            "token": github_token,
            "target_id": repo,
            "reason": reason or "Delete repository (PERMANENT - cannot be undone)",
            "webhook_url": webhook_url,
            "policy": policy,
        }
        return self.dry_run("github_delete_repo", payload)

    def force_push_github(
        self,
        repo: str,
        branch: str,
        github_token: str,
        reason: Optional[str] = None,
        webhook_url: Optional[str] = None,
        policy: Optional[Dict[str, Any]] = None,
    ) -> DryRunResult:
        payload = {
            "token": github_token,
            "target_id": f"{repo}#{branch}",
            "reason": reason,
            "webhook_url": webhook_url,
            "policy": policy,
        }
        return self.dry_run("github_force_push", payload)

    def merge_github(
        self,
        repo: str,
        source_branch: str,
        target_branch: str,
        github_token: str,
        reason: Optional[str] = None,
        webhook_url: Optional[str] = None,
        policy: Optional[Dict[str, Any]] = None,
    ) -> DryRunResult:
        payload = {
            "token": github_token,
            "target_id": repo,
            "source_branch": source_branch,
            "target_branch": target_branch,
            "reason": reason,
            "webhook_url": webhook_url,
            "policy": policy,
        }
        return self.dry_run("github_merge", payload)

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

    # Phase 1.4 - Advanced GitHub Operations

    def transfer_repository(
        self,
        repo: str,
        new_owner: str,
        github_token: str,
        webhook_url: Optional[str] = None,
        policy: Optional[Dict[str, Any]] = None,
    ) -> DryRunResult:
        """
        Transfer repository to another owner/organization.
        
        Args:
            repo: Repository in format "owner/repo"
            new_owner: Target owner username or organization name
            github_token: GitHub personal access token
            webhook_url: Optional webhook URL for notifications
            policy: Optional custom policy rules
            
        Returns:
            DryRunResult with approval details
        """
        payload = {
            "token": github_token,
            "target_id": repo,
            "new_owner": new_owner,
            "webhook_url": webhook_url,
            "policy": policy,
        }
        return self.dry_run("github_transfer_repository", payload)

    def create_or_update_secret(
        self,
        repo: str,
        secret_name: str,
        secret_value: str,
        github_token: str,
        webhook_url: Optional[str] = None,
        policy: Optional[Dict[str, Any]] = None,
    ) -> DryRunResult:
        """
        Create or update GitHub Actions secret.
        
        Args:
            repo: Repository in format "owner/repo"
            secret_name: Name of the secret (e.g., "API_KEY")
            secret_value: Value of the secret
            github_token: GitHub personal access token
            webhook_url: Optional webhook URL for notifications
            policy: Optional custom policy rules
            
        Returns:
            DryRunResult with approval details
        """
        payload = {
            "token": github_token,
            "target_id": repo,
            "secret_name": secret_name,
            "secret_value": secret_value,
            "webhook_url": webhook_url,
            "policy": policy,
        }
        return self.dry_run("github_create_secret", payload)

    def delete_secret(
        self,
        repo: str,
        secret_name: str,
        github_token: str,
        webhook_url: Optional[str] = None,
        policy: Optional[Dict[str, Any]] = None,
    ) -> DryRunResult:
        """
        Delete GitHub Actions secret.
        
        Args:
            repo: Repository in format "owner/repo"
            secret_name: Name of the secret to delete
            github_token: GitHub personal access token
            webhook_url: Optional webhook URL for notifications
            policy: Optional custom policy rules
            
        Returns:
            DryRunResult with approval details
        """
        payload = {
            "token": github_token,
            "target_id": repo,
            "secret_name": secret_name,
            "webhook_url": webhook_url,
            "policy": policy,
        }
        return self.dry_run("github_delete_secret", payload)

    def update_workflow_file(
        self,
        repo: str,
        workflow_path: str,
        content: str,
        github_token: str,
        branch: str = "main",
        commit_message: Optional[str] = None,
        webhook_url: Optional[str] = None,
        policy: Optional[Dict[str, Any]] = None,
    ) -> DryRunResult:
        """
        Update GitHub Actions workflow file.
        
        Args:
            repo: Repository in format "owner/repo"
            workflow_path: Path to workflow file (e.g., ".github/workflows/ci.yml")
            content: New content for the workflow file
            github_token: GitHub personal access token
            branch: Branch to commit to (default: "main")
            commit_message: Optional commit message
            webhook_url: Optional webhook URL for notifications
            policy: Optional custom policy rules
            
        Returns:
            DryRunResult with approval details
        """
        payload = {
            "token": github_token,
            "target_id": repo,
            "workflow_path": workflow_path,
            "content": content,
            "branch": branch,
            "commit_message": commit_message or f"Update workflow {workflow_path}",
            "webhook_url": webhook_url,
            "policy": policy,
        }
        return self.dry_run("github_update_workflow", payload)

    def update_branch_protection(
        self,
        repo: str,
        branch: str,
        github_token: str,
        required_reviews: Optional[int] = None,
        require_code_owner_reviews: Optional[bool] = None,
        dismiss_stale_reviews: Optional[bool] = None,
        require_status_checks: Optional[bool] = None,
        status_checks: Optional[list] = None,
        enforce_admins: Optional[bool] = None,
        webhook_url: Optional[str] = None,
        policy: Optional[Dict[str, Any]] = None,
    ) -> DryRunResult:
        """
        Update branch protection rules.
        
        Args:
            repo: Repository in format "owner/repo"
            branch: Branch name (e.g., "main")
            github_token: GitHub personal access token
            required_reviews: Number of required reviews (0-6)
            require_code_owner_reviews: Require code owner review
            dismiss_stale_reviews: Dismiss stale reviews on push
            require_status_checks: Require status checks to pass
            status_checks: List of required status check names
            enforce_admins: Enforce restrictions for admins
            webhook_url: Optional webhook URL for notifications
            policy: Optional custom policy rules
            
        Returns:
            DryRunResult with approval details
        """
        payload = {
            "token": github_token,
            "target_id": f"{repo}#{branch}",
            "required_reviews": required_reviews,
            "require_code_owner_reviews": require_code_owner_reviews,
            "dismiss_stale_reviews": dismiss_stale_reviews,
            "require_status_checks": require_status_checks,
            "status_checks": status_checks,
            "enforce_admins": enforce_admins,
            "webhook_url": webhook_url,
            "policy": policy,
        }
        return self.dry_run("github_update_branch_protection", payload)

    def delete_branch_protection(
        self,
        repo: str,
        branch: str,
        github_token: str,
        webhook_url: Optional[str] = None,
        policy: Optional[Dict[str, Any]] = None,
    ) -> DryRunResult:
        """
        Delete branch protection rules.
        
        Args:
            repo: Repository in format "owner/repo"
            branch: Branch name (e.g., "main")
            github_token: GitHub personal access token
            webhook_url: Optional webhook URL for notifications
            policy: Optional custom policy rules
            
        Returns:
            DryRunResult with approval details
        """
        payload = {
            "token": github_token,
            "target_id": f"{repo}#{branch}",
            "webhook_url": webhook_url,
            "policy": policy,
        }
        return self.dry_run("github_delete_branch_protection", payload)

    def change_repository_visibility(
        self,
        repo: str,
        private: bool,
        github_token: str,
        webhook_url: Optional[str] = None,
        policy: Optional[Dict[str, Any]] = None,
    ) -> DryRunResult:
        """
        Change repository visibility (public ↔ private).
        
        Args:
            repo: Repository in format "owner/repo"
            private: True for private, False for public
            github_token: GitHub personal access token
            webhook_url: Optional webhook URL for notifications
            policy: Optional custom policy rules
            
        Returns:
            DryRunResult with approval details
        """
        payload = {
            "token": github_token,
            "target_id": repo,
            "private": private,
            "webhook_url": webhook_url,
            "policy": policy,
        }
        return self.dry_run("github_change_visibility", payload)

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
