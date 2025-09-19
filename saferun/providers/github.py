"""
GitHub provider integration for SafeRun API.
"""

from typing import Dict, List, Any, Optional, Tuple
import httpx
import asyncio
from datetime import datetime
import os
from dotenv import load_dotenv
import structlog

from saferun.models.models import ActionType, ProviderType
from saferun.utils.errors import ProviderError, handle_provider_error
from tenacity import retry, stop_after_attempt, wait_exponential

load_dotenv()
logger = structlog.get_logger(__name__)


class GitHubProvider:
    """GitHub API provider for SafeRun."""
    
    def __init__(self, token: Optional[str] = None):
        self.token = token or os.getenv("GITHUB_TOKEN")
        self.base_url = "https://api.github.com"
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "SafeRun-API/1.0"
        }
        
        if not self.token:
            logger.warning("GitHub token not provided, API calls will be limited")
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10)
    )
    async def _make_request(
        self, 
        method: str, 
        url: str, 
        data: Optional[Dict] = None,
        params: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Make authenticated request to GitHub API with retry logic."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.request(
                    method=method,
                    url=f"{self.base_url}/{url.lstrip('/')}",
                    headers=self.headers,
                    json=data,
                    params=params,
                    timeout=30.0
                )
                
                if response.status_code >= 400:
                    error_detail = response.text
                    try:
                        error_json = response.json()
                        error_detail = error_json.get("message", error_detail)
                    except:
                        pass
                    
                    raise ProviderError(
                        message=f"GitHub API error: {error_detail}",
                        provider="github",
                        details={
                            "status_code": response.status_code,
                            "url": url,
                            "method": method
                        }
                    )
                
                return response.json() if response.content else {}
                
        except httpx.TimeoutException as e:
            raise handle_provider_error("github", f"{method} {url}", e)
        except httpx.ConnectError as e:
            raise handle_provider_error("github", f"{method} {url}", e)
        except Exception as e:
            raise handle_provider_error("github", f"{method} {url}", e)
    
    async def preview_action(
        self, 
        action_type: ActionType,
        resource_path: str,
        parameters: Dict[str, Any]
    ) -> Tuple[List[str], List[str], Dict[str, Any]]:
        """Preview what the action would do without executing it."""
        
        predicted_changes = []
        affected_resources = []
        rollback_data = {}
        
        try:
            if action_type == ActionType.CREATE:
                changes, resources, rollback = await self._preview_create(resource_path, parameters)
            elif action_type == ActionType.UPDATE:
                changes, resources, rollback = await self._preview_update(resource_path, parameters)
            elif action_type == ActionType.DELETE:
                changes, resources, rollback = await self._preview_delete(resource_path, parameters)
            elif action_type == ActionType.READ:
                changes, resources, rollback = await self._preview_read(resource_path, parameters)
            else:
                raise ProviderError(
                    message=f"Unsupported action type: {action_type}",
                    provider="github"
                )
            
            predicted_changes.extend(changes)
            affected_resources.extend(resources)
            rollback_data.update(rollback)
            
        except Exception as e:
            if isinstance(e, ProviderError):
                raise
            raise handle_provider_error("github", f"preview {action_type}", e)
        
        return predicted_changes, affected_resources, rollback_data
    
    async def execute_action(
        self, 
        action_type: ActionType,
        resource_path: str,
        parameters: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute the action."""
        
        try:
            if action_type == ActionType.CREATE:
                return await self._execute_create(resource_path, parameters)
            elif action_type == ActionType.UPDATE:
                return await self._execute_update(resource_path, parameters)
            elif action_type == ActionType.DELETE:
                return await self._execute_delete(resource_path, parameters)
            elif action_type == ActionType.READ:
                return await self._execute_read(resource_path, parameters)
            else:
                raise ProviderError(
                    message=f"Unsupported action type: {action_type}",
                    provider="github"
                )
                
        except Exception as e:
            if isinstance(e, ProviderError):
                raise
            raise handle_provider_error("github", f"execute {action_type}", e)
    
    async def rollback_action(
        self, 
        action_type: ActionType,
        resource_path: str,
        rollback_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Rollback a previously executed action."""
        
        try:
            if action_type == ActionType.CREATE:
                return await self._rollback_create(resource_path, rollback_data)
            elif action_type == ActionType.UPDATE:
                return await self._rollback_update(resource_path, rollback_data)
            elif action_type == ActionType.DELETE:
                return await self._rollback_delete(resource_path, rollback_data)
            else:
                return {"message": f"No rollback needed for {action_type}"}
                
        except Exception as e:
            if isinstance(e, ProviderError):
                raise
            raise handle_provider_error("github", f"rollback {action_type}", e)
    
    # CREATE operations
    async def _preview_create(self, resource_path: str, parameters: Dict[str, Any]) -> Tuple[List[str], List[str], Dict[str, Any]]:
        """Preview create operations."""
        if "repos/" in resource_path and "/issues" in resource_path:
            # Preview issue creation
            repo_path = resource_path.split("/issues")[0]
            return (
                [f"Create issue '{parameters.get('title', 'Untitled')}' in {repo_path}"],
                [resource_path],
                {"action": "delete_issue", "repo_path": repo_path}
            )
        elif "repos/" in resource_path and "/pulls" in resource_path:
            # Preview PR creation
            repo_path = resource_path.split("/pulls")[0]
            return (
                [f"Create pull request '{parameters.get('title', 'Untitled')}' in {repo_path}"],
                [resource_path],
                {"action": "close_pr", "repo_path": repo_path}
            )
        else:
            return (
                [f"Create resource at {resource_path}"],
                [resource_path],
                {"action": "generic_delete", "resource_path": resource_path}
            )
    
    async def _execute_create(self, resource_path: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Execute create operations."""
        if "repos/" in resource_path and "/issues" in resource_path:
            # Create issue
            url = resource_path
            return await self._make_request("POST", url, parameters)
        elif "repos/" in resource_path and "/pulls" in resource_path:
            # Create pull request
            url = resource_path
            return await self._make_request("POST", url, parameters)
        else:
            raise ProviderError(
                message=f"Unsupported create operation for {resource_path}",
                provider="github"
            )
    
    async def _rollback_create(self, resource_path: str, rollback_data: Dict[str, Any]) -> Dict[str, Any]:
        """Rollback create operations (usually means deleting what was created)."""
        action = rollback_data.get("action")
        
        if action == "delete_issue":
            # Cannot delete issues via API, close instead
            issue_url = f"{rollback_data['repo_path']}/issues/{rollback_data.get('issue_number')}"
            return await self._make_request("PATCH", issue_url, {"state": "closed"})
        elif action == "close_pr":
            # Close the PR
            pr_url = f"{rollback_data['repo_path']}/pulls/{rollback_data.get('pr_number')}"
            return await self._make_request("PATCH", pr_url, {"state": "closed"})
        else:
            return {"message": "Rollback not implemented for this create operation"}
    
    # UPDATE operations
    async def _preview_update(self, resource_path: str, parameters: Dict[str, Any]) -> Tuple[List[str], List[str], Dict[str, Any]]:
        """Preview update operations."""
        # Get current state for rollback
        try:
            current_data = await self._make_request("GET", resource_path)
            rollback_data = {
                "action": "restore_previous",
                "previous_state": current_data,
                "resource_path": resource_path
            }
        except:
            rollback_data = {"action": "update_failed", "resource_path": resource_path}
        
        changes = []
        for key, value in parameters.items():
            changes.append(f"Update {key} to '{value}'")
        
        return (changes, [resource_path], rollback_data)
    
    async def _execute_update(self, resource_path: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Execute update operations."""
        return await self._make_request("PATCH", resource_path, parameters)
    
    async def _rollback_update(self, resource_path: str, rollback_data: Dict[str, Any]) -> Dict[str, Any]:
        """Rollback update operations."""
        if rollback_data.get("action") == "restore_previous":
            previous_state = rollback_data.get("previous_state", {})
            # Restore relevant fields
            restore_data = {k: v for k, v in previous_state.items() 
                          if k in ["title", "body", "state", "description"]}
            return await self._make_request("PATCH", resource_path, restore_data)
        else:
            return {"message": "Cannot rollback update - previous state not available"}
    
    # DELETE operations
    async def _preview_delete(self, resource_path: str, parameters: Dict[str, Any]) -> Tuple[List[str], List[str], Dict[str, Any]]:
        """Preview delete operations."""
        # Get current data for potential recovery
        try:
            current_data = await self._make_request("GET", resource_path)
            rollback_data = {
                "action": "recreate",
                "backup_data": current_data,
                "resource_path": resource_path
            }
        except:
            rollback_data = {"action": "delete_irreversible", "resource_path": resource_path}
        
        return (
            [f"Delete resource at {resource_path}"],
            [resource_path],
            rollback_data
        )
    
    async def _execute_delete(self, resource_path: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Execute delete operations."""
        return await self._make_request("DELETE", resource_path, parameters)
    
    async def _rollback_delete(self, resource_path: str, rollback_data: Dict[str, Any]) -> Dict[str, Any]:
        """Rollback delete operations."""
        if rollback_data.get("action") == "recreate":
            backup_data = rollback_data.get("backup_data", {})
            # Attempt to recreate - this may not always be possible
            create_data = {k: v for k, v in backup_data.items() 
                          if k in ["title", "body", "description", "name"]}
            
            # Determine the parent path for recreation
            if "/issues/" in resource_path:
                parent_path = resource_path.rsplit("/issues/", 1)[0] + "/issues"
            elif "/pulls/" in resource_path:
                parent_path = resource_path.rsplit("/pulls/", 1)[0] + "/pulls"
            else:
                parent_path = resource_path.rsplit("/", 1)[0]
            
            return await self._make_request("POST", parent_path, create_data)
        else:
            return {"message": "Cannot rollback delete - operation is irreversible"}
    
    # READ operations
    async def _preview_read(self, resource_path: str, parameters: Dict[str, Any]) -> Tuple[List[str], List[str], Dict[str, Any]]:
        """Preview read operations."""
        return (
            [f"Read resource at {resource_path}"],
            [resource_path],
            {"action": "no_rollback_needed"}
        )
    
    async def _execute_read(self, resource_path: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Execute read operations."""
        return await self._make_request("GET", resource_path, params=parameters)