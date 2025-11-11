"""Example: Change repository visibility."""
from saferun import SafeRunClient

# Initialize client
client = SafeRunClient(api_key="YOUR_API_KEY")

# Make repository private
result = client.change_repository_visibility(
    repo="owner/repo",
    private=True,  # True = private, False = public
    github_token="GITHUB_TOKEN",
)

if result.needs_approval:
    print(f"⚠️  Visibility change requires approval")
    print(f"📋 Risk Score: {result.risk_score}/10")
    print(f"🔗 Approve at: {result.approval_url}")
    print(f"\nChange: Public → Private")
    print(f"\nReasons:")
    for reason in result.reasons:
        print(f"  • {reason}")
    
    # Wait for approval
    status = client.wait_for_approval(result.change_id)
    
    if status.approved:
        print("✅ Repository is now private!")
    else:
        print("❌ Visibility change rejected")
else:
    print("✅ Repository visibility changed without approval")

# Make repository public (high risk!)
result = client.change_repository_visibility(
    repo="owner/private-repo",
    private=False,  # Making public
    github_token="GITHUB_TOKEN",
)

print(f"\n⚠️  Making repo public - HIGH RISK!")
print(f"📋 Risk Score: {result.risk_score}/10")
print(f"🔗 Approve at: {result.approval_url}")
