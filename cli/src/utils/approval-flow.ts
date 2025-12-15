import readline from 'readline';
import chalk from 'chalk';
import open from 'open';
import ora from 'ora';
import https from 'https';
import { DryRunResult, SafeRunClient, SafeRunApprovalTimeout } from '@saferun/sdk';
import { MetricsCollector } from './metrics';
import { SafeRunConfig, ModeSettings } from './config';

export interface ApprovalFlowOptions {
  client: SafeRunClient;
  metrics?: MetricsCollector;
  pollIntervalMs?: number;
  timeoutMs?: number;
  config?: SafeRunConfig;
  modeSettings?: ModeSettings;
}

export enum ApprovalOutcome {
  Approved = 'approved',
  // SECURITY: Bypassed outcome removed - no bypass mechanism exists
  Cancelled = 'cancelled',
}

export class ApprovalFlow {
  private readonly rl: readline.Interface;
  private readonly client: SafeRunClient;
  private readonly metrics?: MetricsCollector;
  private readonly pollInterval: number;
  private readonly timeout: number;
  private readonly config?: SafeRunConfig;
  private readonly modeSettings?: ModeSettings;

  constructor(options: ApprovalFlowOptions) {
    this.client = options.client;
    this.metrics = options.metrics;
    this.pollInterval = options.pollIntervalMs ?? 2_000;
    this.timeout = options.timeoutMs ?? 2 * 60 * 60_000; // 2 hours (matches server approval timeout)
    this.config = options.config;
    this.modeSettings = options.modeSettings;
    this.rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  }

  async requestApproval(result: DryRunResult): Promise<ApprovalOutcome> {
    if (!result.needsApproval) {
      this.close();
      return ApprovalOutcome.Approved;
    }

    this.showPreview(result);
    const approvalUrl = result.approvalUrl ?? 'https://app.saferun.dev';

    // Check if stdin is interactive (TTY)
    const isInteractive = process.stdin.isTTY;

    if (!isInteractive) {
      // Non-interactive mode (git hooks) - show clean approval UI
      console.log(chalk.bold('\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'));
      console.log(chalk.bold.yellow('📋 Approval Required'));
      console.log(chalk.bold('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n'));
      console.log(chalk.cyan('🌐 Open this URL to approve or reject:'));
      console.log(chalk.bold.cyan(`   ${approvalUrl}\n`));
      this.close();
      return this.waitForApproval(result);
    }

    // Interactive mode - start polling immediately in background
    // User can approve via Slack/Web while we show options
    const pollingPromise = this.waitForApprovalBackground(result);
    
    // Show options menu
    const options = this.buildOptions(result, approvalUrl);
    this.printOptions(options);
    console.log(chalk.gray('\n💡 Approve in Slack or Web - CLI will auto-detect'));

    try {
      // Race between user input and background polling
      const userInputPromise = this.waitForUserInput(options, result, approvalUrl);
      
      const outcome = await Promise.race([pollingPromise, userInputPromise]);
      
      // Clean up - cancel the other promise
      this.cancelPolling = true;
      
      return outcome;
    } finally {
      this.close();
    }
  }
  
  private cancelPolling = false;
  
  private async waitForUserInput(
    options: Array<{ key: string; label: string; action: () => Promise<ApprovalOutcome> }>,
    result: DryRunResult,
    approvalUrl: string
  ): Promise<ApprovalOutcome> {
    while (!this.cancelPolling) {
      const choice = (await this.prompt('\nSelect option: ')).trim();
      
      if (this.cancelPolling) {
        // Polling finished while waiting for input
        return ApprovalOutcome.Approved;
      }
      
      const option = options.find((entry) => entry.key === choice);
      if (!option) {
        console.log(chalk.red('Invalid selection. Please choose one of the available options.'));
        continue;
      }
      
      // For cancel, return immediately
      if (option.key === '5') {
        return ApprovalOutcome.Cancelled;
      }

      const outcome = await option.action();
      return outcome;
    }
    return ApprovalOutcome.Approved;
  }
  
