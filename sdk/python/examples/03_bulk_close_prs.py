"""Bulk close GitHub PRs safely."""
from saferun import SafeRunClient

client = SafeRunClient(api_key="YOUR_API_KEY")
result = client.bulk_close_github_prs(
    repo="owner/repo",
    github_token="GITHUB_TOKEN",
    view="open_prs",
)

print("Change ID:", result.change_id)
print("Needs approval:", result.needs_approval)
if result.needs_approval:
    print("Approve at:", result.approval_url)
