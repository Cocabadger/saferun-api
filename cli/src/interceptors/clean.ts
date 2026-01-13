import chalk from 'chalk';
import { ApprovalFlow, ApprovalOutcome } from '../utils/approval-flow';
import { runGitCommand, getCurrentBranch, isProtectedBranch } from '../utils/git';
import { logOperation } from '../utils/logger';
import { ModeSettings, OperationRuleConfig } from '../utils/config';
import { InterceptorContext } from './types';

function isDangerousClean(args: string[]): boolean {
  let hasForce = false;
  let hasDirectories = false;

  for (const arg of args) {
    if (arg === '-f' || arg === '--force') {
      hasForce = true;
    }
    if (arg === '-d' || arg === '--dir' || arg === '--directories') {
      hasDirectories = true;
    }
  }

  return hasForce && hasDirectories;
}

export async function interceptClean(context: InterceptorContext): Promise<number> {
  if (!isDangerousClean(context.args)) {
    return runGitCommand(['clean', ...context.args], {
      cwd: context.gitInfo.repoRoot,
      disableAliases: ['clean'],
    });
  }

  // Filter by protected branches - only protect configured branches
  const protectedBranches = context.config.github.protected_branches ?? [];
  const currentBranch = await getCurrentBranch(context.gitInfo.repoRoot);
  const protectedBranch = currentBranch ? isProtectedBranch(currentBranch, protectedBranches) : false;

  // Allow clean -fd on non-protected branches without approval
  if (!protectedBranch) {
    console.log(chalk.yellow(`⚠️  Clean -fd detected on branch: ${currentBranch || 'HEAD'}`));
    console.log(chalk.gray(`   ℹ️  Branch '${currentBranch}' is not protected - proceeding without approval`));
    console.log(chalk.gray(`   (Configure protected branches with: saferun settings branches)\n`));
    
    return runGitCommand(['clean', ...context.args], {
      cwd: context.gitInfo.repoRoot,
      disableAliases: ['clean'],
    });
  }

  const repoSlug = context.config.github.repo === 'auto' ? context.gitInfo.repoSlug ?? 'local/repo' : context.config.github.repo;
  const rule = context.config.rules?.clean;
  const command = `git clean ${context.args.join(' ')}`.trim();
  const reasons = ['clean_force_directories'];

  let riskScore = rule?.risk_score != null ? rule.risk_score : 6.5;
  riskScore = clampRisk(riskScore);

  const humanPreview = 'Force cleaning untracked files and directories.';
  const enforcement = resolveEnforcement(context.modeSettings, rule?.action, 'warn');

  if (enforcement.action === 'allow' || enforcement.action === 'warn') {
    if (enforcement.action === 'warn' || context.modeSettings?.show_warnings) {
      console.warn(chalk.yellow('SafeRun warning: git clean -fd will run without approval.'));
    }
    context.metrics.track('operation_allowed', {
      hook: 'alias:clean',
      operation_type: 'clean',
      repo: repoSlug,
      reason: enforcement.action === 'warn' ? 'policy_warn' : 'policy_allow',
    }).catch(() => undefined);
    return runGitCommand(['clean', ...context.args], {
      cwd: context.gitInfo.repoRoot,
      disableAliases: ['clean'],
    });
  }

  const approvals: PendingApproval[] = [];

  try {
    const dryRun = await context.client.gitOperation({
      operationType: 'clean',
      target: `${repoSlug}@workspace`,
      command,
      metadata: {
        repo: repoSlug,
        args: context.args,
      },
      riskScore: riskScore / 10,
      humanPreview,
      requiresApproval: enforcement.requiresApproval || enforcement.shouldBlock,
      reasons,
    });

    if (!dryRun.needsApproval && !enforcement.shouldBlock) {
      context.metrics.track('operation_allowed', {
        hook: 'alias:clean',
        operation_type: 'clean',
        repo: repoSlug,
        reason: 'api_allows',
      }).catch(() => undefined);
      await logOperation(context.gitInfo.repoRoot, {
        event: 'clean',
        operation: 'clean',
        repo: repoSlug,
        outcome: 'api_allows',
        args: context.args,
      });
    } else if (!dryRun.needsApproval && enforcement.shouldBlock) {
      console.error(chalk.red('SafeRun policy blocks git clean -fd.'));
      context.metrics.track('operation_blocked', {
        hook: 'alias:clean',
        operation_type: 'clean',
        repo: repoSlug,
        reason: 'policy_block',
      }).catch(() => undefined);
      await logOperation(context.gitInfo.repoRoot, {
        event: 'clean',
        operation: 'clean',
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
          hook: 'alias:clean',
          operation_type: 'clean',
          repo: repoSlug,
          reason: 'user_cancelled',
        }).catch(() => undefined);
        await logOperation(context.gitInfo.repoRoot, {
          event: 'clean',
          operation: 'clean',
          repo: repoSlug,
          outcome: 'cancelled',
        });
        console.error(chalk.red('SafeRun blocked git clean -fd.'));
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
    // SECURITY: Block operation when API unavailable (fail-secure)
    console.error(chalk.red('🚫 Operation blocked - SafeRun API unreachable'));
    console.error(chalk.yellow('   Cannot verify safety without API connection.'));
    context.metrics.track('operation_blocked', {
      hook: 'alias:clean',
      operation_type: 'clean',
      repo: repoSlug,
      reason: 'api_unreachable',
    }).catch(() => undefined);
    await logOperation(context.gitInfo.repoRoot, {
      event: 'clean',
      operation: 'clean',
      repo: repoSlug,
      outcome: 'blocked_api_error',
      error: message,
    });
    return 1;
  }

  const exitCode = await runGitCommand(['clean', ...context.args], {
    cwd: context.gitInfo.repoRoot,
    disableAliases: ['clean'],
    env: approvals.length > 0 ? { SAFERUN_APPROVED_CHANGE_ID: approvals[0].changeId } : undefined,
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
      hook: 'alias:clean',
      operation_type: 'clean',
      repo: repoSlug,
      reason: 'executed',
    }).catch(() => undefined);
    await logOperation(context.gitInfo.repoRoot, {
      event: 'clean',
      operation: 'clean',
      repo: repoSlug,
      outcome: 'executed',
    });
  } else {
    context.metrics.track('operation_blocked', {
      hook: 'alias:clean',
      operation_type: 'clean',
      repo: repoSlug,
      reason: 'git_failed',
    }).catch(() => undefined);
    await logOperation(context.gitInfo.repoRoot, {
      event: 'clean',
      operation: 'clean',
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
