"""
Integration tests for cross-user authorization in approvals router

Tests verify multi-tenant isolation:
- Users can only access their own approval requests
- Wrong API key returns 404 (not 403) to prevent enumeration
- Legacy records (without api_key) remain accessible
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from saferun.app import main


@pytest.fixture
def client():
    """Create test client for FastAPI app"""
    return TestClient(main.app)


@pytest.fixture
def mock_storage():
    """Mock storage with test data"""
    class MockStorage:
        def __init__(self):
            self.data = {
                "change-alice-123": {
                    "change_id": "change-alice-123",
                    "api_key": "alice-api-key-12345",
                    "status": "pending",
                    "summary_json": '{"description": "Alice PR"}',
                    "created_at": "2025-01-01T10:00:00",
                    "risk_score": 5.0
                },
                "change-bob-456": {
                    "change_id": "change-bob-456",
                    "api_key": "bob-api-key-67890",
                    "status": "pending",
                    "summary_json": '{"description": "Bob PR"}',
                    "created_at": "2025-01-01T11:00:00",
                    "risk_score": 6.0
                },
                "change-legacy-789": {
                    "change_id": "change-legacy-789",
                    # No api_key field (legacy record)
                    "status": "pending",
                    "summary_json": '{"description": "Legacy PR"}',
                    "created_at": "2024-12-01T09:00:00",
                    "risk_score": 4.0
                }
            }
        
        def get_change(self, change_id):
            return self.data.get(change_id)
        
        def set_approval_status(self, change_id, approved, rejected_reason=None):
            if change_id in self.data:
                self.data[change_id]["status"] = "approved" if approved else "rejected"
        
        def set_change_status(self, change_id, status):
            """Update change status"""
            if change_id in self.data:
                self.data[change_id]["status"] = status
    
    return MockStorage()


def mock_verify_api_key_dependency():
    """Override verify_api_key dependency for testing"""
    from fastapi import HTTPException, Header
    from typing import Optional
    
    def _verify_mock(x_api_key: Optional[str] = Header(None, alias="X-API-Key")) -> str:
        # Accept alice and bob keys
        if x_api_key and x_api_key in ["alice-api-key-12345", "bob-api-key-67890"]:
            return x_api_key
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    return _verify_mock


# GET /approvals/{change_id} tests

def test_get_approval_own_change(client, mock_storage):
    """User can get their own approval request"""
    from saferun.app.routers.auth import verify_api_key
    
    # Override auth dependency
    main.app.dependency_overrides[verify_api_key] = mock_verify_api_key_dependency()
    
    # Mock storage at module level where it's actually called
    with patch("saferun.app.routers.approvals.storage_manager.get_storage", return_value=mock_storage):
        try:
            response = client.get(
                "/api/approvals/change-alice-123",
                headers={"X-API-Key": "alice-api-key-12345"}
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["change_id"] == "change-alice-123"
            assert data["status"] == "pending"
        finally:
            main.app.dependency_overrides.clear()


def test_get_approval_wrong_user_404(client, mock_storage):
    """User trying to access another user's approval gets 404 (not 403)"""
    from saferun.app.routers.auth import verify_api_key
    
    main.app.dependency_overrides[verify_api_key] = mock_verify_api_key_dependency()
    
    with patch("saferun.app.routers.approvals.storage_manager.get_storage", return_value=mock_storage):
        try:
            response = client.get(
                "/api/approvals/change-alice-123",  # Alice's change
                headers={"X-API-Key": "bob-api-key-67890"}  # Bob's key
            )
            
            # Returns 404 to prevent enumeration (not 403)
            assert response.status_code == 404
            # SafeRun uses custom error format with "message" field
            data = response.json()
            assert "message" in data or "detail" in data
            message = data.get("message", data.get("detail", ""))
            assert "not found" in message.lower()
        finally:
            main.app.dependency_overrides.clear()


def test_get_approval_no_auth_401(client, mock_storage):
    """Request without API key returns 401"""
    with patch("saferun.app.routers.approvals.storage_manager.get_storage", return_value=mock_storage):
        response = client.get("/api/approvals/change-alice-123")
        assert response.status_code == 401


