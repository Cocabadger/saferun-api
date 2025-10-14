import os
from typing import Dict, Any, List

import httpx

from .base import Provider

# Note: We avoid importing external GitHub SDKs; use simple HTTP via httpx.


class GitHubProvider(Provider):
    API_BASE = os.getenv("SR_GITHUB_API_BASE", "https://api.github.com")
    USER_AGENT = os.getenv("SR_GITHUB_USER_AGENT", "SafeRun/0.20.0")
    TIMEOUT = float(os.getenv("SR_GITHUB_TIMEOUT", "15"))

    @staticmethod
    def _headers(token: str) -> Dict[str, str]:
        if not token:
            raise RuntimeError("GitHub token is required")
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": GitHubProvider.USER_AGENT,
        }

    @staticmethod
    async def _request(method: str, path: str, token: str, params: Dict[str, Any] | None = None, json_payload: Dict[str, Any] | None = None) -> Dict[str, Any] | None:
        url = f"{GitHubProvider.API_BASE}{path}"
        async with httpx.AsyncClient(timeout=GitHubProvider.TIMEOUT) as client:
            response = await client.request(
                method,
                url,
                headers=GitHubProvider._headers(token),
                params=params,
                json=json_payload,
            )

        if response.status_code == 204:
            return None

        if response.status_code >= 400:
            message = response.text
            rate_remaining = response.headers.get("X-RateLimit-Remaining")
            if rate_remaining == "0":
                reset = response.headers.get("X-RateLimit-Reset")
                message = f"rate limit exceeded (reset={reset})"
            raise RuntimeError(f"GitHub API {response.status_code}: {message}")

        return response.json()

    @staticmethod
    def _parse_target(target_id: str) -> Dict[str, Any]:
        if "@" in target_id:
            owner_repo, view = target_id.split("@", 1)
            owner, repo = owner_repo.split("/", 1)
            return {"kind": "bulk", "view": view, "owner": owner, "repo": repo}
        if "#" in target_id:
            owner_repo, ref = target_id.split("#", 1)
            owner, repo = owner_repo.split("/", 1)
            # Check if it's a merge operation (source→target)
            if "→" in ref:
                source, target = ref.split("→", 1)
                return {"kind": "merge", "owner": owner, "repo": repo, "source_branch": source, "target_branch": target}
            # Otherwise it's a branch reference
            return {"kind": "branch", "owner": owner, "repo": repo, "branch": ref}
        owner, repo = target_id.split("/", 1)
        return {"kind": "repo", "owner": owner, "repo": repo}

    @staticmethod
    async def _get_repo(owner: str, repo: str, token: str) -> Dict[str, Any]:
        data = await GitHubProvider._request("GET", f"/repos/{owner}/{repo}", token)
        if not isinstance(data, dict):
            raise RuntimeError("Unexpected response from GitHub repo metadata")
        return data

    @staticmethod
    async def _get_branch(owner: str, repo: str, branch: str, token: str) -> Dict[str, Any]:
        data = await GitHubProvider._request("GET", f"/repos/{owner}/{repo}/branches/{branch}", token)
        if not isinstance(data, dict):
            raise RuntimeError("Unexpected response from GitHub branch metadata")
        return data

    def __getattribute__(self, name):
        # Ensure monkeypatched class-level async funcs are not bound with self
        if name in {"get_metadata", "get_children_count", "archive", "unarchive", "delete_branch", "restore_branch", "list_open_prs", "bulk_close_prs", "bulk_reopen_prs", "force_push", "merge"}:
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
        """Return metadata for repository/branch/bulk PR/merge targets."""
        info = GitHubProvider._parse_target(target_id)

        if info["kind"] == "bulk":
            prs = await GitHubProvider.list_open_prs(target_id, token)
            sample = [f"#{p['number']} \"{p['title']}\"" for p in prs[:3]]
            return {
                "type": "bulk_pr",
                "owner": info["owner"],
                "repo": info["repo"],
                "view_name": info["view"],
                "records_affected": len(prs),
                "sample": sample,
            }

        repo_data = await GitHubProvider._get_repo(info["owner"], info["repo"], token)

        if info["kind"] == "merge":
            # Get metadata for both source and target branches
            source_data = await GitHubProvider._get_branch(info["owner"], info["repo"], info["source_branch"], token)
            target_data = await GitHubProvider._get_branch(info["owner"], info["repo"], info["target_branch"], token)
            return {
                "object": "merge",
                "owner": info["owner"],
                "repo": info["repo"],
                "source_branch": info["source_branch"],
                "target_branch": info["target_branch"],
                "source_sha": source_data.get("commit", {}).get("sha"),
                "target_sha": target_data.get("commit", {}).get("sha"),
                "isTargetDefault": repo_data.get("default_branch") == info["target_branch"],
            }

        if info["kind"] == "branch":
            branch_data = await GitHubProvider._get_branch(info["owner"], info["repo"], info["branch"], token)
            commit = branch_data.get("commit", {}) or {}
            return {
                "object": "branch",
                "owner": info["owner"],
                "repo": info["repo"],
                "branch": info["branch"],
                "name": branch_data.get("name", info["branch"]),
                "isDefault": repo_data.get("default_branch") == info["branch"],
                "lastCommitDate": commit.get("commit", {}).get("committer", {}).get("date"),
                "sha": commit.get("sha"),
            }

        return {
            "object": "repository",
            "owner": info["owner"],
            "repo": info["repo"],
            "name": repo_data.get("name"),
            "archived": repo_data.get("archived"),
            "lastPushedAt": repo_data.get("pushed_at"),
            "stars": repo_data.get("stargazers_count"),
            "forks": repo_data.get("forks_count"),
            "default_branch": repo_data.get("default_branch"),
        }

    @staticmethod
    async def get_children_count(target_id: str, token: str) -> int:
        info = GitHubProvider._parse_target(target_id)
        if info["kind"] == "bulk":
            prs = await GitHubProvider.list_open_prs(target_id, token)
            return len(prs)
        if info["kind"] == "branch":
            return 0
        repo_data = await GitHubProvider._get_repo(info["owner"], info["repo"], token)
        return int(repo_data.get("open_issues_count") or 0)

    @staticmethod
    async def archive(target_id: str, token: str) -> None:
        info = GitHubProvider._parse_target(target_id)
        if info["kind"] != "repo":
            raise RuntimeError("Archive action only supported for repositories")
        await GitHubProvider._request(
            "PATCH",
            f"/repos/{info['owner']}/{info['repo']}",
            token,
            json_payload={"archived": True},
        )

    @staticmethod
    async def unarchive(target_id: str, token: str) -> None:
        info = GitHubProvider._parse_target(target_id)
        if info["kind"] != "repo":
            raise RuntimeError("Unarchive action only supported for repositories")
        await GitHubProvider._request(
            "PATCH",
            f"/repos/{info['owner']}/{info['repo']}",
            token,
            json_payload={"archived": False},
        )

    @staticmethod
    async def delete_repository(target_id: str, token: str) -> None:
        """
        Delete repository (IRREVERSIBLE operation - CANNOT BE UNDONE).
        This is the most dangerous operation - repository and all its data will be permanently deleted.
        """
        info = GitHubProvider._parse_target(target_id)
        if info["kind"] != "repo":
            raise RuntimeError("Delete repository only supported for repositories")
        await GitHubProvider._request(
            "DELETE",
            f"/repos/{info['owner']}/{info['repo']}",
            token,
        )

    # GitHub-specific actions
    @staticmethod
    async def delete_branch(target_id: str, token: str) -> str:
        """Delete branch and return last commit SHA to store in revert_token."""
        info = GitHubProvider._parse_target(target_id)
        if info["kind"] != "branch":
            raise RuntimeError("Branch deletion requires repo#branch format")

        ref = await GitHubProvider._request(
            "GET",
            f"/repos/{info['owner']}/{info['repo']}/git/ref/heads/{info['branch']}",
            token,
        )
        sha = ref.get("object", {}).get("sha")
        if not sha:
            raise RuntimeError("Unable to resolve branch SHA")

        await GitHubProvider._request(
            "DELETE",
            f"/repos/{info['owner']}/{info['repo']}/git/refs/heads/{info['branch']}",
            token,
        )
        return sha

    @staticmethod
    async def restore_branch(target_id: str, token: str, sha: str) -> None:
        info = GitHubProvider._parse_target(target_id)
        if info["kind"] != "branch":
            raise RuntimeError("Branch restore requires repo#branch format")

        payload = {"ref": f"refs/heads/{info['branch']}", "sha": sha}
        try:
            await GitHubProvider._request(
                "POST",
                f"/repos/{info['owner']}/{info['repo']}/git/refs",
                token,
                json_payload=payload,
            )
        except RuntimeError as exc:
            # If branch already exists, treat as success
            if "already exists" not in str(exc):
                raise

    # --- Bulk PR operations ---
    @staticmethod
    async def list_open_prs(target_id: str, token: str) -> List[Dict[str, Any]]:
        info = GitHubProvider._parse_target(target_id)
        if info["kind"] not in {"bulk", "repo"}:
            raise RuntimeError("Bulk PR operations require org/repo[@view]")

        params = {"state": "open", "per_page": 100}
        prs = await GitHubProvider._request(
            "GET",
            f"/repos/{info['owner']}/{info['repo']}/pulls",
            token,
            params=params,
        )
        if not isinstance(prs, list):
            raise RuntimeError("Unexpected response when listing PRs")
        return [
            {
                "number": pr.get("number"),
                "title": pr.get("title"),
                "updatedAt": pr.get("updated_at"),
            }
            for pr in prs
        ]

    @staticmethod
    async def bulk_close_prs(target_id: str, token: str, pr_numbers: list[int] | None = None) -> dict:
        info = GitHubProvider._parse_target(target_id)
        if info["kind"] not in {"bulk", "repo"}:
            raise RuntimeError("Bulk close requires org/repo[@view]")

        if pr_numbers is None:
            prs = await GitHubProvider.list_open_prs(target_id, token)
            pr_numbers = [int(p.get("number")) for p in prs]

        for number in pr_numbers:
            await GitHubProvider._request(
                "PATCH",
                f"/repos/{info['owner']}/{info['repo']}/pulls/{number}",
                token,
                json_payload={"state": "closed"},
            )

        return {"ok": True, "closed_pr_numbers": pr_numbers, "revert_token": "rvk_gh_bulk"}

    @staticmethod
    async def bulk_reopen_prs(target_repo: str, pr_numbers: list[int], token: str | None = None) -> dict:
        info = GitHubProvider._parse_target(target_repo)
        if info["kind"] not in {"bulk", "repo"}:
            raise RuntimeError("Bulk reopen requires org/repo[@view]")

        for number in pr_numbers:
            await GitHubProvider._request(
                "PATCH",
                f"/repos/{info['owner']}/{info['repo']}/pulls/{number}",
                token,
                json_payload={"state": "open"},
            )

        return {"ok": True, "status": "reverted", "reopened": pr_numbers}

    # --- Force Push & Merge operations ---
    @staticmethod
    async def force_push(target_id: str, token: str, commit_sha: str = None) -> dict:
        """
        Force push to a branch (IRREVERSIBLE operation).
        target_id format: owner/repo#branch
        """
        info = GitHubProvider._parse_target(target_id)
        if info["kind"] != "branch":
            raise RuntimeError("Force push requires owner/repo#branch format")

        # Get current branch SHA before force push (for logging/audit)
        branch_data = await GitHubProvider._get_branch(info["owner"], info["repo"], info["branch"], token)
        previous_sha = branch_data.get("commit", {}).get("sha")

        if not commit_sha:
            raise RuntimeError("commit_sha is required for force push")

        # Force update the branch reference
        await GitHubProvider._request(
            "PATCH",
            f"/repos/{info['owner']}/{info['repo']}/git/refs/heads/{info['branch']}",
            token,
            json_payload={"sha": commit_sha, "force": True},
        )

        return {
            "ok": True,
            "previous_sha": previous_sha,
            "new_sha": commit_sha,
            "branch": info["branch"],
        }

    @staticmethod
    async def merge(target_id: str, token: str, commit_message: str = None) -> dict:
        """
        Merge branches (IRREVERSIBLE operation).
        target_id format: owner/repo#source_branch→target_branch
        """
        info = GitHubProvider._parse_target(target_id)
        if info["kind"] != "merge":
            raise RuntimeError("Merge requires owner/repo#source→target format")

        # Get the target branch default_branch status
        repo_data = await GitHubProvider._get_repo(info["owner"], info["repo"], token)
        is_main_branch = repo_data.get("default_branch") == info["target_branch"]

        # Prepare merge payload
        payload = {
            "base": info["target_branch"],
            "head": info["source_branch"],
        }
        if commit_message:
            payload["commit_message"] = commit_message

        # Execute merge
        result = await GitHubProvider._request(
            "POST",
            f"/repos/{info['owner']}/{info['repo']}/merges",
            token,
            json_payload=payload,
        )

        return {
            "ok": True,
            "merge_sha": result.get("sha") if result else None,
            "source": info["source_branch"],
            "target": info["target_branch"],
            "is_main_branch": is_main_branch,
        }

    @staticmethod
    async def merge_pull_request(
        owner: str,
        repo: str,
        pr_number: int,
        token: str,
        commit_title: str = None,
        commit_message: str = None,
        merge_method: str = "merge"
    ) -> dict:
        """
        Merge a pull request (IRREVERSIBLE operation).
        
        Args:
            owner: Repository owner
            repo: Repository name
            pr_number: Pull request number
            token: GitHub token
            commit_title: Optional custom merge commit title
            commit_message: Optional custom merge commit message
            merge_method: Merge method (merge, squash, or rebase)
        
        Returns:
            dict with merge details including sha and merged status
        """
        # Get PR details to check target branch
        pr_data = await GitHubProvider._request(
            "GET",
            f"/repos/{owner}/{repo}/pulls/{pr_number}",
            token
        )
        
        base_branch = pr_data.get("base", {}).get("ref")
        
        # Get repo to check if merging to default branch
        repo_data = await GitHubProvider._get_repo(owner, repo, token)
        is_main_branch = repo_data.get("default_branch") == base_branch
        
        # Prepare merge payload
        payload = {"merge_method": merge_method}
        if commit_title:
            payload["commit_title"] = commit_title
        if commit_message:
            payload["commit_message"] = commit_message
        
        # Execute merge
        result = await GitHubProvider._request(
            "PUT",
            f"/repos/{owner}/{repo}/pulls/{pr_number}/merge",
            token,
            json_payload=payload
        )
        
        return {
            "ok": True,
            "sha": result.get("sha"),
            "merged": result.get("merged", True),
            "message": result.get("message"),
            "pr_number": pr_number,
            "base_branch": base_branch,
            "is_main_branch": is_main_branch
        }


