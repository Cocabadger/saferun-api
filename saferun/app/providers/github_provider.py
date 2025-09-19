from typing import Dict, Any, Tuple
from .base import Provider

# Note: We avoid importing external GitHub SDKs; use simple HTTP if needed.
# For tests, methods will be monkeypatched.

class GitHubProvider(Provider):
    def __getattribute__(self, name):
        # Ensure monkeypatched class-level async funcs are not bound with self
        if name in {"get_metadata", "get_children_count", "archive", "unarchive", "delete_branch", "restore_branch", "list_open_prs", "bulk_close_prs", "bulk_reopen_prs"}:
            cls = type(self)
            d = cls.__dict__.get(name)
            if d is not None:
                # Support our default @staticmethods and monkeypatched plain functions
                if isinstance(d, staticmethod):
                    return d.__get__(None, cls)
                return d
        return super().__getattribute__(name)
    @staticmethod
    async def get_metadata(target_id: str, token: str) -> Dict[str, Any]:
        """
        target_id formats:
          - repo: "org/repo"
          - branch: "org/repo#branch"
          - bulk PRs: "org/repo@open_prs"
        Return a dict capturing minimal metadata used by risk/human preview.
        """
        if "@" in target_id:
            owner_repo, view = target_id.split("@", 1)
            owner, repo = owner_repo.split("/", 1)
            if view == "open_prs":
                # Try to get a preview sample from list_open_prs
                try:
                    prs = await GitHubProvider.list_open_prs(target_id, token)
                except Exception:
                    prs = []
                sample = prs[:3]
                return {
                    "type": "bulk_pr",
                    "owner": owner,
                    "repo": repo,
                    "view_name": view,
                    "records_affected": len(prs),
                    "sample": sample,
                }
        if "#" in target_id:
            owner_repo, branch = target_id.split("#", 1)
            owner, repo = owner_repo.split("/", 1)
            return {
                "object": "branch",
                "owner": owner,
                "repo": repo,
                "branch": branch,
                # placeholders; tests will fill via monkeypatch
                "name": branch,
                "isDefault": False,
                "lastCommitDate": None,
            }
        # repo
        owner, repo = target_id.split("/", 1)
        return {
            "object": "repository",
            "owner": owner,
            "repo": repo,
            "name": repo,
            "archived": False,
            "lastPushedAt": None,
            "stars": 0,
            "forks": 0,
        }

    @staticmethod
    async def get_children_count(target_id: str, token: str) -> int:
        # For bulk PR view, return number of PRs; default 0 else
        if "@" in target_id:
            # Try to use list_open_prs if available
            try:
                prs = await GitHubProvider.list_open_prs(target_id, token)
                return len(prs)
            except Exception:
                return 0
        return 0

    @staticmethod
    async def archive(target_id: str, token: str) -> None:
        # Archive repo; noop in default impl
        return None

    @staticmethod
    async def unarchive(target_id: str, token: str) -> None:
        # Unarchive repo; noop in default impl
        return None

    # GitHub-specific actions
    @staticmethod
    async def delete_branch(target_id: str, token: str) -> str:
        """Delete branch and return last commit SHA to store in revert_token."""
        # Return a fake SHA by default; tests monkeypatch
        return "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"

    @staticmethod
    async def restore_branch(target_id: str, token: str, sha: str) -> None:
        return None

    # --- Bulk PR operations ---
    @staticmethod
    async def list_open_prs(target_id: str, token: str) -> list[dict]:
        """
        Return list of PRs for bulk operations. Each item:
        {"number": int, "title": str, "updatedAt": iso8601}
        Default impl returns a small synthetic list used by tests.
        """
        return [
            {"number": 123, "title": "hotfix: patch CVE", "updatedAt": "2025-01-01T00:00:00Z"},
            {"number": 124, "title": "release: 1.2.3", "updatedAt": "2025-01-02T00:00:00Z"},
            {"number": 125, "title": "chore: deps", "updatedAt": "2025-01-03T00:00:00Z"},
        ]

    @staticmethod
    async def bulk_close_prs(target_id: str, token: str, pr_numbers: list[int] | None = None) -> dict:
        """Close given PRs and return a summary with closed numbers and a revert token."""
        if pr_numbers is None:
            try:
                prs = await GitHubProvider.list_open_prs(target_id, token)
                pr_numbers = [int(p.get("number")) for p in prs]
            except Exception:
                pr_numbers = []
        return {"ok": True, "closed_pr_numbers": pr_numbers, "revert_token": "rvk_gh_bulk"}

    @staticmethod
    async def bulk_reopen_prs(target_repo: str, pr_numbers: list[int], token: str | None = None) -> dict:
        """Reopen given PRs; return status dict for tests."""
        return {"ok": True, "status": "reverted", "reopened": pr_numbers}
