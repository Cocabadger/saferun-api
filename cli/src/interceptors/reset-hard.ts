import chalk from 'chalk';
import { ApprovalFlow, ApprovalOutcome } from '../utils/approval-flow';
import { getAheadBehind, resolveCommit, runGitCommand } from '../utils/git';
import { logOperation } from '../utils/logger';
import { ModeSettings, OperationRuleConfig } from '../utils/config';
import { InterceptorContext } from './types';

interface ResetParams {
  mode: 'hard' | 'mixed' | 'soft' | 'unknown';
  target?: string;
}

function parseResetArgs(args: string[]): ResetParams {
  let mode: ResetParams['mode'] = 'mixed';
  let target: string | undefined;

  for (const arg of args) {
    if (arg === '--hard') {
      mode = 'hard';
    } else if (arg === '--soft') {
      mode = 'soft';
    } else if (arg === '--mixed') {
      mode = 'mixed';
    }
  }

  const nonFlags = args.filter((arg) => !arg.startsWith('-'));
  if (nonFlags.length > 0) {
    target = nonFlags[nonFlags.length - 1];
  }

  return { mode, target };
}

export async function interceptReset(context: InterceptorContext): Promise<number> {
  const params = parseResetArgs(context.args);
  if (params.mode !== 'hard') {
    return runGitCommand(['reset', ...context.args], {
      cwd: context.gitInfo.repoRoot,
      disableAliases: ['reset'],
    });
  }

  const repoSlug = context.config.github.repo === 'auto' ? context.gitInfo.repoSlug ?? 'local/repo' : context.config.github.repo;
  const rule = context.config.rules?.reset_hard;

  const targetRef = params.target ?? 'HEAD';
  const targetSha = await resolveCommit(targetRef, context.gitInfo.repoRoot);
  const currentSha = await resolveCommit('HEAD', context.gitInfo.repoRoot);

  let commitsBack = 0;
  if (targetSha && currentSha && targetSha !== currentSha) {
    const { behind } = await getAheadBehind('HEAD', targetRef, context.gitInfo.repoRoot);
    commitsBack = behind;
  }

  const reasons = ['reset_hard'];
  if (commitsBack > 0) {
    reasons.push(`commits_discarded:${commitsBack}`);
  }

  if (rule?.max_commits_back && commitsBack > rule.max_commits_back) {
    reasons.push(`commits_over_limit:${rule.max_commits_back}`);
  }

  let riskScore = 7 + Math.min(commitsBack * 0.6, 3);
  if (rule?.risk_score != null) {
    riskScore = rule.risk_score;
  }
  riskScore = clampRisk(riskScore);

  const humanPreview = commitsBack > 0
    ? `Reset --hard will discard approximately ${commitsBack} commits.`
    : 'Reset --hard will overwrite working tree and index.';

  const actionOverride = rule?.max_commits_back && commitsBack > rule.max_commits_back ? 'require_approval' : rule?.action;
  
  // DEBUG: временный лог для диагностики
  
  const enforcement = resolveEnforcement(context.modeSettings, actionOverride, 'warn');
  

  if (enforcement.action === 'allow' || enforcement.action === 'warn') {
    if (enforcement.action === 'warn' || context.modeSettings?.show_warnings) {
      console.warn(chalk.yellow('SafeRun warning: git reset --hard will run without approval.'));
    }
    context.metrics.track('operation_allowed', {
      hook: 'alias:reset',
      operation_type: 'reset_hard',
      repo: repoSlug,
      target: targetRef,
      reason: enforcement.action === 'warn' ? 'policy_warn' : 'policy_allow',
    }).catch(() => undefined);
    return runGitCommand(['reset', ...context.args], {
      cwd: context.gitInfo.repoRoot,
      disableAliases: ['reset'],
    });
  }

  const approvals: PendingApproval[] = [];

  try {
    const dryRun = await context.client.gitOperation({
      operationType: 'reset_hard',
      target: `${repoSlug}@${targetRef}`,
      command: `git reset --hard ${targetRef}`,
      metadata: {
        repo: repoSlug,
        target: targetRef,
        commitsDiscarded: commitsBack,
      },
      riskScore: riskScore / 10,
      humanPreview,
      requiresApproval: enforcement.requiresApproval || enforcement.shouldBlock,
      reasons,
    });

    if (!dryRun.needsApproval && !enforcement.shouldBlock) {
      context.metrics.track('operation_allowed', {
        hook: 'alias:reset',
        operation_type: 'reset_hard',
        repo: repoSlug,
        target: targetRef,
        reason: 'api_allows',
      }).catch(() => undefined);
      await logOperation(context.gitInfo.repoRoot, {
        event: 'reset_hard',
        operation: 'reset_hard',
        repo: repoSlug,
        target: targetRef,
        outcome: 'api_allows',
      });
    } else if (!dryRun.needsApproval && enforcement.shouldBlock) {
      console.error(chalk.red('SafeRun policy blocks git reset --hard.'));
      context.metrics.track('operation_blocked', {
        hook: 'alias:reset',
        operation_type: 'reset_hard',
        repo: repoSlug,
        target: targetRef,
        reason: 'policy_block',
      }).catch(() => undefined);
      await logOperation(context.gitInfo.repoRoot, {
        event: 'reset_hard',
        operation: 'reset_hard',
        repo: repoSlug,
        target: targetRef,
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
          metadata: { repo: repoSlug, target: targetRef },
        });
        await logOperation(context.gitInfo.repoRoot, {
          event: 'reset_hard',
          operation: 'reset_hard',
          repo: repoSlug,
          target: targetRef,
          outcome: 'cancelled',
        });
        console.error(chalk.red('SafeRun blocked git reset --hard.'));
        return 1;
      }

      approvals.push({
        changeId: dryRun.changeId,
        metadata: { repo: repoSlug, target: targetRef },
      });
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    console.error(chalk.red(`SafeRun error: ${message}`));
    // SECURITY: Block operation when API unavailable (fail-secure)
    console.error(chalk.red('🚫 Operation blocked - SafeRun API unreachable'));
    console.error(chalk.yellow('   Cannot verify safety without API connection.'));
    context.metrics.track('operation_blocked', {
      hook: 'alias:reset',
      operation_type: 'reset_hard',
      repo: repoSlug,
      target: targetRef,
      reason: 'api_unreachable',
    }).catch(() => undefined);
    await logOperation(context.gitInfo.repoRoot, {
      event: 'reset_hard',
      operation: 'reset_hard',
      repo: repoSlug,
      target: targetRef,
      outcome: 'blocked_api_error',
      error: message,
    });
    return 1;
  }

  const exitCode = await runGitCommand(['reset', ...context.args], {
    cwd: context.gitInfo.repoRoot,
    disableAliases: ['reset'],
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
      hook: 'alias:reset',
      operation_type: 'reset_hard',
      repo: repoSlug,
      target: targetRef,
      reason: 'executed',
    }).catch(() => undefined);
    await logOperation(context.gitInfo.repoRoot, {
      event: 'reset_hard',
      operation: 'reset_hard',
      repo: repoSlug,
      target: targetRef,
      outcome: 'executed',
    });
  } else {
    context.metrics.track('operation_blocked', {
      hook: 'alias:reset',
      operation_type: 'reset_hard',
      repo: repoSlug,
      target: targetRef,
      reason: 'git_failed',
    }).catch(() => undefined);
    await logOperation(context.gitInfo.repoRoot, {
      event: 'reset_hard',
      operation: 'reset_hard',
      repo: repoSlug,
      target: targetRef,
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