  private async waitForApprovalBackground(result: DryRunResult): Promise<ApprovalOutcome> {
    const approvalUrl = result.approvalUrl ?? 'https://app.saferun.dev';

    // QR code already shown in showPreview()

    const startTime = Date.now();

    // Silent polling - no spinner since user is looking at menu
    while (!this.cancelPolling && Date.now() - startTime < this.timeout) {
      try {
        const status = await this.client.getApprovalStatus(result.changeId);

        // Check final success statuses first
        if (status.status === 'executed' || status.status === 'applied') {
          console.log(chalk.green('\n✓ Operation approved and executed!'));
          this.metrics?.track('operation_executed', { change_id: result.changeId }).catch(() => undefined);
          return ApprovalOutcome.Approved;
        }

        if (status.status === 'reverted') {
          console.log(chalk.yellow('\n↩ Operation was reverted'));
          return ApprovalOutcome.Approved;
        }

        // Check failure statuses
        if (status.rejected || ['failed', 'rejected', 'cancelled'].includes(status.status || '')) {
          const message = status.status === 'failed'
            ? '\n✗ Operation failed during execution'
            : '\n✗ SafeRun approval rejected';
          console.log(chalk.red(message));
          return ApprovalOutcome.Cancelled;
        }

        if (status.expired) {
          console.log(chalk.red('\n✗ Approval expired'));
          return ApprovalOutcome.Cancelled;
        }

        // Fallback: if approved=true but no execution status yet, treat as approved
        if (status.approved && !status.pending) {
          console.log(chalk.green('\n✓ SafeRun approval granted!'));
          return ApprovalOutcome.Approved;
        }
      } catch (error) {
        // Continue polling on transient errors
        if (error instanceof Error && !error.message.includes('404')) {
          // Log but continue
        }
      }

      // Wait before next poll
      await new Promise(resolve => setTimeout(resolve, this.pollInterval));
    }

    // Timeout or cancelled
    if (!this.cancelPolling) {
      console.log(chalk.red('\n✗ Approval timed out'));
    }
    return ApprovalOutcome.Cancelled;
  }

  private showPreview(result: DryRunResult): void {
    const riskColor = getRiskColor(result.riskScore);
    console.log(chalk.bold('\n═══════════════════════════════════'));
    console.log(chalk.bold('  🛡️  SafeRun Protection Active'));
    console.log(chalk.bold('═══════════════════════════════════'));

    console.log(`\n${chalk.gray('Operation:')} ${result.humanPreview || 'Unknown operation'}`);
    // Risk score comes as 0-1 from API, convert to 0-10 for display
    const displayScore = (result.riskScore * 10).toFixed(1);
    console.log(`${chalk.gray('Risk Score:')} ${riskColor(`${displayScore}/10`)}`);

    if (result.reasons.length > 0) {
      console.log(`\n${chalk.gray('Reasons:')}`);
      for (const reason of result.reasons) {
        console.log(`  • ${reason}`);
      }
    }

    if (result.approvalUrl) {
      console.log(`\n${chalk.gray('🌐 Approve or reject:')}`);
      console.log(`   ${chalk.cyan(result.approvalUrl)}`);
    }
  }

  private async browserApproval(result: DryRunResult, url: string): Promise<ApprovalOutcome> {
    this.metrics?.track('approval_requested', { method: 'browser' }).catch(() => undefined);
    const opened = await this.openBrowser(url);
    if (!opened) {
      return ApprovalOutcome.Cancelled;
    }
    return this.waitForApproval(result);
  }

  private async openBrowser(url: string): Promise<boolean> {
    try {
      await open(url);
      return true;
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unknown error';
      console.error(chalk.red(`Failed to open browser: ${message}`));
      console.log(`Open manually: ${chalk.cyan(url)}`);
      return false;
    }
  }

