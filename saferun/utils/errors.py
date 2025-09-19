"""
Comprehensive error handling for SafeRun API.
"""

from typing import Any, Dict, Optional
from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
import structlog
import traceback
from datetime import datetime

# Configure structured logging
logger = structlog.get_logger(__name__)


class SafeRunError(Exception):
    """Base exception for SafeRun API."""
    
    def __init__(
        self, 
        message: str, 
        error_code: str = None, 
        details: Dict[str, Any] = None,
        status_code: int = 500
    ):
        self.message = message
        self.error_code = error_code or self.__class__.__name__
        self.details = details or {}
        self.status_code = status_code
        self.timestamp = datetime.utcnow().isoformat()
        super().__init__(self.message)


class ProviderError(SafeRunError):
    """Error related to provider operations."""
    
    def __init__(self, message: str, provider: str, details: Dict[str, Any] = None):
        super().__init__(
            message=message,
            error_code="PROVIDER_ERROR",
            details={**(details or {}), "provider": provider},
            status_code=502
        )


class AuthenticationError(SafeRunError):
    """Authentication related errors."""
    
    def __init__(self, message: str = "Authentication failed", details: Dict[str, Any] = None):
        super().__init__(
            message=message,
            error_code="AUTHENTICATION_ERROR",
            details=details,
            status_code=401
        )


class AuthorizationError(SafeRunError):
    """Authorization related errors."""
    
    def __init__(self, message: str = "Insufficient permissions", details: Dict[str, Any] = None):
        super().__init__(
            message=message,
            error_code="AUTHORIZATION_ERROR", 
            details=details,
            status_code=403
        )


class ValidationError(SafeRunError):
    """Input validation errors."""
    
    def __init__(self, message: str, field: str = None, details: Dict[str, Any] = None):
        super().__init__(
            message=message,
            error_code="VALIDATION_ERROR",
            details={**(details or {}), "field": field} if field else details,
            status_code=400
        )


class ActionNotFoundError(SafeRunError):
    """Action not found error."""
    
    def __init__(self, action_id: str):
        super().__init__(
            message=f"Action with ID '{action_id}' not found",
            error_code="ACTION_NOT_FOUND",
            details={"action_id": action_id},
            status_code=404
        )


class RiskThresholdExceededError(SafeRunError):
    """Risk threshold exceeded error."""
    
    def __init__(self, risk_score: float, threshold: float, action_type: str = None):
        super().__init__(
            message=f"Risk score {risk_score} exceeds threshold {threshold}",
            error_code="RISK_THRESHOLD_EXCEEDED",
            details={
                "risk_score": risk_score,
                "threshold": threshold,
                "action_type": action_type
            },
            status_code=423  # Locked
        )


class ApprovalRequiredError(SafeRunError):
    """Approval required for high-risk action."""
    
    def __init__(self, action_id: str, risk_score: float):
        super().__init__(
            message="Manual approval required for high-risk action",
            error_code="APPROVAL_REQUIRED",
            details={
                "action_id": action_id,
                "risk_score": risk_score
            },
            status_code=202  # Accepted
        )


class RollbackError(SafeRunError):
    """Error during rollback operation."""
    
    def __init__(self, action_id: str, reason: str, details: Dict[str, Any] = None):
        super().__init__(
            message=f"Rollback failed for action {action_id}: {reason}",
            error_code="ROLLBACK_ERROR",
            details={**(details or {}), "action_id": action_id, "reason": reason},
            status_code=500
        )


class ProviderConnectionError(ProviderError):
    """Provider connection error."""
    
    def __init__(self, provider: str, details: Dict[str, Any] = None):
        super().__init__(
            message=f"Failed to connect to {provider} provider",
            provider=provider,
            details=details
        )


class ProviderTimeoutError(ProviderError):
    """Provider timeout error."""
    
    def __init__(self, provider: str, timeout: float, details: Dict[str, Any] = None):
        super().__init__(
            message=f"Timeout connecting to {provider} provider after {timeout}s",
            provider=provider,
            details={**(details or {}), "timeout": timeout}
        )


def create_error_response(error: SafeRunError) -> JSONResponse:
    """Create a standardized error response."""
    return JSONResponse(
        status_code=error.status_code,
        content={
            "error": {
                "code": error.error_code,
                "message": error.message,
                "details": error.details,
                "timestamp": error.timestamp
            }
        }
    )


async def saferun_exception_handler(request: Request, exc: SafeRunError) -> JSONResponse:
    """Global exception handler for SafeRun exceptions."""
    logger.error(
        "SafeRun error occurred",
        error_code=exc.error_code,
        message=exc.message,
        details=exc.details,
        path=request.url.path,
        method=request.method
    )
    return create_error_response(exc)


async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Global exception handler for unexpected errors."""
    error_id = datetime.utcnow().isoformat()
    
    logger.error(
        "Unexpected error occurred",
        error_id=error_id,
        error_type=type(exc).__name__,
        message=str(exc),
        traceback=traceback.format_exc(),
        path=request.url.path,
        method=request.method
    )
    
    # Don't expose internal error details in production
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "An unexpected error occurred",
                "details": {"error_id": error_id},
                "timestamp": datetime.utcnow().isoformat()
            }
        }
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Handle FastAPI validation errors."""
    logger.warning(
        "Validation error occurred",
        errors=exc.errors(),
        path=request.url.path,
        method=request.method
    )
    
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Input validation failed",
                "details": {"validation_errors": exc.errors()},
                "timestamp": datetime.utcnow().isoformat()
            }
        }
    )


def handle_provider_error(provider: str, operation: str, original_error: Exception) -> ProviderError:
    """Handle and wrap provider-specific errors."""
    error_message = f"Error during {operation} operation"
    
    if "timeout" in str(original_error).lower():
        return ProviderTimeoutError(
            provider=provider,
            details={"operation": operation, "original_error": str(original_error)}
        )
    elif "connection" in str(original_error).lower():
        return ProviderConnectionError(
            provider=provider,
            details={"operation": operation, "original_error": str(original_error)}
        )
    else:
        return ProviderError(
            message=error_message,
            provider=provider,
            details={"operation": operation, "original_error": str(original_error)}
        )


def log_and_raise(error: SafeRunError) -> None:
    """Log an error and raise it."""
    logger.error(
        "SafeRun error",
        error_code=error.error_code,
        message=error.message,
        details=error.details
    )
    raise error