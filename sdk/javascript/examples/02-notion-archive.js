import { SafeRunClient } from "@saferun/sdk";

const client = new SafeRunClient({ apiKey: "YOUR_API_KEY" });

const result = await client.archiveNotionPage({
  pageId: "NOTION_PAGE_ID",
  notionToken: "NOTION_TOKEN",
});

console.log("Change ID:", result.changeId);
console.log("Needs approval:", result.needsApproval);
