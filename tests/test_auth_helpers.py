import pytest
from fastapi import HTTPException
from saferun.app.routers.auth_helpers import verify_change_ownership


class MockStorage:
    """Mock storage for testing"""
    def __init__(self):
        self.changes = {}
    
    def get_change(self, change_id):
        return self.changes.get(change_id)


def test_verify_change_ownership_success():
    """Test successful ownership verification"""
    storage = MockStorage()
    storage.changes["test-123"] = {
        "change_id": "test-123",
        "api_key": "sr_user123",
        "status": "pending"
    }
    
    result = verify_change_ownership("test-123", "sr_user123", storage)
    assert result["change_id"] == "test-123"
    assert result["api_key"] == "sr_user123"


def test_verify_change_ownership_wrong_user():
    """Test ownership check rejects wrong user"""
    storage = MockStorage()
    storage.changes["test-123"] = {
        "change_id": "test-123",
        "api_key": "sr_alice",
        "status": "pending"
    }
    
    # Bob tries to access Alice's change
    with pytest.raises(HTTPException) as exc_info:
        verify_change_ownership("test-123", "sr_bob", storage)
    
    assert exc_info.value.status_code == 404  # Not 403!
    assert "not found" in exc_info.value.detail.lower()


def test_verify_change_ownership_legacy_record():
    """Test backward compatibility with old records"""
    storage = MockStorage()
    storage.changes["old-123"] = {
        "change_id": "old-123",
        "api_key": None,  # Old record without api_key
        "status": "pending"
    }
    
    # Should allow access (backward compat)
    result = verify_change_ownership("old-123", "sr_anyone", storage)
    assert result["change_id"] == "old-123"


def test_verify_change_ownership_missing_api_key():
    """Test backward compatibility when api_key field is missing"""
    storage = MockStorage()
    storage.changes["old-456"] = {
        "change_id": "old-456",
        # No api_key field at all
        "status": "pending"
    }
    
    # Should allow access (backward compat)
    result = verify_change_ownership("old-456", "sr_anyone", storage)
    assert result["change_id"] == "old-456"


def test_verify_change_ownership_not_found():
    """Test 404 when change doesn't exist"""
    storage = MockStorage()
    
    with pytest.raises(HTTPException) as exc_info:
        verify_change_ownership("nonexistent", "sr_user", storage)
    
    assert exc_info.value.status_code == 404
    assert "not found" in exc_info.value.detail.lower()


def test_verify_change_ownership_case_sensitive():
    """Test that API key comparison is case-sensitive"""
    storage = MockStorage()
    storage.changes["test-789"] = {
        "change_id": "test-789",
        "api_key": "sr_Alice",
        "status": "pending"
    }
    
    # Different case should fail
    with pytest.raises(HTTPException) as exc_info:
        verify_change_ownership("test-789", "sr_alice", storage)
    
    assert exc_info.value.status_code == 404
