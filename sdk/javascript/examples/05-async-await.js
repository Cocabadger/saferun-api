import { SafeRunClient } from "@saferun/sdk";

const client = new SafeRunClient({ apiKey: "YOUR_API_KEY" });

const result = await client.bulkCloseGithubPrs({
  repo: "owner/repo",
  githubToken: "GITHUB_TOKEN",
  view: "open",
});

if (result.needsApproval) {
  console.log("Waiting for approval at:", result.approvalUrl);
  const status = await client.waitForApproval(result.changeId, { pollInterval: 5000 });
  if (status.approved) {
    console.log("Change applied");
  }
}
