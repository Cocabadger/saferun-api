"""
E2E Test for Delete Branch API endpoint
TEST #25: Delete Branch via API with approval flow

Requires environment variables:
- SAFERUN_API_KEY: SafeRun API key (sr_...)
- GITHUB_TOKEN: GitHub personal access token with repo scope
"""
import os
import requests
import time
from datetime import datetime

# Test configuration - uses environment variables for security
API_BASE = os.getenv("SAFERUN_API_URL", "https://saferun-api.up.railway.app")
API_KEY = os.getenv("SAFERUN_API_KEY", "")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
OWNER = os.getenv("GITHUB_TEST_OWNER", "Cocabadger")
REPO = os.getenv("GITHUB_TEST_REPO", "test-sf-v01")

def test_delete_branch_api():
    """
    TEST #25: Delete Branch via API
    
    Flow:
    1. Create test branch via GitHub API
    2. Call SafeRun API to delete branch (creates pending operation)
    3. Verify Slack notification sent
    4. Approve via API
    5. Verify branch deleted
    6. Test revert (restore branch)
    
    Skip if required environment variables are not set.
    """
    
    # Skip if tokens not configured
    if not API_KEY or not GITHUB_TOKEN:
        import pytest
        pytest.skip("SAFERUN_API_KEY and GITHUB_TOKEN environment variables required for E2E tests")
    
    # Generate unique branch name
    timestamp = int(time.time())
    branch_name = f"test-delete-api-{timestamp}"
    
    print(f"\n{'='*60}")
    print(f"TEST #25: Delete Branch API - {datetime.now().isoformat()}")
    print(f"{'='*60}")
    print(f"Branch: {branch_name}")
    print(f"Repo: {OWNER}/{REPO}")
    
    # Step 1: Create test branch via GitHub API
    print(f"\n[STEP 1] Creating test branch '{branch_name}'...")
    
    # Get main branch SHA
    response = requests.get(
        f"https://api.github.com/repos/{OWNER}/{REPO}/git/ref/heads/main",
        headers={"Authorization": f"Bearer {GITHUB_TOKEN}"}
    )
    assert response.status_code == 200, f"Failed to get main branch: {response.text}"
    main_sha = response.json()["object"]["sha"]
    print(f"  ✅ Main branch SHA: {main_sha[:8]}...")
    
    # Create new branch
    response = requests.post(
        f"https://api.github.com/repos/{OWNER}/{REPO}/git/refs",
        headers={"Authorization": f"Bearer {GITHUB_TOKEN}"},
        json={"ref": f"refs/heads/{branch_name}", "sha": main_sha}
    )
    assert response.status_code == 201, f"Failed to create branch: {response.text}"
    print(f"  ✅ Branch created: {branch_name}")
    
    # Step 2: Call SafeRun API to delete branch
    print(f"\n[STEP 2] Calling SafeRun API to delete branch...")
    response = requests.delete(
        f"{API_BASE}/v1/github/repos/{OWNER}/{REPO}/branches/{branch_name}",
        headers={
            "X-API-Key": API_KEY,
            "Content-Type": "application/json"
        },
        json={
            "token": GITHUB_TOKEN,
            "reason": f"TEST #25 - Delete branch API test ({timestamp})"
        }
    )
    
    print(f"  Status: {response.status_code}")
    print(f"  Response: {response.text}")
    
    assert response.status_code == 200, f"API call failed: {response.text}"
    
    data = response.json()
    change_id = data["change_id"]
    
    print(f"\n  ✅ Operation created:")
    print(f"     Change ID: {change_id}")
    print(f"     Status: {data['status']}")
    print(f"     Requires Approval: {data['requires_approval']}")
    print(f"     Risk Score: {data['risk_score']}")
    print(f"     Revertable: {data['revertable']}")
    print(f"     Revert Type: {data['revert_type']}")
    
    # Assertions
    assert data["status"] == "pending", "Status should be pending"
    assert data["requires_approval"] == True, "Should require approval"
    assert data["risk_score"] == 4.0, f"Risk score should be 4.0 for non-main branch, got {data['risk_score']}"
    assert data["revertable"] == True, "Should be revertable"
    assert data["revert_type"] == "branch_restore", "Revert type should be branch_restore"
    
    # Step 3: Verify Slack notification
    print(f"\n[STEP 3] Slack notification should be sent to #saferun-alerts")
    print(f"  📨 Check Slack for approval request:")
    print(f"     Operation: Delete Branch")
    print(f"     Branch: {branch_name}")
    print(f"     Repository: {OWNER}/{REPO}")
    print(f"     Risk Score: 4.0/10")
    print(f"     Change ID: {change_id}")
    
    # Step 4: Approve operation
    print(f"\n[STEP 4] Approving operation...")
    input("  ⏸️  Press Enter after verifying Slack notification to approve...")
    
    response = requests.post(
        f"{API_BASE}/api/approvals/{change_id}/approve",
        headers={"X-API-Key": API_KEY}
    )
    
    print(f"  Status: {response.status_code}")
    assert response.status_code == 200, f"Approval failed: {response.text}"
    print(f"  ✅ Operation approved")
    
    # Wait for execution
    time.sleep(2)
    
    # Step 5: Verify branch deleted
    print(f"\n[STEP 5] Verifying branch deleted...")
    response = requests.get(
        f"https://api.github.com/repos/{OWNER}/{REPO}/git/ref/heads/{branch_name}",
        headers={"Authorization": f"Bearer {GITHUB_TOKEN}"}
    )
    
    assert response.status_code == 404, f"Branch should be deleted, but got status {response.status_code}"
    print(f"  ✅ Branch deleted successfully")
    
    # Step 6: Test revert (restore branch)
    print(f"\n[STEP 6] Testing revert (restore branch)...")
    print(f"  📨 Check Slack for revert command...")
    input("  ⏸️  Press Enter to continue with revert...")
    
    response = requests.post(
        f"{API_BASE}/webhooks/github/revert/{change_id}",
        headers={"Content-Type": "application/json"},
        json={"github_token": GITHUB_TOKEN}
    )
    
    print(f"  Status: {response.status_code}")
    print(f"  Response: {response.text}")
    assert response.status_code == 200, f"Revert failed: {response.text}"
    
    revert_data = response.json()
    print(f"  ✅ Revert executed:")
    print(f"     Status: {revert_data['status']}")
    print(f"     Revert Type: {revert_data['revert_type']}")
    
    # Verify branch restored
    time.sleep(2)
    response = requests.get(
        f"https://api.github.com/repos/{OWNER}/{REPO}/git/ref/heads/{branch_name}",
        headers={"Authorization": f"Bearer {GITHUB_TOKEN}"}
    )
    
    assert response.status_code == 200, f"Branch should be restored, but got status {response.status_code}"
    restored_sha = response.json()["object"]["sha"]
    print(f"  ✅ Branch restored: {branch_name}")
    print(f"     SHA: {restored_sha[:8]}...")
    
    # Cleanup: Delete test branch
    print(f"\n[CLEANUP] Deleting test branch...")
    requests.delete(
        f"https://api.github.com/repos/{OWNER}/{REPO}/git/refs/heads/{branch_name}",
        headers={"Authorization": f"Bearer {GITHUB_TOKEN}"}
    )
    print(f"  ✅ Cleanup complete")
    
    print(f"\n{'='*60}")
    print(f"✅ TEST #25 PASSED - Delete Branch API")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    test_delete_branch_api()
