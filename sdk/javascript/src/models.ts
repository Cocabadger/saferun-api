import type { SafeRunClient } from "./client.js";

export interface ApprovalStatus {
  approved: boolean;
  rejected: boolean;
  expired: boolean;
  pending: boolean;
  status?: string;
}

export interface ChangeStatus {
  changeId: string;
  status: string;
  requiresApproval: boolean;
  approved: boolean;
  humanPreview?: string;
  operationType?: string;
  riskScore?: number;
  reasons?: string[];
}

export class RevertResult {
  constructor(
    public readonly revertToken: string,
    public readonly status: string,
    public readonly revertedAt: Date,
  ) {}
}

export class ApplyResult {
  constructor(
    public readonly changeId: string,
    public readonly status: string,
    public readonly revertToken: string | undefined,
    public readonly appliedAt: Date,
    private readonly client: SafeRunClient,
  ) {}

  async revert(): Promise<RevertResult> {
    if (!this.revertToken) {
      throw new Error("Revert token is not available for this change");
    }
    return this.client.revertChange(this.revertToken);
  }
}

export class DryRunResult {
  constructor(
    public readonly changeId: string,
    public readonly needsApproval: boolean,
    public readonly approvalUrl: string | undefined,
    public readonly rejectUrl: string | undefined,
    public readonly riskScore: number,
    public readonly reasons: string[],
    public readonly humanPreview: string,
    public readonly expiresAt: Date,
    public readonly revertUrl: string | undefined,
    public readonly revertWindowHours: number | undefined,
    private readonly client: SafeRunClient,
  ) {}

  approve(): Promise<ApplyResult> {
    return this.client.applyChange(this.changeId, true);
  }

  async reject(): Promise<void> {
    throw new Error("SafeRun API currently handles rejection via approval endpoint");
  }

  getStatus(): Promise<ApprovalStatus> {
    return this.client.getApprovalStatus(this.changeId);
  }
}
