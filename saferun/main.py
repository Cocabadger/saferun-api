"""
FastAPI application for SafeRun API.
"""

from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
import uvicorn
import os
from datetime import timedelta
from dotenv import load_dotenv
import structlog

# Import models and core components
from saferun.models.models import (
    ActionRequest, ActionPreview, ActionExecution, 
    RollbackRequest, RollbackResult, APIKeyRequest, AuthToken
)
from saferun.core import safety_middleware
from saferun.auth import authenticate_api_key, get_current_user, require_permission
from saferun.utils.errors import (
    SafeRunError, saferun_exception_handler, general_exception_handler,
    validation_exception_handler
)

# Load environment variables
load_dotenv()

# Configure logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)

# Create FastAPI app
app = FastAPI(
    title="SafeRun API",
    description="Open-source safety middleware for AI agents - prevent destructive actions before they happen",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add exception handlers
app.add_exception_handler(SafeRunError, saferun_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, general_exception_handler)


@app.on_event("startup")
async def startup_event():
    """Initialize the application."""
    logger.info("SafeRun API starting up")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown."""
    logger.info("SafeRun API shutting down")


# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "SafeRun API"}


# Authentication endpoints
@app.post("/api/v1/auth/token", response_model=AuthToken)
async def login(request: APIKeyRequest):
    """Authenticate with API key and receive JWT token."""
    access_token = await authenticate_api_key(request.api_key)
    return AuthToken(
        access_token=access_token,
        token_type="bearer",
        expires_in=int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30")) * 60
    )


# Action management endpoints
@app.post("/api/v1/actions/preview", response_model=ActionPreview)
async def preview_action(
    request: ActionRequest,
    current_user: dict = Depends(require_permission("read"))
):
    """Preview an action without executing it."""
    try:
        preview = await safety_middleware.preview_action(request)
        return preview
    except Exception as e:
        logger.error(f"Failed to preview action: {e}")
        raise


@app.post("/api/v1/actions/execute", response_model=ActionExecution)
async def execute_action(
    action_id: str,
    approved_by: str = None,
    force: bool = False,
    current_user: dict = Depends(require_permission("execute"))
):
    """Execute a previously previewed action."""
    try:
        execution = await safety_middleware.execute_action(
            action_id=action_id,
            approved_by=approved_by or current_user.get("sub"),
            force=force
        )
        return execution
    except Exception as e:
        logger.error(f"Failed to execute action {action_id}: {e}")
        raise


@app.post("/api/v1/actions/rollback", response_model=RollbackResult)
async def rollback_action(
    request: RollbackRequest,
    current_user: dict = Depends(require_permission("execute"))
):
    """Rollback a previously executed action."""
    try:
        result = await safety_middleware.rollback_action(request)
        return result
    except Exception as e:
        logger.error(f"Failed to rollback action {request.action_id}: {e}")
        raise


@app.get("/api/v1/actions/{action_id}/status", response_model=ActionExecution)
async def get_action_status(
    action_id: str,
    current_user: dict = Depends(require_permission("read"))
):
    """Get the status of an action."""
    try:
        status = safety_middleware.get_action_status(action_id)
        return status
    except Exception as e:
        logger.error(f"Failed to get action status for {action_id}: {e}")
        raise


@app.post("/api/v1/actions/{action_id}/approve", response_model=ActionExecution)
async def approve_action(
    action_id: str,
    current_user: dict = Depends(require_permission("approve"))
):
    """Approve a pending high-risk action."""
    try:
        execution = safety_middleware.approve_action(
            action_id=action_id,
            approved_by=current_user.get("sub")
        )
        return execution
    except Exception as e:
        logger.error(f"Failed to approve action {action_id}: {e}")
        raise


# Information endpoints
@app.get("/api/v1/providers")
async def list_providers(
    current_user: dict = Depends(require_permission("read"))
):
    """List available providers."""
    from saferun.providers import provider_manager
    return {
        "providers": provider_manager.list_available_providers()
    }


@app.get("/api/v1/risk/thresholds")
async def get_risk_thresholds(
    current_user: dict = Depends(require_permission("read"))
):
    """Get current risk assessment thresholds."""
    return {
        "default_threshold": safety_middleware.risk_analyzer.risk_threshold,
        "high_risk_threshold": safety_middleware.risk_analyzer.high_risk_threshold,
        "risk_levels": ["low", "medium", "high", "critical"]
    }


# Utility endpoint for testing
@app.post("/api/v1/test/dry-run")
async def test_dry_run(
    request: ActionRequest,
    current_user: dict = Depends(require_permission("read"))
):
    """Test endpoint for dry-run functionality."""
    # Force dry-run to true for safety
    request.dry_run = True
    
    preview = await safety_middleware.preview_action(request)
    
    return {
        "preview": preview,
        "safe_to_execute": preview.risk_assessment.score < 0.7,
        "recommendations": preview.risk_assessment.mitigation_suggestions
    }


if __name__ == "__main__":
    # Configuration from environment
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8000"))
    debug = os.getenv("API_DEBUG", "false").lower() == "true"
    
    logger.info(
        "Starting SafeRun API server",
        host=host,
        port=port,
        debug=debug
    )
    
    uvicorn.run(
        "saferun.main:app",
        host=host,
        port=port,
        reload=debug,
        log_level="info"
    )