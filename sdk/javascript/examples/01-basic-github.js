import { SafeRunClient } from "@saferun/sdk";

const client = new SafeRunClient({ apiKey: "YOUR_API_KEY" });

const result = await client.archiveGithubRepo({
  repo: "owner/repo",
  githubToken: "GITHUB_TOKEN",
});

if (result.needsApproval) {
  console.log("Approval required:", result.approvalUrl);
} else {
  console.log("Archived without approval");
}
