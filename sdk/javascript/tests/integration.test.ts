import { describe, it, expect } from "vitest";
import { SafeRunClient } from "../src/client.js";

describe.skip("SafeRun integration", () => {
  it("should archive repo via live API", async () => {
    const apiKey = process.env.SAFERUN_API_KEY;
    if (!apiKey) {
      throw new Error("SAFERUN_API_KEY not set");
    }
    const client = new SafeRunClient({ apiKey });
    const result = await client.archiveGithubRepo({
      repo: "owner/repo",
      githubToken: "ghp_example",
    });
    expect(result.changeId).toBeTruthy();
  });
});