  private async slackApproval(result: DryRunResult): Promise<ApprovalOutcome> {
    this.metrics?.track('approval_requested', { method: 'slack' }).catch(() => undefined);
    const slack = this.getSlackConfig();
    if (!slack) {
      console.log(chalk.yellow('Slack notifications are not configured. Falling back to waiting for approval.'));
      return this.waitForApproval(result);
    }

    const spinner = ora('Sending Slack notification...').start();
    try {
      await this.sendSlackNotification(slack.webhook_url as string, {
        approvalUrl: result.approvalUrl ?? 'https://app.saferun.dev',
        riskScore: result.riskScore,
        reasons: result.reasons,
        preview: result.humanPreview,
      });
      spinner.succeed('Slack notification sent.');
    } catch (error) {
      spinner.fail('Failed to send Slack notification.');
      const message = error instanceof Error ? error.message : 'Unknown error';
      console.log(chalk.red(message));
      return this.waitForApproval(result);
    }

    return this.waitForApproval(result);
  }

  // SECURITY: bypassCode() method removed - no bypass mechanism exists

  private async waitForApproval(result: DryRunResult): Promise<ApprovalOutcome> {
    const approvalUrl = result.approvalUrl ?? 'https://app.saferun.dev';

    // QR code already shown in showPreview()

    const startTime = Date.now();
    const maxAttempts = Math.ceil(this.timeout / this.pollInterval);
    let attempt = 0;

    const spinner = ora({
      text: this.getWaitingText(0, maxAttempts, 0, Math.floor(this.timeout / 1000)),
      spinner: 'dots',
    }).start();

    try {
      while (Date.now() - startTime < this.timeout) {
        attempt++;
        const elapsed = Math.floor((Date.now() - startTime) / 1000);
        const remaining = Math.max(0, Math.floor((this.timeout - (Date.now() - startTime)) / 1000));

        // Update spinner text with details
        spinner.text = this.getWaitingText(attempt, maxAttempts, elapsed, remaining);

        // Check approval status
        try {
          const status = await this.client.getApprovalStatus(result.changeId);

          // Check final success statuses first
          if (status.status === 'executed' || status.status === 'applied') {
            spinner.succeed(chalk.green('✓ Operation executed successfully'));
            this.metrics?.track('operation_executed', { change_id: result.changeId }).catch(() => undefined);
            return ApprovalOutcome.Approved;
          }

          if (status.status === 'reverted') {
            spinner.warn(chalk.yellow('↩ Operation was reverted'));
            return ApprovalOutcome.Approved;
          }

          // Check failure statuses
          if (status.rejected || ['failed', 'rejected', 'cancelled'].includes(status.status || '')) {
            const message = status.status === 'failed'
              ? '✗ Operation failed during execution'
              : '✗ SafeRun approval rejected';
            spinner.fail(chalk.red(message));
            return ApprovalOutcome.Cancelled;
          }

          if (status.expired) {
            spinner.fail(chalk.red('✗ Approval expired'));
            return ApprovalOutcome.Cancelled;
          }

          // Fallback: if approved=true but no execution status yet, treat as approved
          // (for backward compatibility with endpoints that don't set 'executed' status)
          if (status.approved && !status.pending) {
            spinner.succeed(chalk.green('✓ SafeRun approval granted'));
            return ApprovalOutcome.Approved;
          }

          // Still pending - continue polling
        } catch (error) {
          // Continue polling on transient errors
          if (error instanceof Error && !error.message.includes('404')) {
            throw error;
          }
        }

        // Wait before next poll
        await new Promise(resolve => setTimeout(resolve, this.pollInterval));
      }

      // Timeout reached
      spinner.fail(chalk.red('✗ Approval timed out'));
      console.error(chalk.red(`Approval timed out after ${Math.round(this.timeout / 1000)} seconds.`));
      return ApprovalOutcome.Cancelled;
    } catch (error) {
      spinner.fail(chalk.red('✗ Approval wait aborted'));
      if (error instanceof SafeRunApprovalTimeout) {
        console.error(chalk.red(`Approval timed out after ${Math.round(this.timeout / 1000)} seconds.`));
      } else if (error instanceof Error) {
        console.error(chalk.red(`Failed to confirm approval: ${error.message}`));
      }
      return ApprovalOutcome.Cancelled;
    }
  }

