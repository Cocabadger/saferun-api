from pydantic import BaseModel, Field
from typing import List, Literal, Optional, Dict
from datetime import datetime, timedelta, timezone
import uuid
from saferun import __version__ as SR_VERSION

ProviderLiteral = Literal["notion", "gdrive", "slack", "gsheets", "airtable", "github"]

class AirtableRecordArchiveDryRunRequest(BaseModel):
    token: str
    target_id: str  # "baseId/tableId/recordId"
    policy: Optional[Dict] = None
    webhook_url: Optional[str] = None

class AirtableBulkArchiveDryRunRequest(BaseModel):
    token: str
    target_id: str  # "baseId/tableId @viewName"
    policy: Optional[Dict] = None
    webhook_url: Optional[str] = None


class DryRunNotionArchiveRequest(BaseModel):
    notion_token: str
    page_id: str
    policy: Optional[Dict] = None
    webhook_url: Optional[str] = None
class GitHubRepoArchiveDryRunRequest(BaseModel):
    token: str
    target_id: str  # "org/repo"
    policy: Optional[Dict] = None
    webhook_url: Optional[str] = None

class GitHubBranchDeleteDryRunRequest(BaseModel):
    token: str
    target_id: str  # "org/repo#branch"
    policy: Optional[Dict] = None
    webhook_url: Optional[str] = None

class GitHubBulkClosePRsDryRunRequest(BaseModel):
    token: str
    target_id: str  # "org/repo@open_prs"
    policy: Optional[Dict] = None
    webhook_url: Optional[str] = None





class DryRunArchiveRequest(BaseModel):
    token: str
    target_id: str
    provider: ProviderLiteral
    policy: Optional[Dict] = None
    webhook_url: Optional[str] = None

class DiffUnit(BaseModel):
    op: Literal["archive", "delete_branch", "bulk_preview"]
    impact: Dict

class TargetRef(BaseModel):
    provider: ProviderLiteral
    target_id: str
    type: Literal["page", "db_item", "file", "folder", "record", "bulk_view", "repo", "branch", "bulk_pr", "channel"]

class Summary(BaseModel):
    title: Optional[str]
    parent_type: Optional[str] = None
    blocks_count: int = 0
    blocks_count_approx: bool = True
    last_edited_time: Optional[datetime] = None
    # GitHub-specific summary fields (optional)
    name: Optional[str] = None
    stars: Optional[int] = None
    forks: Optional[int] = None
    lastPushedAt: Optional[str] = None
    isDefault: Optional[bool] = None
    lastCommitDate: Optional[str] = None

class DryRunArchiveResponse(BaseModel):
    service: str = "saferun"
    version: str = SR_VERSION
    status: str = "ok"
    change_id: str
    target: TargetRef
    summary: Summary
    diff: List[DiffUnit]
    risk_score: float = Field(ge=0.0, le=1.0)
    reasons: List[str] = []
    requires_approval: bool = False
    human_preview: str
    telemetry: Dict
    approve_url: Optional[str] = None
    revert_url: Optional[str] = None
    apply: Optional[bool] = None
    note: Optional[str] = None
    records_affected: Optional[int] = None
    expires_at: datetime


def new_change_id() -> str:
    return str(uuid.uuid4())

def expiry(minutes: int = 30) -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=minutes)


# Alias the notion response to the generic dry-run response shape for now
DryRunNotionArchiveResponse = DryRunArchiveResponse