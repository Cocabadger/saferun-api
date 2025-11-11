"""Example: Manage GitHub Actions secrets."""
from saferun import SafeRunClient

# Initialize client
client = SafeRunClient(api_key="YOUR_API_KEY")

# Create or update a secret
result = client.create_or_update_secret(
    repo="owner/repo",
    secret_name="API_KEY",
    secret_value="sk_live_abc123xyz",
    github_token="GITHUB_TOKEN",
)

if result.needs_approval:
    print(f"⚠️  Secret update requires approval")
    print(f"📋 Risk Score: {result.risk_score}/10")
    print(f"🔗 Approve at: {result.approval_url}")
    
    # Wait for approval
    status = client.wait_for_approval(result.change_id)
    
    if status.approved:
        print("✅ Secret created/updated successfully!")
else:
    print("✅ Secret created/updated without approval")

# Delete a secret
result = client.delete_secret(
    repo="owner/repo",
    secret_name="OLD_API_KEY",
    github_token="GITHUB_TOKEN",
)

if result.needs_approval:
    print(f"\n⚠️  Secret deletion requires approval")
    print(f"🔗 Approve at: {result.approval_url}")
