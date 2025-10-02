import { SafeRunClient } from '@saferun/sdk';

const client = new SafeRunClient({ apiKey: process.env.SAFERUN_API_KEY ?? '' });

export async function safeArchiveRepo(repo) {
  const githubToken = process.env.GITHUB_TOKEN ?? '';
  const result = await client.archiveGithubRepo({ repo, githubToken });
  if (result.needsApproval) {
    return `Approval required: ${result.approvalUrl}`;
  }
  return 'Repository archived';
}
