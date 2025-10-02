"""LangChain tool example using SafeRun."""
from langchain.tools import Tool
from saferun import SafeRunClient

client = SafeRunClient(api_key="YOUR_API_KEY")

def safe_delete_branch(repo_and_branch: str) -> str:
    repo, branch = repo_and_branch.split(":")
    result = client.delete_github_branch(
        repo=repo,
        branch=branch,
        github_token="GITHUB_TOKEN",
    )
    if result.needs_approval:
        return f"Approval required: {result.approval_url}"
    return "Branch deleted"

safe_delete_tool = Tool(
    name="SafeDeleteBranch",
    description="Safely delete a GitHub branch",
    func=safe_delete_branch,
)
