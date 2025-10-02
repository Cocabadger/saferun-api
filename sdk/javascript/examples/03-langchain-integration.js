import { SafeRunClient } from "@saferun/sdk";

const client = new SafeRunClient({ apiKey: "YOUR_API_KEY" });

export async function safeDeleteBranch(input) {
  const [repo, branch] = input.split(":");
  const result = await client.deleteGithubBranch({
    repo,
    branch,
    githubToken: "GITHUB_TOKEN",
  });
  if (result.needsApproval) {
    return `Approval required: ${result.approvalUrl}`;
  }
  return `Branch ${branch} deleted`;
}
