import axios, { AxiosInstance } from "axios";
import {
  APPLY_ENDPOINT,
  DEFAULT_API_URL,
  DEFAULT_MAX_RETRIES,
  DEFAULT_TIMEOUT,
  DRY_RUN_ENDPOINTS,
  GIT_OPERATION_CONFIRM_ENDPOINT,
  GIT_OPERATION_STATUS_ENDPOINT,
  REVERT_ENDPOINT,
} from "./constants.js";
import { SafeRunAPIError, SafeRunApprovalTimeout } from "./exceptions.js";
import { ApplyResult, ApprovalStatus, ChangeStatus, DryRunResult, RevertResult } from "./models.js";

export interface SafeRunClientOptions {
  apiKey: string;
  apiUrl?: string;
  timeout?: number;
  maxRetries?: number;
}

export interface DryRunPayload extends Record<string, any> {
  token?: string;
  notion_token?: string;
  page_id?: string;
  target_id?: string;
  webhook_url?: string;
  policy?: Record<string, any>;
  metadata?: Record<string, unknown>;
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export class SafeRunClient {
  private readonly apiUrl: string;
  private readonly timeout: number;
  private readonly maxRetries: number;
  private readonly http: AxiosInstance;

  constructor(options: SafeRunClientOptions) {
    this.apiUrl = (options.apiUrl ?? DEFAULT_API_URL).replace(/\/$/, "");
    this.timeout = options.timeout ?? DEFAULT_TIMEOUT;
    this.maxRetries = options.maxRetries ?? DEFAULT_MAX_RETRIES;
    this.http = axios.create({
      baseURL: this.apiUrl,
      timeout: this.timeout,
      headers: {
        "Content-Type": "application/json",
        "X-API-Key": options.apiKey,
      },
    });
  }

  archiveGithubRepo(params: {
    repo: string;
    githubToken: string;
    webhookUrl?: string;
    policy?: Record<string, unknown>;
  }): Promise<DryRunResult> {
    return this.dryRun("github_archive_repo", {
      token: params.githubToken,
      target_id: params.repo,
      webhook_url: params.webhookUrl,
      policy: params.policy,
    });
  }

  deleteGithubRepo(params: {
    repo: string;
    githubToken: string;
    reason?: string;
    webhookUrl?: string;
    policy?: Record<string, unknown>;
  }): Promise<DryRunResult> {
    return this.dryRun("github_delete_repo", {
      token: params.githubToken,
      target_id: params.repo,
      reason: params.reason || "Delete repository (PERMANENT - cannot be undone)",
      webhook_url: params.webhookUrl,
      policy: params.policy,
    });
  }

  deleteGithubBranch(params: {
    repo: string;
    branch: string;
    githubToken: string;
    webhookUrl?: string;
    policy?: Record<string, unknown>;
    metadata?: Record<string, unknown>;
  }): Promise<DryRunResult> {
    return this.dryRun("github_delete_branch", {
      token: params.githubToken,
      target_id: `${params.repo}#${params.branch}`,
      webhook_url: params.webhookUrl,
      policy: params.policy,
      metadata: params.metadata,
    });
  }

  bulkCloseGithubPrs(params: {
    repo: string;
    githubToken: string;
    view?: string;
    webhookUrl?: string;
    policy?: Record<string, unknown>;
  }): Promise<DryRunResult> {
    const target = params.view ? `${params.repo}@${params.view}` : params.repo;
    return this.dryRun("github_bulk_close_prs", {
      token: params.githubToken,
      target_id: target,
      webhook_url: params.webhookUrl,
      policy: params.policy,
    });
  }

  forcePushGithub(params: {
    repo: string;
    branch: string;
    githubToken: string;
    reason?: string;
    webhookUrl?: string;
    policy?: Record<string, unknown>;
    metadata?: Record<string, unknown>;
  }): Promise<DryRunResult> {
    return this.dryRun("github_force_push", {
      token: params.githubToken,
      target_id: `${params.repo}#${params.branch}`,
      reason: params.reason,
      webhook_url: params.webhookUrl,
      policy: params.policy,
      metadata: params.metadata,
    });
  }

  mergeGithub(params: {
    repo: string;
    sourceBranch: string;
    targetBranch: string;
    githubToken: string;
    reason?: string;
    webhookUrl?: string;
    policy?: Record<string, unknown>;
  }): Promise<DryRunResult> {
    return this.dryRun("github_merge", {
      token: params.githubToken,
      target_id: params.repo,
      source_branch: params.sourceBranch,
      target_branch: params.targetBranch,
      reason: params.reason,
      webhook_url: params.webhookUrl,
      policy: params.policy,
    });
  }

  gitOperation(params: {
    operationType: string;
    target: string;
    command: string;
    metadata?: Record<string, unknown>;
    riskScore: number;
    humanPreview: string;
    requiresApproval?: boolean;
    reasons?: string[];
    policy?: Record<string, unknown>;
    webhookUrl?: string;
    ttlMinutes?: number;
  }): Promise<DryRunResult> {
    return this.dryRun("git_operation", {
      operation_type: params.operationType,
      target: params.target,
      command: params.command,
      metadata: params.metadata ?? {},
      risk_score: params.riskScore,
      human_preview: params.humanPreview,
      requires_approval: params.requiresApproval,
      reasons: params.reasons ?? [],
      policy: params.policy,
      webhook_url: params.webhookUrl,
      ttl_minutes: params.ttlMinutes,
    });
  }

  archiveNotionPage(params: {
    pageId: string;
    notionToken: string;
    webhookUrl?: string;
    policy?: Record<string, unknown>;
  }): Promise<DryRunResult> {
    return this.dryRun("notion_archive_page", {
      notion_token: params.notionToken,
      page_id: params.pageId,
      webhook_url: params.webhookUrl,
      policy: params.policy,
    });
  }

  async dryRun(operation: string, payload: DryRunPayload): Promise<DryRunResult> {
    const endpoint = DRY_RUN_ENDPOINTS[operation];
    if (!endpoint) {
      throw new Error(`Unsupported operation: ${operation}`);
    }
    const data = await this.post(endpoint, payload);
    return this.parseDryRun(data);
  }

  async applyChange(changeId: string, approval = true): Promise<ApplyResult> {
    const data = await this.post(APPLY_ENDPOINT, { change_id: changeId, approval });
    return this.parseApply(data);
  }

  async revertChange(revertToken: string): Promise<RevertResult> {
    const data = await this.post(REVERT_ENDPOINT, { revert_token: revertToken });
    return this.parseRevert(data);
  }

  async getApprovalStatus(changeId: string): Promise<ApprovalStatus> {
    try {
      const { data } = await this.http.get(GIT_OPERATION_STATUS_ENDPOINT(changeId));
      const status = this.parseChangeStatus(data);
      return {
        approved: status.approved,
        rejected: status.status === "cancelled" || status.status === "failed" || status.status === "rejected",
        expired: status.status === "expired",
        pending: !status.approved && status.status === "pending",
        status: status.status,
      };
    } catch (error: any) {
      const status = error?.response?.status;
      if (status === 404) {
        return {
          approved: false,
          rejected: false,
          expired: false,
          pending: false,
          status: "not_found",
        };
      }
      throw error;
    }
  }

  async waitForApproval(
    changeId: string,
    options: { timeout?: number; pollInterval?: number; autoApply?: boolean } = {},
  ): Promise<ApprovalStatus> {
    const timeoutMs = options.timeout ?? 300_000;
    const pollMs = options.pollInterval ?? 2000;
    const autoApply = options.autoApply ?? true;
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
      if (autoApply) {
        try {
          const result = await this.applyChange(changeId, true);
          return {
            approved: ["applied", "already_applied"].includes(result.status),
            rejected: false,
            expired: false,
            pending: false,
            status: result.status,
          };
        } catch (error: any) {
          if (!(error instanceof SafeRunAPIError && [403, 409].includes(error.statusCode))) {
            throw error;
          }
          // continue to polling
        }
      }

      const status = await this.getApprovalStatus(changeId);
      if (status.expired) {
        throw new SafeRunApprovalTimeout(changeId, timeoutMs);
      }
      if (status.approved || status.rejected) {
        return status;
      }
      await sleep(pollMs);
    }
    throw new SafeRunApprovalTimeout(changeId, timeoutMs);
  }

