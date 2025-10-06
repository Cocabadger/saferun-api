"""Rate limiting middleware for SafeRun API.

Implements per-API-key rate limiting using in-memory storage.
For production, consider using Redis for distributed rate limiting.

SECURITY: Rate limiting CANNOT be bypassed or disabled.
When limit is reached, requests are BLOCKED. Users must either:
- Wait for hourly window to reset
- Upgrade to paid tier (unlimited requests)
"""
import os
import time
from typing import Dict, Tuple
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

# Get rate limit from environment (Railway variable SR_FREE_TIER_LIMIT)
FREE_TIER_LIMIT = int(os.getenv("SR_FREE_TIER_LIMIT", "1000"))
RATE_LIMIT_WINDOW = 3600  # 1 hour in seconds

# In-memory storage for rate limiting
# Format: {api_key: (request_count, window_start_time)}
_rate_limit_store: Dict[str, Tuple[int, float]] = {}


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Skip rate limiting ONLY for health checks and auth registration
        if request.url.path in ["/", "/health", "/readyz", "/v1/auth/register"]:
            return await call_next(request)
        
        # Extract API key from header
        api_key = request.headers.get("X-API-Key")
        
        # Skip rate limiting if no API key (will be rejected by auth middleware)
        if not api_key:
            return await call_next(request)
        
        # Check rate limit
        current_time = time.time()
        
        if api_key in _rate_limit_store:
            count, window_start = _rate_limit_store[api_key]
            
            # Reset window if expired
            if current_time - window_start > RATE_LIMIT_WINDOW:
                _rate_limit_store[api_key] = (1, current_time)
            else:
                # Check if limit exceeded
                if count >= FREE_TIER_LIMIT:
                    reset_time = int(window_start + RATE_LIMIT_WINDOW - current_time)
                    
                    # Return detailed error with upgrade instructions
                    # NO BYPASS OPTION - security requirement
                    return JSONResponse(
                        status_code=429,
                        content={
                            "error": "Rate limit exceeded",
                            "message": f"Free tier limit of {FREE_TIER_LIMIT} requests/hour exhausted",
                            "reset_in_seconds": reset_time,
                            "reset_at": int(window_start + RATE_LIMIT_WINDOW),
                            "options": {
                                "wait": f"Try again in {reset_time // 60} minutes",
                                "upgrade": {
                                    "message": "Upgrade to paid tier for unlimited requests",
                                    "url": "https://saferun.dev/pricing",
                                    "contact": "support@saferun.dev"
                                }
                            }
                        },
                        headers={
                            "X-RateLimit-Limit": str(FREE_TIER_LIMIT),
                            "X-RateLimit-Remaining": "0",
                            "X-RateLimit-Reset": str(int(window_start + RATE_LIMIT_WINDOW)),
                            "Retry-After": str(reset_time),
                        }
                    )
                
                # Increment counter
                _rate_limit_store[api_key] = (count + 1, window_start)
        else:
            # First request for this API key
            _rate_limit_store[api_key] = (1, current_time)
        
        # Add rate limit headers to response
        response = await call_next(request)
        
        if api_key in _rate_limit_store:
            count, window_start = _rate_limit_store[api_key]
            remaining = max(0, FREE_TIER_LIMIT - count)
            reset_timestamp = int(window_start + RATE_LIMIT_WINDOW)
            
            response.headers["X-RateLimit-Limit"] = str(FREE_TIER_LIMIT)
            response.headers["X-RateLimit-Remaining"] = str(remaining)
            response.headers["X-RateLimit-Reset"] = str(reset_timestamp)
        
        return response


def cleanup_expired_entries():
    """Clean up expired rate limit entries (call periodically)."""
    current_time = time.time()
    expired_keys = [
        key for key, (_, window_start) in _rate_limit_store.items()
        if current_time - window_start > RATE_LIMIT_WINDOW
    ]
    for key in expired_keys:
        del _rate_limit_store[key]
