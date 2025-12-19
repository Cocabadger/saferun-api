import chalk from 'chalk';
import { DryRunResult } from '@saferun/sdk';
import { ApprovalFlow, ApprovalOutcome } from '../utils/approval-flow';
import { runGitCommand } from '../utils/git';
import { logOperation } from '../utils/logger';
import { withSystemMetadata } from '../utils/system-info';
import { InterceptorContext } from './types';

interface ForcePushParams {
  remote: string;
  branch: string;
  isForce: boolean;
}

function parsePushArgs(args: string[]): ForcePushParams | null {
  let remote = 'origin';
  let branch = '';
  let isForce = false;

  // Check for --force or -f flag
  for (const arg of args) {
    if (arg === '--force' || arg === '-f' || arg === '--force-with-lease') {
      isForce = true;
    }
  }

  // If not force push, skip interception
  if (!isForce) {
    return null;
  }

  // Parse remote and branch
  const nonFlags = args.filter((arg) => !arg.startsWith('-'));
  if (nonFlags.length > 0) {
    remote = nonFlags[0];
  }
  if (nonFlags.length > 1) {
    branch = nonFlags[1];
  }

  // If no branch specified, get current branch
  if (!branch) {
    try {
      const { execSync } = require('child_process');
      branch = execSync('git rev-parse --abbrev-ref HEAD', { encoding: 'utf-8' }).trim();
    } catch {
      branch = 'HEAD';
    }
  }

  return { remote, branch, isForce };
}

export async function interceptForcePush(context: InterceptorContext): Promise<number> {
  const params = parsePushArgs(context.args);

  // If not force push, run normally
  if (!params || !params.isForce) {
    return runGitCommand(['push', ...context.args], {
      cwd: context.gitInfo.repoRoot,
      disableAliases: ['push'],
    });
  }

  const repoSlug = context.config.github.repo === 'auto' ? context.gitInfo.repoSlug ?? 'local/repo' : context.config.github.repo;
  const githubToken = process.env.GITHUB_TOKEN || process.env.GH_TOKEN;

  if (!githubToken) {
    console.error(chalk.red('GitHub token not found. Set GITHUB_TOKEN or GH_TOKEN environment variable.'));
    return 1;
  }

  console.log(chalk.yellow(`⚠️  Force push detected: ${params.remote}/${params.branch}`));
  console.log(chalk.yellow('   This is a DANGEROUS operation - it rewrites history!'));

  try {
    // Get current commit SHA
    let commitSha: string;
    try {
      const { execSync } = require('child_process');
      commitSha = execSync('git rev-parse HEAD', { encoding: 'utf-8' }).trim();
    } catch {
      commitSha = 'unknown';
    }

    // Call SafeRun API to check if force push needs approval
    const dryRun: DryRunResult = await (context.client as any).forcePushGithub({
      repo: repoSlug,
      branch: params.branch,
      githubToken,
      reason: `Force push to ${params.branch} (rewrites history)`,
      webhookUrl: context.config.notifications?.webhook_url as string | undefined,
      metadata: withSystemMetadata({
        source: 'cli',
        commit_sha: commitSha,
      }),
    });

    // Track the operation
    context.metrics.track('force_push_check', {
      hook: 'alias:push',
      operation_type: 'force_push',
      repo: repoSlug,
      branch: params.branch,
      needs_approval: dryRun.needsApproval,
      change_id: dryRun.changeId,
      commit_sha: commitSha,
    }).catch(() => undefined);

    // Force push ALWAYS requires approval (IRREVERSIBLE)
    if (!dryRun.needsApproval) {
      console.log(chalk.red('⚠️  CRITICAL: Force push should ALWAYS require approval!'));
      console.log(chalk.red('   This is a bug - contact SafeRun support.'));
      return 1;
    }

    // Request approval through SafeRun flow
    const flow = new ApprovalFlow({
      client: context.client,
      metrics: context.metrics,
      config: context.config,
      modeSettings: context.modeSettings,
    });

    const outcome = await flow.requestApproval(dryRun);

    if (outcome !== ApprovalOutcome.Approved) {
      console.error(chalk.red(`✗ SafeRun blocked force push to '${params.branch}' (${outcome})`));

      await logOperation(context.gitInfo.repoRoot, {
        event: 'force_push',
        operation: 'force_push',
        repo: repoSlug,
        branch: params.branch,
        outcome: 'cancelled',
        change_id: dryRun.changeId,
      });

      context.metrics.track('operation_blocked', {
        hook: 'alias:push',
        operation_type: 'force_push',
        repo: repoSlug,
        branch: params.branch,
        outcome,
      }).catch(() => undefined);

      return 1;
    }

    // Approved - execute force push
    console.log(chalk.green(`✓ Force push approved - executing...`));

    await logOperation(context.gitInfo.repoRoot, {
      event: 'force_push',
      operation: 'force_push',
      repo: repoSlug,
      branch: params.branch,
      outcome: 'approved',
      change_id: dryRun.changeId,
    });

    context.metrics.track('operation_approved', {
      hook: 'alias:push',
      operation_type: 'force_push',
      repo: repoSlug,
      branch: params.branch,
    }).catch(() => undefined);

    // Execute the force push
    // 3. Execute push command
      const exitCode = await runGitCommand(['push', ...context.args], {
        cwd: context.gitInfo.repoRoot,
        disableAliases: ['push'],
      });

      if (exitCode === 0) {
      console.log(chalk.green(`✓ Force pushed to ${params.remote}/${params.branch}`));
      console.log(chalk.yellow(`⚠️  History has been rewritten - other users will need to force pull!`));

      // Confirm execution to SafeRun
      try {
        // Record execution
        await context.client.applyChange(dryRun.changeId, true);
      } catch (err) {
        console.warn(chalk.yellow('Warning: Failed to confirm execution to SafeRun'));
      }
    }

    return exitCode;

  } catch (error: any) {
    console.error(chalk.red(`✗ SafeRun force push check failed: ${error.message}`));

    context.metrics.track('operation_error', {
      hook: 'alias:push',
      operation_type: 'force_push',
      repo: repoSlug,
      branch: params.branch,
      error: error.message,
    }).catch(() => undefined);

    // SECURITY: Block operation when API unavailable (fail-secure)
    // AI agents could disable network to bypass protection
    console.error(chalk.red('🚫 Operation blocked - SafeRun API unreachable'));
    console.error(chalk.yellow('   Cannot verify safety without API connection.'));
    console.error(chalk.yellow('   Please check your network and try again.'));
    return 1;
  }
}