  async confirmGitOperation(params: {
    changeId: string;
    status?: "applied" | "cancelled" | "failed";
    metadata?: Record<string, unknown>;
  }): Promise<ChangeStatus> {
    const payload = {
      change_id: params.changeId,
      status: params.status ?? "applied",
      metadata: params.metadata ?? {},
    };
    const { data } = await this.http.post(GIT_OPERATION_CONFIRM_ENDPOINT, payload);
    return this.parseChangeStatus(data);
  }

  private async post(path: string, payload: Record<string, unknown>): Promise<any> {
    let attempt = 0;
    while (true) {
      try {
        const response = await this.http.post(path, payload);
        return response.data;
      } catch (error: any) {
        attempt += 1;
        const status = error?.response?.status;
        const message = error?.response?.data?.message || error?.message || "Unknown error";
        if (status && status >= 400) {
          throw new SafeRunAPIError(status, typeof message === "string" ? message : JSON.stringify(message));
        }
        if (attempt >= this.maxRetries) {
          throw error;
        }
        await sleep(2 ** attempt * 100);
      }
    }
  }

  private parseDryRun(data: any): DryRunResult {
    // Support both camelCase (needsApproval) and snake_case (requires_approval) for backwards compatibility
    const needsApproval = data?.needsApproval !== undefined 
      ? Boolean(data.needsApproval) 
      : Boolean(data?.requires_approval);
    
    return new DryRunResult(
      data?.change_id ?? "",
      needsApproval,
      data?.approve_url ?? undefined,
      data?.reject_url ?? undefined,
      Number(data?.risk_score ?? 0),
      Array.isArray(data?.reasons) ? data.reasons : [],
      data?.human_preview ?? "",
      this.parseDate(data?.expires_at),
      data?.revert_url ?? undefined,
      data?.revert_window_hours ?? undefined,
      this,
    );
  }

  private parseApply(data: any): ApplyResult {
    return new ApplyResult(
      data?.change_id ?? "",
      data?.status ?? "",
      data?.revert_token ?? undefined,
      this.parseDate(data?.applied_at),
      this,
    );
  }

  private parseRevert(data: any): RevertResult {
    return new RevertResult(
      data?.revert_token ?? "",
      data?.status ?? "",
      this.parseDate(data?.reverted_at),
    );
  }

  private parseChangeStatus(data: any): ChangeStatus {
    return {
      changeId: data?.change_id ?? "",
      status: data?.status ?? "unknown",
      requiresApproval: Boolean(data?.requires_approval),
      approved: Boolean(data?.approved),
      humanPreview: data?.human_preview,
      operationType: data?.operation_type,
      riskScore: typeof data?.risk_score === "number" ? data.risk_score : undefined,
      reasons: Array.isArray(data?.reasons) ? data.reasons : [],
    };
  }

  private parseDate(value?: string): Date {
    if (!value) {
      return new Date();
    }
    const iso = value.endsWith("Z") ? value : `${value}`;
    const date = new Date(iso);
    return Number.isNaN(date.getTime()) ? new Date() : date;
  }
}
