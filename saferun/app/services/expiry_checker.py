"""Background task to auto-expire pending operations after revert_window."""
import asyncio
import logging
from datetime import datetime, timezone
from .. import db_postgres as db

logger = logging.getLogger(__name__)


async def check_expired_operations():
    """
    Check and expire operations past their revert_window.
    Updates status from 'pending' to 'expired' for operations where:
    - status = 'pending'
    - revert_expires_at < NOW()
    
    Returns list of expired change_ids.
    """
    try:
        # Get PostgreSQL connection directly
        conn = db.get_connection()
        cur = conn.cursor()
        
        # Update expired operations
        cur.execute("""
            UPDATE changes 
            SET status = 'expired'
            WHERE status = 'pending' 
              AND revert_expires_at IS NOT NULL
              AND revert_expires_at < NOW()
            RETURNING change_id, target_id, revert_expires_at;
        """)
        
        expired_records = cur.fetchall()
        conn.commit()
        conn.close()
        
        if expired_records:
            expired_ids = [row[0] for row in expired_records]
            logger.info(f"Auto-expired {len(expired_ids)} operations: {expired_ids}")
            
            # TODO: Send Slack notifications for expired operations
            for change_id, target_id, expires_at in expired_records:
                logger.info(f"Expired: {change_id} | Target: {target_id} | Expired at: {expires_at}")
        
        return [row[0] for row in expired_records] if expired_records else []
        
    except Exception as e:
        logger.error(f"Expiry checker error: {e}", exc_info=True)
        return []


async def cleanup_oauth_states():
    """
    Cleanup expired and used OAuth states from the database.
    
    SECURITY: OAuth states should have short TTL (10 min) to prevent replay attacks.
    This function removes states that are either:
    - Expired (created more than 10 minutes ago)
    - Already used (OAuth flow completed)
    """
    try:
        db.cleanup_expired_oauth_states()
        logger.debug("OAuth states cleanup completed")
    except Exception as e:
        logger.error(f"OAuth states cleanup error: {e}", exc_info=True)


async def expiry_checker_loop():
    """
    Run expiry check every 5 minutes.
    This background task continuously monitors for operations that have exceeded
    their revert_window without approval and auto-expires them.
    
    Also cleans up expired OAuth states for security.
    """
    logger.info("Expiry checker started - checking every 5 minutes")
    
    while True:
        try:
            # Check expired operations
            expired_ids = await check_expired_operations()
            if expired_ids:
                logger.info(f"Expiry check complete: {len(expired_ids)} operations expired")
            else:
                logger.debug("Expiry check complete: no expired operations")
            
            # Cleanup expired OAuth states (security housekeeping)
            await cleanup_oauth_states()
            
        except Exception as e:
            logger.error(f"Expiry checker loop error: {e}", exc_info=True)
        
        # Wait 5 minutes before next check
        await asyncio.sleep(300)
