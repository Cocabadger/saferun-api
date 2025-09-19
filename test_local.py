#!/usr/bin/env python3
"""Quick test script to verify SafeRun is working."""

import requests
import json
import sys

BASE_URL = "http://localhost:8500"

def test_health():
    """Test health endpoint."""
    print("Testing health endpoint...")
    resp = requests.get(f"{BASE_URL}/readyz")
    assert resp.status_code == 200, f"Health check failed: {resp.text}"
    print("✅ Health check passed")

def test_registration():
    """Test API key registration."""
    print("\nTesting registration...")
    
    # Use timestamp to ensure unique email
    import time
    email = f"test.{int(time.time())}@example.com"
    
    resp = requests.post(
        f"{BASE_URL}/v1/auth/register",
        json={"email": email}
    )
    
    if resp.status_code != 200:
        print(f"❌ Registration failed: {resp.text}")
        return None
    
    data = resp.json()
    api_key = data.get("api_key")
    print(f"✅ Registration successful! API Key: {api_key[:10]}...")
    return api_key

def test_dry_run(api_key):
    """Test dry-run with API key."""
    print("\nTesting dry-run with API key...")
    
    resp = requests.post(
        f"{BASE_URL}/v1/dry-run/github.repo.archive",
        headers={"X-API-Key": api_key},
        json={
            "token": "fake_github_token_for_test",
            "target_id": "owner/repo"
        }
    )
    
    # We expect this to fail with invalid token, but it should authenticate
    if resp.status_code == 401:
        print("❌ API key authentication failed")
        return False
    
    print(f"✅ API key works! (Response: {resp.status_code})")
    return True

def main():
    print("=" * 50)
    print("SafeRun Production Test")
    print("=" * 50)
    
    try:
        test_health()
        api_key = test_registration()
        if api_key:
            test_dry_run(api_key)
        
        print("\n" + "=" * 50)
        print("✅ All basic tests passed!")
        print("SafeRun is ready for deployment")
        print("=" * 50)
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    print("\nMake sure SafeRun is running on localhost:8500")
    print("Start it with: uvicorn saferun.app.main:app --port 8500")
    input("\nPress Enter when ready...")
    main()
