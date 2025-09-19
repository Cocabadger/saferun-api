"""
Core safety middleware for SafeRun API.
"""

from typing import Dict, Any, Optional
from datetime import datetime
import uuid
import asyncio
import structlog

from saferun.models.models import (
    ActionRequest, ActionPreview, ActionExecution, ActionStatus,
    RollbackRequest, RollbackResult, ActionType
)
from saferun.core.risk import RiskAnalyzer
from saferun.providers import provider_manager
from saferun.utils.errors import (
    ActionNotFoundError, RiskThresholdExceededError, ApprovalRequiredError,
    RollbackError, ProviderError
)

logger = structlog.get_logger(__name__)


class SafetyMiddleware:
    """Core safety middleware that orchestrates action safety checks."""
    
    def __init__(self):
        self.risk_analyzer = RiskAnalyzer()
        self.actions_store = {}  # In production, use a proper database
        self.pending_approvals = {}  # In production, use a proper queue system
    
    async def preview_action(self, request: ActionRequest) -> ActionPreview:
        """Preview an action without executing it."""
        
        logger.info(
            "Previewing action",
            provider=request.provider,
            action_type=request.action_type,
            resource_path=request.resource_path,
            dry_run=request.dry_run
        )
        
        try:
            # Get the appropriate provider
            provider = provider_manager.get_provider(request.provider)
            
            # Assess risk
            risk_assessment = self.risk_analyzer.assess_risk(
                provider=request.provider,
                action_type=request.action_type,
                resource_path=request.resource_path,
                parameters=request.parameters
            )
            
            # Get preview from provider
            predicted_changes, affected_resources, rollback_data = await provider.preview_action(
                action_type=request.action_type,
                resource_path=request.resource_path,
                parameters=request.parameters
            )
            
            # Determine if approval is required
            requires_approval = (
                self.risk_analyzer.requires_approval(risk_assessment) and 
                not request.force
            )
            
            # Create action preview
            action_preview = ActionPreview(
                provider=request.provider,
                action_type=request.action_type,
                resource_path=request.resource_path,
                parameters=request.parameters,
                risk_assessment=risk_assessment,
                predicted_changes=predicted_changes,
                affected_resources=affected_resources,
                requires_approval=requires_approval,
                estimated_duration=self._estimate_duration(request.action_type, request.parameters)
            )
            
            # Store preview for potential execution
            self.actions_store[action_preview.action_id] = {
                "preview": action_preview,
                "rollback_data": rollback_data,
                "created_at": datetime.utcnow()
            }
            
            logger.info(
                "Action preview generated",
                action_id=action_preview.action_id,
                risk_score=risk_assessment.score,
                risk_level=risk_assessment.level,
                requires_approval=requires_approval
            )
            
            return action_preview
            
        except Exception as e:
            logger.error(
                "Failed to preview action",
                error=str(e),
                provider=request.provider,
                action_type=request.action_type
            )
            raise
    
    async def execute_action(
        self, 
        action_id: str, 
        approved_by: Optional[str] = None,
        force: bool = False
    ) -> ActionExecution:
        """Execute a previously previewed action."""
        
        if action_id not in self.actions_store:
            raise ActionNotFoundError(action_id)
        
        action_data = self.actions_store[action_id]
        preview = action_data["preview"]
        rollback_data = action_data["rollback_data"]
        
        logger.info(
            "Executing action",
            action_id=action_id,
            provider=preview.provider,
            action_type=preview.action_type,
            approved_by=approved_by,
            force=force
        )
        
        # Create execution record
        execution = ActionExecution(
            action_id=action_id,
            status=ActionStatus.PENDING,
            approval_required=preview.requires_approval,
            rollback_data=rollback_data
        )
        
        try:
            # Check if approval is required
            if preview.requires_approval and not force and not approved_by:
                execution.status = ActionStatus.PENDING
                self.pending_approvals[action_id] = execution
                raise ApprovalRequiredError(action_id, preview.risk_assessment.score)
            
            # Check risk threshold if not forced
            if not force and preview.risk_assessment.score >= self.risk_analyzer.high_risk_threshold:
                if not approved_by:
                    raise RiskThresholdExceededError(
                        risk_score=preview.risk_assessment.score,
                        threshold=self.risk_analyzer.high_risk_threshold,
                        action_type=preview.action_type
                    )
            
            # Mark as approved if we have an approver
            if approved_by:
                execution.approved_by = approved_by
                execution.approved_at = datetime.utcnow()
                execution.status = ActionStatus.APPROVED
            
            # Execute the action
            execution.status = ActionStatus.EXECUTING
            execution.started_at = datetime.utcnow()
            
            provider = provider_manager.get_provider(preview.provider)
            result = await provider.execute_action(
                action_type=preview.action_type,
                resource_path=preview.resource_path,
                parameters=preview.parameters
            )
            
            execution.result = result
            execution.status = ActionStatus.COMPLETED
            execution.completed_at = datetime.utcnow()
            
            # Update the stored execution
            action_data["execution"] = execution
            
            logger.info(
                "Action executed successfully",
                action_id=action_id,
                status=execution.status,
                duration=(execution.completed_at - execution.started_at).total_seconds()
            )
            
            return execution
            
        except Exception as e:
            execution.status = ActionStatus.FAILED
            execution.error = str(e)
            execution.completed_at = datetime.utcnow()
            action_data["execution"] = execution
            
            logger.error(
                "Action execution failed",
                action_id=action_id,
                error=str(e),
                provider=preview.provider,
                action_type=preview.action_type
            )
            
            # Re-raise the original exception
            raise
    
    async def rollback_action(self, request: RollbackRequest) -> RollbackResult:
        """Rollback a previously executed action."""
        
        if request.action_id not in self.actions_store:
            raise ActionNotFoundError(request.action_id)
        
        action_data = self.actions_store[request.action_id]
        preview = action_data["preview"]
        execution = action_data.get("execution")
        rollback_data = action_data["rollback_data"]
        
        if not execution or execution.status != ActionStatus.COMPLETED:
            raise RollbackError(
                action_id=request.action_id,
                reason="Action was not successfully completed",
                details={"current_status": execution.status if execution else "no_execution"}
            )
        
        logger.info(
            "Rolling back action",
            action_id=request.action_id,
            provider=preview.provider,
            action_type=preview.action_type,
            reason=request.reason
        )
        
        try:
            provider = provider_manager.get_provider(preview.provider)
            rollback_result_data = await provider.rollback_action(
                action_type=preview.action_type,
                resource_path=preview.resource_path,
                rollback_data=rollback_data
            )
            
            # Create rollback result
            rollback_result = RollbackResult(
                action_id=request.action_id,
                status=ActionStatus.ROLLED_BACK,
                rollback_actions=[f"Rolled back {preview.action_type} on {preview.resource_path}"],
                completed_at=datetime.utcnow()
            )
            
            # Update execution status
            execution.status = ActionStatus.ROLLED_BACK
            action_data["rollback"] = rollback_result
            
            logger.info(
                "Action rolled back successfully",
                action_id=request.action_id,
                rollback_id=rollback_result.rollback_id
            )
            
            return rollback_result
            
        except Exception as e:
            rollback_error = RollbackError(
                action_id=request.action_id,
                reason=str(e),
                details={"original_error": str(e)}
            )
            
            logger.error(
                "Rollback failed",
                action_id=request.action_id,
                error=str(e)
            )
            
            raise rollback_error
    
    def get_action_status(self, action_id: str) -> ActionExecution:
        """Get the status of an action."""
        
        if action_id not in self.actions_store:
            raise ActionNotFoundError(action_id)
        
        action_data = self.actions_store[action_id]
        execution = action_data.get("execution")
        
        if not execution:
            # Action was previewed but not executed yet
            preview = action_data["preview"]
            return ActionExecution(
                action_id=action_id,
                status=ActionStatus.PENDING,
                approval_required=preview.requires_approval
            )
        
        return execution
    
    def approve_action(self, action_id: str, approved_by: str) -> ActionExecution:
        """Approve a pending action."""
        
        if action_id not in self.pending_approvals:
            if action_id not in self.actions_store:
                raise ActionNotFoundError(action_id)
            
            action_data = self.actions_store[action_id]
            execution = action_data.get("execution")
            if execution and execution.status != ActionStatus.PENDING:
                raise ValueError(f"Action {action_id} is not pending approval")
        
        # This would trigger execution in a real implementation
        # For now, just mark as approved
        if action_id in self.pending_approvals:
            execution = self.pending_approvals[action_id]
            execution.approved_by = approved_by
            execution.approved_at = datetime.utcnow()
            execution.status = ActionStatus.APPROVED
            del self.pending_approvals[action_id]
            
            # Store the updated execution
            self.actions_store[action_id]["execution"] = execution
            
            return execution
        
        raise ActionNotFoundError(action_id)
    
    def _estimate_duration(self, action_type: ActionType, parameters: Dict[str, Any]) -> float:
        """Estimate the duration of an action in seconds."""
        
        base_durations = {
            ActionType.READ: 1.0,
            ActionType.CREATE: 3.0,
            ActionType.UPDATE: 2.0,
            ActionType.DELETE: 1.5
        }
        
        base_duration = base_durations.get(action_type, 2.0)
        
        # Adjust based on parameters
        if "bulk" in parameters or "batch" in parameters:
            base_duration *= 2.0
        
        if len(str(parameters)) > 1000:  # Large parameters
            base_duration *= 1.5
        
        return base_duration


# Global safety middleware instance
safety_middleware = SafetyMiddleware()