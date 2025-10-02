"""Data models for SafeRun SDK."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, TYPE_CHECKING


if TYPE_CHECKING:
    from .client import SafeRunClient


@dataclass
class ApplyResult:
    """Result of applying a change."""

    change_id: str
    status: str
    revert_token: Optional[str]
    applied_at: datetime
    _client: "SafeRunClient"  # type: ignore[name-defined]

    def revert(self) -> "RevertResult":
        if not self.revert_token:
            raise ValueError("Revert token is not available for this change")
        return self._client.revert_change(self.revert_token)


@dataclass
class RevertResult:
    """Result of reverting a change."""

    revert_token: str
    status: str
    reverted_at: datetime


@dataclass
class ApprovalStatus:
    """Status of approval."""

    approved: bool
    rejected: bool
    expired: bool
    pending: bool


@dataclass
class DryRunResult:
    """Result of dry-run operation."""

    change_id: str
    needs_approval: bool
    approval_url: Optional[str]
    reject_url: Optional[str]
    risk_score: float
    reasons: List[str]
    human_preview: str
    expires_at: datetime
    _client: "SafeRunClient"  # type: ignore[name-defined]

    def approve(self) -> ApplyResult:
        return self._client.apply_change(self.change_id, approval=True)

    def reject(self) -> None:
        raise NotImplementedError("SafeRun API currently handles rejection via approve endpoint")

    def get_status(self) -> ApprovalStatus:
        return self._client.get_approval_status(self.change_id)


