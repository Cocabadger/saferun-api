import pytest
import os
import tempfile
import base64
from saferun.app import db, crypto


# Generate test encryption key
TEST_KEY = base64.b64encode(os.urandom(32)).decode()


@pytest.fixture(autouse=True)
def setup_test_env(monkeypatch):
    """Setup test environment with encryption key and temp database"""
    monkeypatch.setenv("SR_ENCRYPTION_KEY", TEST_KEY)
    
    # Use temporary database for tests
    temp_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
    temp_db.close()
    
    monkeypatch.setenv("SR_SQLITE_PATH", temp_db.name)
    db.reload_db_path(temp_db.name)
    
    # Initialize database
    db.init_db()
    
    yield
    
    # Cleanup
    try:
        os.unlink(temp_db.name)
    except:
        pass


def test_upsert_encrypts_token():
    """Test that tokens are encrypted when stored"""
    change = {
        "change_id": "test-encrypt-123",
        "token": "ghp_plaintext_token_12345",
        "provider": "github",
        "status": "pending",
        "target_id": "owner/repo"
    }
    
    db.upsert_change(change)
    
    # Read directly from DB (bypassing decrypt)
    raw = db.fetchone("SELECT token FROM changes WHERE change_id = ?", ("test-encrypt-123",))
    
    # Token in DB should be encrypted
    assert raw["token"] != "ghp_plaintext_token_12345"
    assert crypto.is_encrypted(raw["token"]) is True
    
    # But get_change should return decrypted
    retrieved = db.get_change("test-encrypt-123")
    assert retrieved["token"] == "ghp_plaintext_token_12345"


def test_upsert_encrypts_revert_token():
    """Test that revert tokens are encrypted when stored"""
    change = {
        "change_id": "test-revert-456",
        "revert_token": "ghp_revert_token_67890",
        "provider": "github",
        "status": "pending",
        "target_id": "owner/repo"
    }
    
    db.upsert_change(change)
    
    # Read directly from DB
    raw = db.fetchone("SELECT revert_token FROM changes WHERE change_id = ?", ("test-revert-456",))
    
    # Revert token in DB should be encrypted
    assert raw["revert_token"] != "ghp_revert_token_67890"
    assert crypto.is_encrypted(raw["revert_token"]) is True
    
    # But get_change should return decrypted
    retrieved = db.get_change("test-revert-456")
    assert retrieved["revert_token"] == "ghp_revert_token_67890"


def test_migration_plaintext_to_encrypted():
    """Test migration of existing plaintext tokens"""
    # Insert plaintext token directly (simulating old data)
    db.exec(
        "INSERT INTO changes (change_id, token, provider, status, target_id) VALUES (?, ?, ?, ?, ?)",
        ("old-123", "ghp_old_plaintext", "github", "pending", "owner/repo")
    )
    
    # Verify it's plaintext
    raw_before = db.fetchone("SELECT token FROM changes WHERE change_id = ?", ("old-123",))
    assert raw_before["token"] == "ghp_old_plaintext"
    assert crypto.is_encrypted(raw_before["token"]) is False
    
    # Run migration
    count = db.migrate_tokens_to_encrypted()
    assert count >= 1
    
    # Verify encrypted in DB
    raw_after = db.fetchone("SELECT token FROM changes WHERE change_id = ?", ("old-123",))
    assert raw_after["token"] != "ghp_old_plaintext"
    assert crypto.is_encrypted(raw_after["token"]) is True
    
    # Verify decrypts correctly
    retrieved = db.get_change("old-123")
    assert retrieved["token"] == "ghp_old_plaintext"


def test_migration_idempotent():
    """Test that migration can run multiple times safely"""
    change = {
        "change_id": "test-idempotent-789",
        "token": "ghp_test_idempotent",
        "provider": "github",
        "status": "pending",
        "target_id": "owner/repo"
    }
    db.upsert_change(change)
    
    # Run migration multiple times
    count1 = db.migrate_tokens_to_encrypted()
    count2 = db.migrate_tokens_to_encrypted()
    count3 = db.migrate_tokens_to_encrypted()
    
    # Should not re-encrypt already encrypted tokens
    assert count2 == 0
    assert count3 == 0
    
    # Token should still decrypt correctly
    retrieved = db.get_change("test-idempotent-789")
    assert retrieved["token"] == "ghp_test_idempotent"


def test_set_revert_token_encrypts():
    """Test that set_revert_token encrypts before storing"""
    # Create a change
    change = {
        "change_id": "test-set-revert-999",
        "provider": "github",
        "status": "pending",
        "target_id": "owner/repo"
    }
    db.upsert_change(change)
    
    # Set revert token
    db.set_revert_token("test-set-revert-999", "ghp_new_revert_token")
    
    # Read directly from DB
    raw = db.fetchone("SELECT revert_token FROM changes WHERE change_id = ?", ("test-set-revert-999",))
    
    # Should be encrypted
    assert raw["revert_token"] != "ghp_new_revert_token"
    assert crypto.is_encrypted(raw["revert_token"]) is True
    
    # But get_change should decrypt
    retrieved = db.get_change("test-set-revert-999")
    assert retrieved["revert_token"] == "ghp_new_revert_token"


def test_get_by_revert_token_with_encryption():
    """Test that get_by_revert_token works with encrypted tokens"""
    change = {
        "change_id": "test-get-by-token-111",
        "revert_token": "ghp_unique_revert_12345",
        "provider": "github",
        "status": "pending",
        "target_id": "owner/repo"
    }
    db.upsert_change(change)
    
    # Should find by plaintext token (decrypts and compares)
    retrieved = db.get_by_revert_token("ghp_unique_revert_12345")
    
    assert retrieved is not None
    assert retrieved["change_id"] == "test-get-by-token-111"
    assert retrieved["revert_token"] == "ghp_unique_revert_12345"
