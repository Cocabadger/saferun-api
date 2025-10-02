export class SafeRunError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "SafeRunError";
  }
}

export class SafeRunAPIError extends SafeRunError {
  statusCode: number;
  constructor(statusCode: number, message: string) {
    super(`SafeRun API error (${statusCode}): ${message}`);
    this.name = "SafeRunAPIError";
    this.statusCode = statusCode;
  }
}

export class SafeRunApprovalTimeout extends SafeRunError {
  changeId: string;
  timeoutMs: number;
  constructor(changeId: string, timeoutMs: number) {
    super(`Timed out waiting for approval of change ${changeId} after ${timeoutMs}ms`);
    this.name = "SafeRunApprovalTimeout";
    this.changeId = changeId;
    this.timeoutMs = timeoutMs;
  }
}
