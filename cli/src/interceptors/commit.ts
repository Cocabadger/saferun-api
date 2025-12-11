import chalk from 'chalk';
import { ApprovalFlow, ApprovalOutcome } from '../utils/approval-flow';
import { runGitCommand } from '../utils/git';
import { logOperation } from '../utils/logger';
import { ModeSettings, OperationRuleConfig } from '../utils/config';
import { InterceptorContext } from './types';

function hasNoVerify(args: string[]): boolean {
  for (const arg of args) {
    if (arg === '--no-verify' || arg === '-n') {
      return true;
    }
  }
  return false;
}

export async function interceptCommit(context: InterceptorContext): Promise<number> {
  // If not using --no-verify, just run the command normally
  if (!hasNoVerify(context.args)) {
    return runGitCommand(['commit', ...context.args], {
      cwd: context.gitInfo.repoRoot,
      disableAliases: ['commit'],
    });
  }

  const repoSlug = context.config.github.repo === 'auto' ? context.gitInfo.repoSlug ?? 'local/repo' : context.config.github.repo;
  const rule = context.config.rules?.commit;
  const command = `git commit ${context.args.join(' ')}`.trim();
  const reasons = ['commit_no_verify'];

  let riskScore = rule?.risk_score != null ? rule.risk_score : 7.0;
  riskScore = clampRisk(riskScore);

  const humanPreview = 'Committing with --no-verify bypasses pre-commit and commit-msg hooks.';
  // SECURITY: Default to 'block' for --no-verify as it bypasses security hooks
  const enforcement = resolveEnforcement(context.modeSettings, rule?.action, 'block');

  // Log the attempt
  console.log(chalk.yellow('\n⚠️  SafeRun detected: git commit --no-verify'));
  console.log(chalk.gray('   This bypasses pre-commit hooks including security checks.\n'));

  if (enforcement.action === 'allow' || enforcement.action === 'warn') {
    if (enforcement.action === 'warn' || context.modeSettings?.show_warnings) {
      console.warn(chalk.yellow('SafeRun warning: commit --no-verify will proceed without approval.'));
    }
    context.metrics.track('operation_allowed', {
      hook: 'alias:commit',
      operation_type: 'commit_no_verify',
      repo: repoSlug,
      reason: enforcement.action === 'warn' ? 'policy_warn' : 'policy_allow',
    }).catch(() => undefined);
    return runGitCommand(['commit', ...context.args], {
      cwd: context.gitInfo.repoRoot,
      disableAliases: ['commit'],
    });
  }

  const approvals: PendingApproval[] = [];

  try {
    const dryRun = await context.client.gitOperation({
      operationType: 'custom',  // API doesn't have commit_no_verify yet
      target: `${repoSlug}@workspace`,
      command,
      metadata: {
        repo: repoSlug,
        args: context.args,
        bypassed_hooks: ['pre-commit', 'commit-msg'],
        custom_type: 'commit_no_verify',
      },
      riskScore: riskScore / 10,
      humanPreview,
      requiresApproval: enforcement.requiresApproval || enforcement.shouldBlock,
      reasons,
    });

    if (!dryRun.needsApproval && !enforcement.shouldBlock) {
      context.metrics.track('operation_allowed', {
        hook: 'alias:commit',
        operation_type: 'commit_no_verify',
        repo: repoSlug,
        reason: 'api_allows',
      }).catch(() => undefined);
      await logOperation(context.gitInfo.repoRoot, {
        event: 'commit_no_verify',
        operation: 'commit',
        repo: repoSlug,
        outcome: 'api_allows',
        args: context.args,
      });
    } else if (!dryRun.needsApproval && enforcement.shouldBlock) {
      console.error(chalk.red('SafeRun policy blocks commit --no-verify.'));
      context.metrics.track('operation_blocked', {
        hook: 'alias:commit',
        operation_type: 'commit_no_verify',
        repo: repoSlug,
        reason: 'policy_block',
      }).catch(() => undefined);
      await logOperation(context.gitInfo.repoRoot, {
        event: 'commit_no_verify',
        operation: 'commit',
        repo: repoSlug,
        outcome: 'blocked',
        reason: 'policy_block',
      });
      return 1;
    } else {
      const flow = new ApprovalFlow({
        client: context.client,
        metrics: context.metrics,
        config: context.config,
        modeSettings: context.modeSettings,
      });
      const outcome = await flow.requestApproval(dryRun);
      if (outcome !== ApprovalOutcome.Approved) {
        await context.client.confirmGitOperation({
          changeId: dryRun.changeId,
          status: 'cancelled',
          metadata: { repo: repoSlug },
        });
        context.metrics.track('operation_blocked', {
          hook: 'alias:commit',
          operation_type: 'commit_no_verify',
          repo: repoSlug,
          reason: 'user_cancelled',
        }).catch(() => undefined);
        await logOperation(context.gitInfo.repoRoot, {
          event: 'commit_no_verify',
          operation: 'commit',
          repo: repoSlug,
          outcome: 'cancelled',
        });
        console.error(chalk.red('SafeRun blocked commit --no-verify.'));
        return 1;
      }
      approvals.push({
        changeId: dryRun.changeId,
        metadata: { repo: repoSlug },
      });
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    console.error(chalk.red(`SafeRun error: ${message}`));
    
    // SECURITY: Always block when API unavailable (fail-secure)
    // AI agents could disable network to bypass protection
    console.error(chalk.red('🚫 Operation blocked - SafeRun API unreachable'));
    console.error(chalk.yellow('   Cannot verify safety without API connection.'));
    context.metrics.track('operation_blocked', {
      hook: 'alias:commit',
      operation_type: 'commit_no_verify',
      repo: repoSlug,
      reason: 'api_unreachable',
    }).catch(() => undefined);
    await logOperation(context.gitInfo.repoRoot, {
      event: 'commit_no_verify',
      operation: 'commit',
      repo: repoSlug,
      outcome: 'blocked_api_error',
      error: message,
    });
    return 1;
  }

  const exitCode = await runGitCommand(['commit', ...context.args], {
    cwd: context.gitInfo.repoRoot,
    disableAliases: ['commit'],
  });

  for (const approval of approvals) {
    await context.client.confirmGitOperation({
      changeId: approval.changeId,
      status: exitCode === 0 ? 'applied' : 'failed',
      metadata: exitCode === 0 ? approval.metadata : { ...approval.metadata, exitCode },
    });
  }

  if (exitCode === 0) {
    context.metrics.track('operation_allowed', {
      hook: 'alias:commit',
      operation_type: 'commit_no_verify',
      repo: repoSlug,
      reason: 'executed',
    }).catch(() => undefined);
    await logOperation(context.gitInfo.repoRoot, {
      event: 'commit_no_verify',
      operation: 'commit',
      repo: repoSlug,
      outcome: 'executed',
    });
  } else {
    context.metrics.track('operation_blocked', {
      hook: 'alias:commit',
      operation_type: 'commit_no_verify',
      repo: repoSlug,
      reason: 'git_failed',
    }).catch(() => undefined);
    await logOperation(context.gitInfo.repoRoot, {
      event: 'commit_no_verify',
      operation: 'commit',
      repo: repoSlug,
      outcome: 'failed',
      exitCode,
    });
  }

  return exitCode;
}

interface PendingApproval {
  changeId: string;
  metadata: Record<string, unknown>;
}

type EnforcementAction = 'allow' | 'warn' | 'require_approval' | 'block';

interface EnforcementDecision {
  action: EnforcementAction;
  requiresApproval: boolean;
  shouldBlock: boolean;
}

function resolveEnforcement(
  modeSettings: ModeSettings | undefined,
  ruleAction: OperationRuleConfig['action'] | undefined,
  defaultAction: EnforcementAction,
): EnforcementDecision {
  if (modeSettings?.block_operations === false) {
    const warn = modeSettings?.show_warnings === true;
    return {
      action: warn ? 'warn' : 'allow',
      requiresApproval: false,
      shouldBlock: false,
    };
  }

  let action = ruleAction ?? defaultAction;
  if (action === 'warn' && modeSettings?.show_warnings === false) {
    action = 'allow';
  }
  if (action === 'require_approval' && modeSettings?.require_approval === false) {
    action = modeSettings?.show_warnings ? 'warn' : 'allow';
  }

  switch (action) {
    case 'allow':
      return { action: 'allow', requiresApproval: false, shouldBlock: false };
    case 'warn':
      return { action: 'warn', requiresApproval: false, shouldBlock: false };
    case 'block':
      return { action: 'block', requiresApproval: true, shouldBlock: true };
    case 'require_approval':
    default:
      return { action: 'require_approval', requiresApproval: true, shouldBlock: false };
  }
}

function clampRisk(score: number): number {
  if (Number.isNaN(score)) {
    return 0;
  }
  return Math.min(10, Math.max(0, score));
}

