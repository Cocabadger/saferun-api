"""API Key registration and authentication."""
from fastapi import APIRouter, HTTPException, Header, Depends
from pydantic import BaseModel, EmailStr
from typing import Optional
from .. import db
from saferun import __version__ as SR_VERSION

router = APIRouter(prefix="/v1/auth", tags=["Authentication"])

class RegisterRequest(BaseModel):
    email: EmailStr

class RegisterResponse(BaseModel):
    service: str = "saferun"
    version: str = SR_VERSION
    api_key: str
    message: str = "API key created successfully. Save it securely - it won't be shown again."

class StatusResponse(BaseModel):
    service: str = "saferun"
    version: str = SR_VERSION
    email: str
    usage_count: int
    created_at: str

@router.post("/register", response_model=RegisterResponse)
async def register(body: RegisterRequest):
    """Register a new user and get an API key."""
    # Check if email already has a key
    existing = db.get_api_key_by_email(body.email)
    if existing:
        raise HTTPException(
            status_code=400,
            detail="Email already registered. Contact support if you lost your key."
        )
    
    # Create new API key
    api_key = db.create_api_key(body.email)
    
    return RegisterResponse(
        api_key=api_key
    )

@router.get("/status", response_model=StatusResponse)
async def get_status(x_api_key: str = Header(..., alias="X-API-Key")):
    """Get API key status and usage."""
    key_info = db.validate_api_key(x_api_key)
    if not key_info:
        raise HTTPException(
            status_code=401,
            detail="Invalid or inactive API key"
        )
    
    # Don't increment counter for status check
    return StatusResponse(
        email=key_info["email"],
        usage_count=key_info["usage_count"] - 1,  # Subtract the increment from validate
        created_at=key_info["created_at"]
    )

def verify_api_key(x_api_key: Optional[str] = Header(None, alias="X-API-Key")) -> str:
    """Dependency to verify API key in protected routes."""
    if not x_api_key:
        raise HTTPException(
            status_code=401,
            detail="X-API-Key header required"
        )
    
    key_info = db.validate_api_key(x_api_key)
    if not key_info:
        raise HTTPException(
            status_code=401,
            detail="Invalid or inactive API key"
        )
    
    return x_api_key
