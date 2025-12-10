"""GitHub API service for webhook handling and operations"""
import hashlib
import hmac
import os
import time
import jwt
from typing import Dict, Any, Optional, Tuple
import httpx
from fastapi import HTTPException


GITHUB_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "")
GITHUB_APP_ID = os.getenv("GITHUB_APP_ID", "")
GITHUB_PRIVATE_KEY = os.getenv("GITHUB_PRIVATE_KEY", "")


def get_github_app_installation_token(installation_id: int) -> Optional[str]:
    """
    Get GitHub App Installation Access Token
    
    Args:
        installation_id: GitHub App installation ID
    
    Returns:
        Installation access token or None if failed
    """
    if not GITHUB_APP_ID or not GITHUB_PRIVATE_KEY:
        raise ValueError("GITHUB_APP_ID and GITHUB_PRIVATE_KEY must be configured")
    
    # Generate JWT for GitHub App authentication
    now = int(time.time())
    payload = {
        "iat": now - 60,  # Issued at time (60s ago to account for clock drift)
        "exp": now + (10 * 60),  # Expires in 10 minutes
        "iss": GITHUB_APP_ID
    }
    
    # Sign JWT with private key
    jwt_token = jwt.encode(payload, GITHUB_PRIVATE_KEY, algorithm="RS256")
    
    # Request installation access token
    try:
        with httpx.Client() as client:
            response = client.post(
                f"https://api.github.com/app/installations/{installation_id}/access_tokens",
                headers={
                    "Authorization": f"Bearer {jwt_token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28"
                },
                timeout=10.0
            )
            
            if response.status_code == 201:
                data = response.json()
                return data.get("token")
            else:
                print(f"❌ Failed to get GitHub App token: {response.status_code} {response.text}")
                return None
    except Exception as e:
        print(f"❌ Error getting GitHub App token: {str(e)}")
        return None


def get_deleted_branch_sha(owner: str, repo: str, branch_name: str, installation_id: int) -> Optional[str]:
    """
    Get SHA of a deleted branch by looking at GitHub Events API.
    
    When a branch is deleted, we can find its last SHA from the DeleteEvent
    or from recent PushEvents to that branch.
    
    Args:
        owner: Repository owner
        repo: Repository name  
        branch_name: Name of the deleted branch
        installation_id: GitHub App installation ID for authentication
    
    Returns:
        SHA string if found, None otherwise
    """
    try:
        # Get GitHub App token
        token = get_github_app_installation_token(installation_id)
        if not token:
            print(f"⚠️ Could not get GitHub App token for installation {installation_id}")
            return None
        
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"
        }
        
        # Try to get SHA from repository events
        # Look for recent PushEvent or CreateEvent for this branch
        with httpx.Client() as client:
            # Check repo events for push to this branch
            response = client.get(
                f"https://api.github.com/repos/{owner}/{repo}/events",
                headers=headers,
                params={"per_page": 100},
                timeout=10.0
            )
            
            if response.status_code == 200:
                events = response.json()
                for event in events:
                    # Look for PushEvent to this branch
                    if event.get("type") == "PushEvent":
                        payload = event.get("payload", {})
                        ref = payload.get("ref", "")
                        # ref format: "refs/heads/branch-name"
                        if ref == f"refs/heads/{branch_name}":
                            head_sha = payload.get("head")
                            if head_sha:
                                print(f"✅ Found SHA for deleted branch '{branch_name}' from PushEvent: {head_sha}")
                                return head_sha
                    
                    # Look for CreateEvent for this branch (branch creation)
                    if event.get("type") == "CreateEvent":
                        payload = event.get("payload", {})
                        if payload.get("ref_type") == "branch" and payload.get("ref") == branch_name:
                            # CreateEvent doesn't have SHA directly, but we can get it from master_branch
                            # For new branches, the SHA is the same as the source branch at creation time
                            # We need to look at the next PushEvent or use the default branch SHA
                            print(f"⚠️ Found CreateEvent for branch '{branch_name}' but no SHA in payload")
                            continue
                
                print(f"⚠️ No SHA found in events for deleted branch '{branch_name}'")
            else:
                print(f"⚠️ Failed to get repo events: {response.status_code}")
                
    except Exception as e:
        print(f"❌ Error getting deleted branch SHA: {str(e)}")
    
    return None


