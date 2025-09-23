"""
Health check endpoints for SafeRun application.
Provides liveness and readiness probes for Kubernetes deployments.
"""
import asyncio
import time
from typing import Dict, Any

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse

from .. import storage as storage_manager
from saferun import __version__ as SR_VERSION

router = APIRouter(tags=["Health"])

# Application startup time for health checks
_startup_time = time.time()

@router.get("/healthz", summary="Liveness probe")
async def liveness_probe() -> Dict[str, Any]:
    """
    Liveness probe endpoint for Kubernetes.
    
    Returns 200 if the application is running.
    Used by Kubernetes to determine if the pod should be restarted.
    """
    return {
        "status": "ok",
        "timestamp": time.time(),
        "uptime_seconds": int(time.time() - _startup_time),
        "service": "saferun",
        "version": SR_VERSION,
    }

@router.get("/readyz", summary="Readiness probe")
async def readiness_probe() -> Dict[str, Any]:
    """
    Readiness probe endpoint for Kubernetes.
    
    Returns 200 if the application is ready to serve traffic.
    Checks storage backend connectivity and other critical dependencies.
    Used by Kubernetes to determine if the pod should receive traffic.
    """
    checks = {}
    overall_status = "ok"
    
    # Check storage backend connectivity
    backend_status = {"status": "ok"}
    try:
        storage = storage_manager.get_storage()
        
        # If a full KV interface is available, check the roundtrip
        if all(hasattr(storage, m) for m in ("store", "get", "delete")):
            test_key = f"health_check_{int(time.time())}"
            test_value = "ok"
            await storage.store(test_key, test_value, ttl=5)
            retrieved = await storage.get(test_key)
            await storage.delete(test_key)
            if retrieved != test_value:
                raise RuntimeError("storage roundtrip mismatch")
            backend_status.update({"status": "ok", "mode": "kv-roundtrip"})
        else:
            # Fallback: safe read-only check
            if hasattr(storage, "list_changes"):
                _ = await storage.list_changes(limit=1)
                backend_status.update({"status": "ok", "mode": "readonly-check"})
            elif hasattr(storage, "gc"):
                await storage.gc()
                backend_status.update({"status": "ok", "mode": "gc-noop"})
            else:
                backend_status.update({"status": "ok", "mode": "noop"})
    except Exception as e:
        backend_status = {"status": "error", "error": str(e), "backend": "unknown"}
        overall_status = "error"

    checks["storage"] = backend_status
    
    # Check if application has been running for minimum time (startup grace period)
    uptime = time.time() - _startup_time
    if uptime < 10:  # 10 second grace period
        checks["startup"] = {
            "status": "warming_up",
            "uptime_seconds": int(uptime),
            "message": "Application still warming up"
        }
        if overall_status == "ok":
            overall_status = "warming_up"
    else:
        checks["startup"] = {
            "status": "ok",
            "uptime_seconds": int(uptime)
        }
    
    response_data = {
        "status": overall_status,
        "timestamp": time.time(),
        "checks": checks,
        "service": "saferun",
        "version": SR_VERSION,
    }
    
    # Return 503 if not ready, 200 if ready
    if overall_status == "error":
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=response_data
        )
    
    return response_data

