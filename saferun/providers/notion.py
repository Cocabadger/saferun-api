"""
Notion provider integration for SafeRun API.
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


class NotionProvider:
    """Notion API provider for SafeRun."""
    
    def __init__(self, token: Optional[str] = None):
        self.token = token or os.getenv("NOTION_TOKEN")
        self.base_url = "https://api.notion.com/v1"
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28"
        }
        
        if not self.token:
            logger.warning("Notion token not provided, API calls will fail")
    
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
        """Make authenticated request to Notion API with retry logic."""
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
                        message=f"Notion API error: {error_detail}",
                        provider="notion",
                        details={
                            "status_code": response.status_code,
                            "url": url,
                            "method": method
                        }
                    )
                
                return response.json() if response.content else {}
                
        except httpx.TimeoutException as e:
            raise handle_provider_error("notion", f"{method} {url}", e)
        except httpx.ConnectError as e:
            raise handle_provider_error("notion", f"{method} {url}", e)
        except Exception as e:
            raise handle_provider_error("notion", f"{method} {url}", e)
    
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
                    provider="notion"
                )
            
            predicted_changes.extend(changes)
            affected_resources.extend(resources)
            rollback_data.update(rollback)
            
        except Exception as e:
            if isinstance(e, ProviderError):
                raise
            raise handle_provider_error("notion", f"preview {action_type}", e)
        
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
                    provider="notion"
                )
                
        except Exception as e:
            if isinstance(e, ProviderError):
                raise
            raise handle_provider_error("notion", f"execute {action_type}", e)
    
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
            raise handle_provider_error("notion", f"rollback {action_type}", e)
    
    # CREATE operations
    async def _preview_create(self, resource_path: str, parameters: Dict[str, Any]) -> Tuple[List[str], List[str], Dict[str, Any]]:
        """Preview create operations."""
        if resource_path == "pages":
            # Preview page creation
            title = self._extract_title_from_properties(parameters.get("properties", {}))
            return (
                [f"Create page '{title}' in Notion"],
                [resource_path],
                {"action": "archive_page", "page_type": "page"}
            )
        elif resource_path == "databases":
            # Preview database creation
            title = parameters.get("title", {}).get("text", [{}])[0].get("text", {}).get("content", "Untitled")
            return (
                [f"Create database '{title}' in Notion"],
                [resource_path],
                {"action": "delete_database", "database_type": "database"}
            )
        else:
            return (
                [f"Create resource at {resource_path}"],
                [resource_path],
                {"action": "generic_delete", "resource_path": resource_path}
            )
    
    async def _execute_create(self, resource_path: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Execute create operations."""
        if resource_path == "pages":
            # Create page
            return await self._make_request("POST", "pages", parameters)
        elif resource_path == "databases":
            # Create database
            return await self._make_request("POST", "databases", parameters)
        else:
            raise ProviderError(
                message=f"Unsupported create operation for {resource_path}",
                provider="notion"
            )
    
    async def _rollback_create(self, resource_path: str, rollback_data: Dict[str, Any]) -> Dict[str, Any]:
        """Rollback create operations."""
        action = rollback_data.get("action")
        
        if action == "archive_page":
            # Archive the created page
            page_id = rollback_data.get("page_id")
            if page_id:
                return await self._make_request("PATCH", f"pages/{page_id}", {"archived": True})
        elif action == "delete_database":
            # Archive the created database (Notion doesn't allow true deletion)
            database_id = rollback_data.get("database_id")
            if database_id:
                return await self._make_request("PATCH", f"databases/{database_id}", {"archived": True})
        
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
        
        # Analyze what's being updated
        if "properties" in parameters:
            for prop_name, prop_value in parameters["properties"].items():
                changes.append(f"Update property '{prop_name}'")
        
        if "archived" in parameters:
            if parameters["archived"]:
                changes.append("Archive item")
            else:
                changes.append("Unarchive item")
        
        if "title" in parameters:
            changes.append("Update title")
        
        if not changes:
            changes.append("Update resource properties")
        
        return (changes, [resource_path], rollback_data)
    
    async def _execute_update(self, resource_path: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Execute update operations."""
        return await self._make_request("PATCH", resource_path, parameters)
    
    async def _rollback_update(self, resource_path: str, rollback_data: Dict[str, Any]) -> Dict[str, Any]:
        """Rollback update operations."""
        if rollback_data.get("action") == "restore_previous":
            previous_state = rollback_data.get("previous_state", {})
            # Restore relevant fields
            restore_data = {}
            
            if "properties" in previous_state:
                restore_data["properties"] = previous_state["properties"]
            if "archived" in previous_state:
                restore_data["archived"] = previous_state["archived"]
            if "title" in previous_state:
                restore_data["title"] = previous_state["title"]
            
            return await self._make_request("PATCH", resource_path, restore_data)
        else:
            return {"message": "Cannot rollback update - previous state not available"}
    
    # DELETE operations (Notion uses archiving instead of true deletion)
    async def _preview_delete(self, resource_path: str, parameters: Dict[str, Any]) -> Tuple[List[str], List[str], Dict[str, Any]]:
        """Preview delete operations."""
        # Get current data for potential recovery
        try:
            current_data = await self._make_request("GET", resource_path)
            rollback_data = {
                "action": "unarchive",
                "backup_data": current_data,
                "resource_path": resource_path
            }
        except:
            rollback_data = {"action": "delete_irreversible", "resource_path": resource_path}
        
        return (
            [f"Archive (delete) resource at {resource_path}"],
            [resource_path],
            rollback_data
        )
    
    async def _execute_delete(self, resource_path: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Execute delete operations (archive in Notion)."""
        # Notion doesn't have true deletion, so we archive instead
        archive_params = {"archived": True}
        archive_params.update(parameters)
        return await self._make_request("PATCH", resource_path, archive_params)
    
    async def _rollback_delete(self, resource_path: str, rollback_data: Dict[str, Any]) -> Dict[str, Any]:
        """Rollback delete operations."""
        if rollback_data.get("action") == "unarchive":
            # Unarchive the item
            return await self._make_request("PATCH", resource_path, {"archived": False})
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
    
    def _extract_title_from_properties(self, properties: Dict[str, Any]) -> str:
        """Extract title from Notion properties."""
        # Look for title property
        for prop_name, prop_value in properties.items():
            if prop_value.get("type") == "title":
                title_array = prop_value.get("title", [])
                if title_array and len(title_array) > 0:
                    return title_array[0].get("text", {}).get("content", "Untitled")
        
        # Fallback to any text property
        for prop_name, prop_value in properties.items():
            if prop_value.get("type") == "rich_text":
                text_array = prop_value.get("rich_text", [])
                if text_array and len(text_array) > 0:
                    return text_array[0].get("text", {}).get("content", "Untitled")
        
        return "Untitled"