def test_get_approval_legacy_record_accessible(client, mock_storage):
    """Legacy records (without api_key) remain accessible for backward compat"""
    from saferun.app.routers.auth import verify_api_key
    
    main.app.dependency_overrides[verify_api_key] = mock_verify_api_key_dependency()
    
    with patch("saferun.app.routers.approvals.storage_manager.get_storage", return_value=mock_storage):
        try:
            response = client.get(
                "/api/approvals/change-legacy-789",
                headers={"X-API-Key": "alice-api-key-12345"}
            )
            
            # Legacy record accessible by any valid API key
            assert response.status_code == 200
            data = response.json()
            assert data["change_id"] == "change-legacy-789"
        finally:
            main.app.dependency_overrides.clear()


def test_get_approval_not_found(client, mock_storage):
    """Non-existent change_id returns 404"""
    from saferun.app.routers.auth import verify_api_key
    
    main.app.dependency_overrides[verify_api_key] = mock_verify_api_key_dependency()
    
    with patch("saferun.app.routers.approvals.storage_manager.get_storage", return_value=mock_storage):
        try:
            response = client.get(
                "/api/approvals/change-nonexistent",
                headers={"X-API-Key": "alice-api-key-12345"}
            )
            
            assert response.status_code == 404
        finally:
            main.app.dependency_overrides.clear()


# POST /approvals/{change_id}/approve tests

def test_approve_own_change(client, mock_storage):
    """User can approve their own change"""
    from saferun.app.routers.auth import verify_api_key
    
    main.app.dependency_overrides[verify_api_key] = mock_verify_api_key_dependency()
    
    with patch("saferun.app.routers.approvals.storage_manager.get_storage", return_value=mock_storage):
        with patch("saferun.app.routers.approvals.db.insert_audit"):  # Mock audit logging
            try:
                response = client.post(
                    "/api/approvals/change-alice-123/approve",
                    headers={"X-API-Key": "alice-api-key-12345"}
                )
                
                assert response.status_code == 200
                assert "approved" in response.json()["message"].lower()
            finally:
                main.app.dependency_overrides.clear()


def test_approve_wrong_user_404(client, mock_storage):
    """User cannot approve another user's change (404)"""
    from saferun.app.routers.auth import verify_api_key
    
    main.app.dependency_overrides[verify_api_key] = mock_verify_api_key_dependency()
    
    with patch("saferun.app.routers.approvals.storage_manager.get_storage", return_value=mock_storage):
        try:
            response = client.post(
                "/api/approvals/change-alice-123/approve",  # Alice's change
                headers={"X-API-Key": "bob-api-key-67890"}  # Bob's key
            )
            
            assert response.status_code == 404
        finally:
            main.app.dependency_overrides.clear()


# POST /approvals/{change_id}/reject tests

def test_reject_own_change(client, mock_storage):
    """User can reject their own change"""
    from saferun.app.routers.auth import verify_api_key
    
    main.app.dependency_overrides[verify_api_key] = mock_verify_api_key_dependency()
    
    with patch("saferun.app.routers.approvals.storage_manager.get_storage", return_value=mock_storage):
        with patch("saferun.app.routers.approvals.db.insert_audit"):  # Mock audit logging
            try:
                response = client.post(
                    "/api/approvals/change-bob-456/reject",
                    headers={"X-API-Key": "bob-api-key-67890"},
                    json={"reason": "Not needed"}
                )
                
                assert response.status_code == 200
                assert "rejected" in response.json()["message"].lower()
            finally:
                main.app.dependency_overrides.clear()


def test_reject_wrong_user_404(client, mock_storage):
    """User cannot reject another user's change (404)"""
    from saferun.app.routers.auth import verify_api_key
    
    main.app.dependency_overrides[verify_api_key] = mock_verify_api_key_dependency()
    
    with patch("saferun.app.routers.approvals.storage_manager.get_storage", return_value=mock_storage):
        try:
            response = client.post(
                "/api/approvals/change-bob-456/reject",  # Bob's change
                headers={"X-API-Key": "alice-api-key-12345"},  # Alice's key
                json={"reason": "Should fail"}
            )
            
            assert response.status_code == 404
        finally:
            main.app.dependency_overrides.clear()
