"""Pytest configuration and fixtures."""
import os
import sys
import pytest

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Set test environment variables
os.environ["SR_STORAGE_BACKEND"] = "sqlite"
os.environ["SR_SQLITE_PATH"] = ":memory:"
os.environ["SR_LOG_LEVEL"] = "ERROR"
os.environ["SR_FREE_TIER_LIMIT"] = "1000"


@pytest.fixture
def mock_env_vars(monkeypatch):
    """Mock environment variables for tests."""
    test_vars = {
        "SR_STORAGE_BACKEND": "sqlite",
        "SR_SQLITE_PATH": ":memory:",
        "SR_LOG_LEVEL": "ERROR",
        "APP_BASE_URL": "https://test.saferun.dev",
    }
    for key, value in test_vars.items():
        monkeypatch.setenv(key, value)
    return test_vars


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    import asyncio
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()
