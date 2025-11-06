"""
Authorization helpers for cross-user isolation
"""
from fastapi import HTTPException
import logging

logger = logging.getLogger(__name__)


def verify_change_ownership(change_id: str, api_key: str, storage):
    """
    Verify that authenticated user owns this change.
    
    Args:
        change_id: Change ID to check
        api_key: Authenticated user's API key
        storage: Storage instance
    
    Returns:
        dict: Change record if authorized
    
    Raises:
        HTTPException(404): If change not found OR user doesn't own it
                            (404 prevents change_id enumeration)
    """
    rec = storage.get_change(change_id)
    
    if not rec:
        raise HTTPException(status_code=404, detail="Approval request not found")
    
    # Get change owner's API key
    change_api_key = rec.get("api_key")
    
    # Backward compatibility: Allow access to old records without api_key
    if not change_api_key:
        logger.warning(
            f"Legacy change {change_id} accessed without api_key - "
            f"consider running migration to add api_key"
        )
        return rec
    
    # Strict ownership check for new records
    if change_api_key != api_key:
        # Return 404 (not 403) to prevent change_id enumeration
        logger.warning(
            f"Unauthorized access attempt: user {api_key[:10]}... "
            f"tried to access change {change_id} owned by {change_api_key[:10]}..."
        )
        raise HTTPException(status_code=404, detail="Approval request not found")
    
    return rec