  private getWaitingText(attempt: number, maxAttempts: number, elapsed: number, remaining: number): string {
    const parts = [
      chalk.cyan('⏳ Waiting for approval...'),
      chalk.gray(`(${attempt}/${maxAttempts})`),
      chalk.yellow(`⏱  ${elapsed}s elapsed`),
      chalk.blue(`⏲  ${remaining}s remaining`),
      chalk.gray('(Ctrl+C to cancel)'),
    ];
    return parts.join(' ');
  }

  private prompt(question: string): Promise<string> {
    return new Promise((resolve) => {
      this.rl.question(question, (answer) => {
        resolve(answer);
      });
    });
  }

  private validateBypassCode(code: string): boolean {
    return /^[0-9]{6}$/.test(code);
  }

  private close(): void {
    this.rl.close();
  }

  private async sendSlackNotification(webhookUrl: string, payload: { approvalUrl: string; riskScore: number; reasons: string[]; preview?: string | null }): Promise<void> {
    await new Promise<void>((resolve, reject) => {
      try {
        const url = new URL(webhookUrl);
        const data = JSON.stringify({
          text: `🛡️ SafeRun approval required\nRisk: ${payload.riskScore}/10\nReasons: ${payload.reasons.join(', ') || 'n/a'}\nPreview: ${payload.preview ?? 'n/a'}\nApprove: ${payload.approvalUrl}`,
        });
        const options: https.RequestOptions = {
          hostname: url.hostname,
          port: url.port ? Number(url.port) : url.protocol === 'https:' ? 443 : 80,
          path: url.pathname + (url.search || ''),
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Content-Length': Buffer.byteLength(data),
          },
        };
        const req = https.request(options, (res) => {
          res.on('data', () => undefined);
          res.on('end', () => {
            if (res.statusCode && res.statusCode >= 200 && res.statusCode < 300) {
              resolve();
            } else {
              reject(new Error(`Slack webhook returned status ${res.statusCode}`));
            }
          });
        });
        req.on('error', reject);
        req.write(data);
        req.end();
      } catch (error) {
        reject(error instanceof Error ? error : new Error('Unknown Slack webhook error'));
      }
    });
  }

  private buildOptions(result: DryRunResult, approvalUrl: string): Array<{ key: string; label: string; action: () => Promise<ApprovalOutcome> }> {
    const options: Array<{ key: string; label: string; action: () => Promise<ApprovalOutcome> }> = [];

    options.push({ key: '1', label: chalk.green('Open browser for approval'), action: () => this.browserApproval(result, approvalUrl) });

    if (this.getSlackConfig()) {
      options.push({ key: '2', label: chalk.blue('Request approval via Slack'), action: () => this.slackApproval(result) });
    }

    // SECURITY: "Enter bypass code" option removed
    // "Continue waiting" removed - polling already runs in background

    options.push({ key: '5', label: chalk.red('Cancel operation'), action: async () => ApprovalOutcome.Cancelled });

    return options;
  }

  private printOptions(options: Array<{ key: string; label: string; action: () => Promise<ApprovalOutcome> }>): void {
    console.log('\n' + chalk.yellow('Options:'));
    for (const option of options) {
      console.log(`  ${option.key}. ${option.label}`);
    }
  }

  private getSlackConfig(): { enabled?: boolean; webhook_url?: string } | null {
    const notifications = this.config?.notifications;
    if (!notifications || typeof notifications !== 'object') {
      return null;
    }
    const slack = (notifications as Record<string, unknown>).slack as { enabled?: boolean; webhook_url?: string } | undefined;
    if (!slack || slack.enabled === false || !slack.webhook_url) {
      return null;
    }
    return slack;
  }

  // SECURITY: allowBypass() and validateBypassCode() methods removed
}

function getRiskColor(score: number): (message: string) => string {
  if (score >= 7) {
    return chalk.red;
  }
  if (score >= 4) {
    return chalk.yellow;
  }
  return chalk.green;
}
