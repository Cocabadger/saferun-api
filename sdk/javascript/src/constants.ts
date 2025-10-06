export const DEFAULT_API_URL = "https://saferun-api.up.railway.app";
export const DEFAULT_TIMEOUT = 30000;
export const DEFAULT_MAX_RETRIES = 3;
export const DRY_RUN_ENDPOINTS: Record<string, string> = {
  github_archive_repo: "/v1/dry-run/github.repo.archive",
  github_delete_repo: "/v1/dry-run/github.repo.delete",
  github_delete_branch: "/v1/dry-run/github.branch.delete",
  github_bulk_close_prs: "/v1/dry-run/github.bulk.close_prs",
  github_force_push: "/v1/dry-run/github.force-push",
  github_merge: "/v1/dry-run/github.merge",
  notion_archive_page: "/v1/dry-run/notion.page.archive",
  git_operation: "/v1/dry-run/git.operation",
};
export const APPLY_ENDPOINT = "/v1/apply";
export const REVERT_ENDPOINT = "/v1/revert";
export const GIT_OPERATION_STATUS_ENDPOINT = (changeId: string) => `/v1/git/operations/${changeId}`;
export const GIT_OPERATION_CONFIRM_ENDPOINT = "/v1/git/operations/confirm";
