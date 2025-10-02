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
  Bypassed = 'bypassed',
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
    this.timeout = options.timeoutMs ?? 5 * 60_000;
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

    // Interactive mode - show options menu
    const options = this.buildOptions(result, approvalUrl);
    this.printOptions(options);

    try {
      while (true) {
        const choice = (await this.prompt('\nSelect option: ')).trim();
        const option = options.find((entry) => entry.key === choice);
        if (!option) {
          console.log(chalk.red('Invalid selection. Please choose one of the available options.'));
          continue;
        }

        const outcome = await option.action();
        if (outcome === ApprovalOutcome.Bypassed) {
          this.metrics?.track('bypass_used', { change_id: result.changeId }).catch(() => undefined);
        }
        return outcome;
      }
    } finally {
      this.close();
    }
  }

  private showPreview(result: DryRunResult): void {
    const riskColor = getRiskColor(result.riskScore);
    console.log(chalk.bold('\n═══════════════════════════════════'));
    console.log(chalk.bold('  🛡️  SafeRun Protection Active'));
    console.log(chalk.bold('═══════════════════════════════════'));

    console.log(`\n${chalk.gray('Operation:')} ${result.humanPreview || 'Unknown operation'}`);
    // Risk score is already 0-10 scale from API
    const displayScore = result.riskScore.toFixed(1);
    console.log(`${chalk.gray('Risk Score:')} ${riskColor(`${displayScore}/10`)}`);

    if (result.reasons.length > 0) {
      console.log(`\n${chalk.gray('Reasons:')}`);
      for (const reason of result.reasons) {
        console.log(`  • ${reason}`);
      }
    }

    if (result.approvalUrl) {
      console.log(`\n${chalk.gray('Approval URL:')} ${chalk.cyan(result.approvalUrl)}`);
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

  private async bypassCode(result: DryRunResult): Promise<ApprovalOutcome> {
    this.metrics?.track('approval_requested', { method: 'bypass_code' }).catch(() => undefined);
    if (!this.allowBypass()) {
      console.log(chalk.red('Bypass codes are disabled in the current SafeRun mode.'));
      return ApprovalOutcome.Cancelled;
    }
    console.log(chalk.yellow('\nEnter a 6-digit bypass code (or leave blank to cancel).'));
    const code = await this.prompt('Bypass code: ');
    if (!code.trim()) {
      return ApprovalOutcome.Cancelled;
    }
    if (!this.validateBypassCode(code.trim())) {
      console.log(chalk.red('Invalid bypass code.'));
      return ApprovalOutcome.Cancelled;
    }
    console.log(chalk.green('Bypass code accepted.'));
    return ApprovalOutcome.Bypassed;
  }

  private async waitForApproval(result: DryRunResult): Promise<ApprovalOutcome> {
    const spinner = ora('Waiting for approval... (Ctrl+C to cancel)').start();
    try {
      const approval = await this.client.waitForApproval(result.changeId, {
        pollInterval: this.pollInterval,
        timeout: this.timeout,
        autoApply: false,
      });
      spinner.succeed('SafeRun approval granted');
      this.metrics?.track('approval_granted', { change_id: result.changeId }).catch(() => undefined);
      return approval.approved ? ApprovalOutcome.Approved : ApprovalOutcome.Cancelled;
    } catch (error) {
      spinner.fail('Approval wait aborted');
      if (error instanceof SafeRunApprovalTimeout) {
        console.error(chalk.red(`Approval timed out after ${Math.round(this.timeout / 1000)} seconds.`));
      } else if (error instanceof Error) {
        console.error(chalk.red(`Failed to confirm approval: ${error.message}`));
      }
      return ApprovalOutcome.Cancelled;
    }
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

    if (this.allowBypass()) {
      options.push({ key: '3', label: chalk.cyan('Enter bypass code'), action: () => this.bypassCode(result) });
    }

    options.push({ key: '4', label: chalk.gray('Wait for auto-approval'), action: () => this.waitForApproval(result) });
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

  private allowBypass(): boolean {
    if (this.modeSettings?.allow_bypass === false) {
      return false;
    }
    const bypass = this.config?.bypass;
    if (!bypass) {
      return true;
    }
    if (bypass.temporary_tokens?.enabled === false) {
      return false;
    }
    return true;
  }
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
