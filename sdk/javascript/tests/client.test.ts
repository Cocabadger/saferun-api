import { describe, expect, it, beforeEach, afterEach, vi } from "vitest";
import axios from "axios";
import { SafeRunClient } from "../src/client.js";

const mockPost = vi.fn();

vi.spyOn(axios, "create").mockReturnValue({ post: mockPost } as any);

describe("SafeRunClient", () => {
  beforeEach(() => {
    mockPost.mockReset();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("performs dry run for archive repo", async () => {
    mockPost.mockResolvedValue({
      data: {
        change_id: "chg_123",
        requires_approval: true,
        approve_url: "https://approve",
        risk_score: 0.5,
        reasons: ["policy"],
        expires_at: "2025-01-01T00:00:00Z",
      },
    });

    const client = new SafeRunClient({ apiKey: "test", apiUrl: "https://example.com" });
    const result = await client.archiveGithubRepo({ repo: "owner/repo", githubToken: "token" });

    expect(result.changeId).toBe("chg_123");
    expect(result.needsApproval).toBe(true);
    expect(mockPost).toHaveBeenCalled();
  });
});
