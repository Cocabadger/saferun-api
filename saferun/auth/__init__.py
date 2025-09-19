"""
Authentication and authorization module for SafeRun API.
"""

from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import os
from dotenv import load_dotenv

load_dotenv()

# Configuration
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-here")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()

# Mock API keys database (in production, use a proper database)
API_KEYS_DB = {
    "saferun-key-123": {
        "user_id": "user1",
        "permissions": ["read", "write", "execute"],
        "created_at": datetime.utcnow(),
        "is_active": True
    }
}


class AuthenticationError(Exception):
    """Custom authentication error."""
    pass


class AuthorizationError(Exception):
    """Custom authorization error."""
    pass


def verify_api_key(api_key: str) -> Dict[str, Any]:
    """Verify API key and return user information."""
    if api_key not in API_KEYS_DB:
        raise AuthenticationError("Invalid API key")
    
    key_info = API_KEYS_DB[api_key]
    if not key_info["is_active"]:
        raise AuthenticationError("API key is inactive")
    
    return key_info


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """Create JWT access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def verify_token(token: str) -> Dict[str, Any]:
    """Verify JWT token and return payload."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise AuthenticationError("Invalid token")
        return payload
    except JWTError:
        raise AuthenticationError("Invalid token")


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Dict[str, Any]:
    """Get current user from JWT token."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        payload = verify_token(credentials.credentials)
        return payload
    except AuthenticationError:
        raise credentials_exception


def require_permission(permission: str):
    """Decorator to require specific permission."""
    def decorator(user: Dict[str, Any] = Depends(get_current_user)):
        user_permissions = user.get("permissions", [])
        if permission not in user_permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission '{permission}' required"
            )
        return user
    return decorator


async def authenticate_api_key(api_key: str) -> str:
    """Authenticate using API key and return JWT token."""
    try:
        key_info = verify_api_key(api_key)
        
        # Create JWT token with user information
        token_data = {
            "sub": key_info["user_id"],
            "permissions": key_info["permissions"],
            "api_key": api_key[:8] + "..."  # Partial key for logging
        }
        
        access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data=token_data, 
            expires_delta=access_token_expires
        )
        
        return access_token
        
    except AuthenticationError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e)
        )


def add_api_key(api_key: str, user_id: str, permissions: list = None) -> None:
    """Add a new API key to the database."""
    if permissions is None:
        permissions = ["read"]
    
    API_KEYS_DB[api_key] = {
        "user_id": user_id,
        "permissions": permissions,
        "created_at": datetime.utcnow(),
        "is_active": True
    }


def revoke_api_key(api_key: str) -> None:
    """Revoke an API key."""
    if api_key in API_KEYS_DB:
        API_KEYS_DB[api_key]["is_active"] = False