def verify_webhook_signature(payload: bytes, signature: str) -> bool:
    """
    Verify GitHub webhook signature using HMAC-SHA256
    
    Args:
        payload: Raw request body bytes
        signature: X-Hub-Signature-256 header value (format: "sha256=...")
    
    Returns:
        bool: True if signature is valid
    """
    if not GITHUB_WEBHOOK_SECRET:
        raise ValueError("GITHUB_WEBHOOK_SECRET not configured")
    
    if not signature or not signature.startswith("sha256="):
        return False
    
    expected_signature = "sha256=" + hmac.new(
        GITHUB_WEBHOOK_SECRET.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(expected_signature, signature)


def calculate_github_risk_score(event_type: str, payload: Dict[str, Any]) -> Tuple[float, list[str]]:
    """
    Calculate risk score for GitHub webhook events
    
    Args:
        event_type: GitHub event type (push, delete, pull_request, etc)
        payload: Webhook payload
    
    Returns:
        Tuple of (risk_score, reasons)
    """
    risk_score = 0.0
    reasons = []
    
    if event_type == "push":
        # Force push detection
        if payload.get("forced"):
            risk_score += 7.0
            reasons.append("github_force_push")
            
            # Check if it's to a protected/default branch
            ref = payload.get("ref", "")
            if "main" in ref or "master" in ref:
                risk_score += 2.0
                reasons.append("github_force_push_to_main")
        
        # Check number of commits
        commits = payload.get("commits", [])
        if len(commits) > 10:
            risk_score += 0.5
            reasons.append("github_large_push")
    
    elif event_type == "delete":
        ref_type = payload.get("ref_type", "")
        ref = payload.get("ref", "")
        
        if ref_type == "branch":
            risk_score += 4.0
            reasons.append("github_branch_delete")
            
            # Higher risk for protected branches
            if "main" in ref or "master" in ref:
                risk_score += 4.0
                reasons.append("github_delete_main_branch")
        
        elif ref_type == "tag":
            risk_score += 3.0
            reasons.append("github_tag_delete")
    
    elif event_type == "pull_request":
        action = payload.get("action", "")
        pr = payload.get("pull_request", {})
        
        if action == "closed" and pr.get("merged"):
            # Merged PR
            base_branch = pr.get("base", {}).get("ref", "")
            
            if "main" in base_branch or "master" in base_branch:
                risk_score += 5.0
                reasons.append("github_merge_to_main")
                
                # Check if merged without review
                if pr.get("review_comments", 0) == 0:
                    risk_score += 1.0
                    reasons.append("github_merge_without_review")
            else:
                risk_score += 2.0
                reasons.append("github_merge")
    
    elif event_type == "repository":
        action = payload.get("action", "")
        
        if action == "archived":
            risk_score += 8.0
            reasons.append("github_repository_archived")
        elif action == "deleted":
            risk_score += 10.0
            reasons.append("github_repository_deleted")
    
    # Cap at 10.0
    risk_score = min(risk_score, 10.0)
    
    return risk_score, reasons


async def revert_force_push(
    owner: str,
    repo: str,
    branch: str,
    before_sha: str,
    github_token: str
) -> bool:
    """
    Revert force push by resetting branch to before SHA
    
    Args:
        owner: Repository owner
        repo: Repository name
        branch: Branch name
        before_sha: SHA before force push (from webhook payload)
        github_token: GitHub token with write permissions
    
    Returns:
        bool: True if revert successful
    """
    url = f"https://api.github.com/repos/{owner}/{repo}/git/refs/heads/{branch}"
    headers = {
        "Authorization": f"token {github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    data = {
        "sha": before_sha,
        "force": True
    }
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.patch(url, json=data, headers=headers)
            return response.status_code == 200
        except Exception as e:
            print(f"Failed to revert force push: {e}")
            return False


async def restore_deleted_branch(
    owner: str,
    repo: str,
    branch: str,
    sha: str,
    github_token: str
) -> bool:
    """
    Restore deleted branch by creating ref at specific SHA
    
    Args:
        owner: Repository owner
        repo: Repository name
        branch: Branch name to restore
        sha: SHA to restore branch to
        github_token: GitHub token with write permissions
    
    Returns:
        bool: True if restore successful
    """
    url = f"https://api.github.com/repos/{owner}/{repo}/git/refs"
    headers = {
        "Authorization": f"token {github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    data = {
        "ref": f"refs/heads/{branch}",
        "sha": sha
    }
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, json=data, headers=headers)
            return response.status_code == 201
        except Exception as e:
            print(f"Failed to restore deleted branch: {e}")
            return False


