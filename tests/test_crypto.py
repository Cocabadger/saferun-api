import pytest
from saferun.app import crypto
import base64
import os

# Mock encryption key for testing
TEST_KEY = base64.b64encode(os.urandom(32)).decode()


@pytest.fixture(autouse=True)
def mock_env_key(monkeypatch):
    """Set test encryption key"""
    monkeypatch.setenv("SR_ENCRYPTION_KEY", TEST_KEY)


def test_encrypt_decrypt_roundtrip():
    """Test basic encryption/decryption"""
    plaintext = "ghp_1234567890abcdefghijklmnopqrst"
    
    encrypted = crypto.encrypt_token(plaintext)
    decrypted = crypto.decrypt_token(encrypted)
    
    assert decrypted == plaintext
    assert encrypted != plaintext
    assert len(encrypted) > len(plaintext)


def test_encrypt_produces_different_ciphertexts():
    """Test that same plaintext produces different ciphertexts (nonce randomness)"""
    plaintext = "ghp_test_token"
    
    encrypted1 = crypto.encrypt_token(plaintext)
    encrypted2 = crypto.encrypt_token(plaintext)
    
    assert encrypted1 != encrypted2  # Different nonces
    assert crypto.decrypt_token(encrypted1) == plaintext
    assert crypto.decrypt_token(encrypted2) == plaintext


def test_decrypt_tampered_token_fails():
    """Test that tampered tokens fail decryption"""
    plaintext = "ghp_test_token"
    encrypted = crypto.encrypt_token(plaintext)
    
    # Tamper with encrypted token
    encrypted_bytes = base64.b64decode(encrypted)
    tampered = encrypted_bytes[:-1] + b'X'  # Change last byte
    tampered_b64 = base64.b64encode(tampered).decode()
    
    # Should return None or raise
    decrypted = crypto.decrypt_token(tampered_b64)
    assert decrypted is None


def test_decrypt_empty_string():
    """Test empty string handling"""
    assert crypto.encrypt_token("") == ""
    assert crypto.decrypt_token("") is None
    assert crypto.decrypt_token(None) is None


def test_is_encrypted_detection():
    """Test encrypted vs plaintext detection"""
    plaintext = "ghp_1234567890abcdef"
    encrypted = crypto.encrypt_token(plaintext)
    
    assert crypto.is_encrypted(encrypted) is True
    assert crypto.is_encrypted(plaintext) is False
    assert crypto.is_encrypted("") is False


def test_missing_encryption_key(monkeypatch):
    """Test error when encryption key not set"""
    monkeypatch.delenv("SR_ENCRYPTION_KEY", raising=False)
    
    with pytest.raises(ValueError, match="SR_ENCRYPTION_KEY not configured"):
        crypto.get_encryption_key()


def test_invalid_encryption_key(monkeypatch):
    """Test error with invalid key"""
    monkeypatch.setenv("SR_ENCRYPTION_KEY", "invalid_key")
    
    with pytest.raises(ValueError, match="Invalid SR_ENCRYPTION_KEY"):
        crypto.get_encryption_key()


def test_invalid_key_length(monkeypatch):
    """Test error with wrong key length"""
    # Generate 16-byte key instead of 32
    short_key = base64.b64encode(os.urandom(16)).decode()
    monkeypatch.setenv("SR_ENCRYPTION_KEY", short_key)
    
    with pytest.raises(ValueError, match="must be 32 bytes"):
        crypto.get_encryption_key()
