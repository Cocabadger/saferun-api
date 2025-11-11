"""SDK constants."""
DEFAULT_API_URL = "https://saferun-api.up.railway.app"
DEFAULT_TIMEOUT = 30
DEFAULT_MAX_RETRIES = 3
DRY_RUN_ENDPOINTS = {
    "github_archive_repo": "/v1/dry-run/github.repo.archive",
    "github_delete_repo": "/v1/dry-run/github.repo.delete",
    "github_delete_branch": "/v1/dry-run/github.branch.delete",
    "github_bulk_close_prs": "/v1/dry-run/github.bulk.close_prs",
    "github_force_push": "/v1/dry-run/github.force-push",
    "github_merge": "/v1/dry-run/github.merge",
    "notion_archive_page": "/v1/dry-run/notion.page.archive",
    # Phase 1.4 - Advanced GitHub Operations
    "github_transfer_repository": "/v1/dry-run/github.repo.transfer",
    "github_create_secret": "/v1/dry-run/github.actions.secret.create",
    "github_delete_secret": "/v1/dry-run/github.actions.secret.delete",
    "github_update_workflow": "/v1/dry-run/github.workflow.update",
    "github_update_branch_protection": "/v1/dry-run/github.branch_protection.update",
    "github_delete_branch_protection": "/v1/dry-run/github.branch_protection.delete",
    "github_change_visibility": "/v1/dry-run/github.repo.visibility.change",
}
APPLY_ENDPOINT = "/v1/apply"
REVERT_ENDPOINT = "/v1/revert"
CHANGE_STATUS_ENDPOINT = "/v1/change/{change_id}"