async def create_revert_commit(
    owner: str,
    repo: str,
    branch: str,
    commit_sha: str,
    github_token: str
) -> bool:
    """
    Create revert commit for a merge
    
    Args:
        owner: Repository owner
        repo: Repository name
        branch: Branch to revert on
        commit_sha: SHA of commit to revert
        github_token: GitHub token with write permissions
    
    Returns:
        bool: True if revert successful
    """
    # Get the commit to revert
    url = f"https://api.github.com/repos/{owner}/{repo}/commits/{commit_sha}"
    headers = {
        "Authorization": f"token {github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    
    async with httpx.AsyncClient() as client:
        try:
            # Get commit details
            response = await client.get(url, headers=headers)
            if response.status_code != 200:
                return False
            
            commit_data = response.json()
            
            # Create revert commit via git revert
            # Note: GitHub doesn't have direct revert API, need to use git operations
            # For now, we'll create a reverse patch
            
            # Get parent commit
            parents = commit_data.get("parents", [])
            if not parents:
                return False
            
            parent_sha = parents[0]["sha"]
            
            # Update branch to parent (effectively reverting)
            ref_url = f"https://api.github.com/repos/{owner}/{repo}/git/refs/heads/{branch}"
            ref_data = {"sha": parent_sha, "force": True}
            
            response = await client.patch(ref_url, json=ref_data, headers=headers)
            return response.status_code == 200
            
        except Exception as e:
            print(f"Failed to create revert commit: {e}")
            return False


def create_revert_action(event_type: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Generate revert action instructions based on event type
    
    Args:
        event_type: GitHub event type
        payload: Webhook payload
    
    Returns:
        Dict with revert action details or None
    """
    if event_type == "push" and payload.get("forced"):
        return {
            "type": "force_push_revert",
            "owner": payload["repository"]["owner"]["login"],
            "repo": payload["repository"]["name"],
            "branch": payload["ref"].replace("refs/heads/", ""),
            "before_sha": payload.get("before"),
            "after_sha": payload.get("after")
        }
    
    elif event_type == "delete" and payload.get("ref_type") == "branch":
        # For delete, we need to get the SHA before deletion
        # This should be stored when we receive the event
        return {
            "type": "branch_restore",
            "owner": payload["repository"]["owner"]["login"],
            "repo": payload["repository"]["name"],
            "branch": payload.get("ref"),
            "sha": None  # Will be populated from previous push event
        }
    
    elif event_type == "pull_request":
        action = payload.get("action")
        pr = payload.get("pull_request", {})
        
        if action == "closed" and pr.get("merged"):
            return {
                "type": "merge_revert",
                "owner": payload["repository"]["owner"]["login"],
                "repo": payload["repository"]["name"],
                "branch": pr["base"]["ref"],
                "merge_commit_sha": pr.get("merge_commit_sha")
            }
    
    elif event_type == "repository":
        action = payload.get("action")
        
        if action == "archived":
            return {
                "type": "repository_unarchive",
                "owner": payload["repository"]["owner"]["login"],
                "repo": payload["repository"]["name"]
            }
        elif action == "deleted":
            # Repository delete is IRREVERSIBLE - no revert action possible
            return None
    
    return None
