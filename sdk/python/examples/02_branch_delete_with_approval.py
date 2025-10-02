"""Delete a GitHub branch and wait for approval."""
from saferun import SafeRunClient

client = SafeRunClient(api_key="YOUR_API_KEY")
result = client.delete_github_branch(
    repo="owner/repo",
    branch="feature-branch",
    github_token="GITHUB_TOKEN",
)

if result.needs_approval:
    print("Awaiting approval at:", result.approval_url)
    status = client.wait_for_approval(result.change_id, timeout=120, poll_interval=5)
    if status.approved:
        print("Change approved and applied")
    else:
        print("Change not approved:", status)
else:
    print("Branch deleted without approval")
