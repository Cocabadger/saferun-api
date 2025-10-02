# SafeRun JavaScript SDK

Node.js/TypeScript client for SafeRun API.

```bash
npm install @saferun/sdk
```

```ts
import { SafeRunClient } from "@saferun/sdk";

const client = new SafeRunClient({ apiKey: "your-api-key" });
const result = await client.archiveGithubRepo({
  repo: "owner/repo",
  githubToken: "ghp_xxx",
});
console.log(result.changeId);
```
