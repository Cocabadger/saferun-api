"""Example: Manage branch protection rules."""
from saferun import SafeRunClient

# Initialize client
client = SafeRunClient(api_key="YOUR_API_KEY")

# Update branch protection rules
result = client.update_branch_protection(
    repo="owner/repo",
    branch="main",
    github_token="GITHUB_TOKEN",
    required_reviews=2,
    require_code_owner_reviews=True,
    dismiss_stale_reviews=True,
    require_status_checks=True,
    status_checks=["ci/build", "ci/test"],
    enforce_admins=True,
)

if result.needs_approval:
    print(f"⚠️  Branch protection update requires approval")
    print(f"📋 Risk Score: {result.risk_score}/10")
    print(f"🔗 Approve at: {result.approval_url}")
    print(f"\nChanges:")
    print(f"  • Required reviews: 2")
    print(f"  • Code owner reviews: Required")
    print(f"  • Status checks: ci/build, ci/test")
    
    # Wait for approval
    status = client.wait_for_approval(result.change_id)
    
    if status.approved:
        print("✅ Branch protection updated successfully!")
else:
    print("✅ Branch protection updated without approval")

# Delete branch protection
result = client.delete_branch_protection(
    repo="owner/repo",
    branch="feature-test",
    github_token="GITHUB_TOKEN",
)

if result.needs_approval:
    print(f"\n⚠️  Branch protection deletion requires approval")
    print(f"🔗 Approve at: {result.approval_url}")
