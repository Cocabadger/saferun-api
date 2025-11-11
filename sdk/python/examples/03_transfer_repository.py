"""Example: Transfer GitHub repository to another owner."""
from saferun import SafeRunClient

# Initialize client
client = SafeRunClient(api_key="YOUR_API_KEY")

# Transfer repository to new owner
result = client.transfer_repository(
    repo="your-org/my-repo",
    new_owner="target-org",
    github_token="GITHUB_TOKEN",
)

if result.needs_approval:
    print(f"⚠️  Repository transfer requires approval")
    print(f"📋 Risk Score: {result.risk_score}/10")
    print(f"🔗 Approve at: {result.approval_url}")
    print(f"\nReasons:")
    for reason in result.reasons:
        print(f"  • {reason}")
    
    # Wait for approval
    print("\n⏳ Waiting for approval...")
    status = client.wait_for_approval(result.change_id, timeout=300)
    
    if status.approved:
        print("✅ Repository transferred successfully!")
    else:
        print("❌ Transfer rejected or timed out")
else:
    print("✅ Repository transferred without approval")
