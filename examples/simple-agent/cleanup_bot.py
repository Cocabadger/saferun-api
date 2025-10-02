"""SafeRun Cleanup Bot
Deletes old branches while respecting SafeRun approvals."""
import os
from datetime import datetime, timedelta

from github import Github
from saferun import SafeRunClient

saferun_client = SafeRunClient(api_key=os.getenv('SAFERUN_API_KEY', ''))
github_client = Github(os.getenv('GITHUB_TOKEN', ''))


def cleanup_old_branches(repo_name: str, days_old: int = 90) -> None:
    repo = github_client.get_repo(repo_name)
    cutoff = datetime.utcnow() - timedelta(days=days_old)
    for branch in repo.get_branches():
        if branch.name in {'main', 'master', 'develop'}:
            continue
        last_commit = branch.commit.commit.author.date
        if last_commit.replace(tzinfo=None) < cutoff:
            print(f"Branch {branch.name} is stale")
            result = saferun_client.delete_github_branch(
                repo=repo_name,
                branch=branch.name,
                github_token=os.getenv('GITHUB_TOKEN', ''),
            )
            if result.needs_approval:
                print('  Approval required:', result.approval_url)
            else:
                print('  Deleted automatically')


if __name__ == '__main__':
    cleanup_old_branches('owner/repo', days_old=90)
