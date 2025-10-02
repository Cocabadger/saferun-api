"""Basic example: archive a GitHub repository."""
from saferun import SafeRunClient

client = SafeRunClient(api_key="YOUR_API_KEY")
result = client.archive_github_repo(
    repo="owner/repo",
    github_token="GITHUB_TOKEN",
)

if result.needs_approval:
    print("Approval required:", result.approval_url)
else:
    print("Archived without approval")
