"""
Encryption utilities for SafeRun
Handles encryption/decryption of sensitive data (GitHub tokens, secrets)
"""
import os
import base64
from typing import Optional
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag
import logging

logger = logging.getLogger(__name__)


def get_encryption_key() -> bytes:
    """Get encryption key from environment"""
    # Read fresh from environment each time (for testing)
    encryption_key_b64 = os.getenv("SR_ENCRYPTION_KEY")
    
    if not encryption_key_b64:
        raise ValueError("SR_ENCRYPTION_KEY not configured")
    
    try:
        key = base64.b64decode(encryption_key_b64)
        if len(key) != 32:  # AES-256 requires 32 bytes
            raise ValueError("SR_ENCRYPTION_KEY must be 32 bytes (base64 encoded)")
        return key
    except Exception as e:
        raise ValueError(f"Invalid SR_ENCRYPTION_KEY: {e}")


def encrypt_token(plaintext: str) -> str:
    """
    Encrypt a token using AES-256-GCM
    
    Args:
        plaintext: Token to encrypt (e.g., GitHub PAT)
    
    Returns:
        Base64-encoded encrypted token: nonce + ciphertext + tag
    """
    if not plaintext:
        return ""
    
    try:
        key = get_encryption_key()
        aesgcm = AESGCM(key)
        
        # Generate random nonce (12 bytes for GCM)
        nonce = os.urandom(12)
        
        # Encrypt
        ciphertext = aesgcm.encrypt(nonce, plaintext.encode('utf-8'), None)
        
        # Combine: nonce + ciphertext (which includes tag)
        encrypted = nonce + ciphertext
        
        # Base64 encode for storage
        return base64.b64encode(encrypted).decode('ascii')
    
    except Exception as e:
        logger.error(f"Encryption failed: {e}")
        raise RuntimeError(f"Failed to encrypt token: {e}")


def decrypt_token(encrypted: str) -> Optional[str]:
    """
    Decrypt a token using AES-256-GCM
    
    Args:
        encrypted: Base64-encoded encrypted token
    
    Returns:
        Decrypted plaintext token, or None if decryption fails
    """
    if not encrypted:
        return None
    
    try:
        key = get_encryption_key()
        aesgcm = AESGCM(key)
        
        # Decode from base64
        encrypted_bytes = base64.b64decode(encrypted)
        
        # Extract nonce (first 12 bytes) and ciphertext
        nonce = encrypted_bytes[:12]
        ciphertext = encrypted_bytes[12:]
        
        # Decrypt
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)
        
        return plaintext.decode('utf-8')
    
    except InvalidTag:
        logger.error("Token decryption failed: Invalid authentication tag (tampered data)")
        return None
    except Exception as e:
        logger.error(f"Decryption failed: {e}")
        return None


def is_encrypted(token: str) -> bool:
    """
    Check if a token is encrypted (for migration purposes)
    
    GitHub PAT format: ghp_... or github_pat_...
    Encrypted tokens: base64 (no prefix pattern)
    """
    if not token:
        return False
    
    # If starts with known GitHub token prefix, it's plaintext
    if token.startswith(('ghp_', 'github_pat_', 'gho_', 'ghu_', 'ghs_', 'ghr_')):
        return False
    
    # Try to decode as base64 - if it works, likely encrypted
    try:
        decoded = base64.b64decode(token, validate=True)
        # Encrypted tokens should decode to at least 12 (nonce) + 16 (tag) + data bytes
        return len(decoded) >= 28
    except Exception:
        return False
