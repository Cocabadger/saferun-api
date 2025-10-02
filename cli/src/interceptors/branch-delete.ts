import chalk from 'chalk';
import { DryRunResult } from '@saferun/sdk';
import { ApprovalFlow, ApprovalOutcome } from '../utils/approval-flow';
import { getAheadBehind, isProtectedBranch, matchesBranchPattern, runGitCommand } from '../utils/git';
import { logOperation } from '../utils/logger';
import { ModeSettings, OperationRuleConfig } from '../utils/config';
import { InterceptorContext } from './types';

interface BranchDeleteTargets {
  branches: string[];
  force: boolean;
}

function parseBranchArgs(args: string[]): BranchDeleteTargets {
  const branches: string[] = [];
  let force = false;

  for (let i = 0; i < args.length; i += 1) {
    const arg = args[i];
    if (arg === '-D') {
      force = true;
      if (args[i + 1] && !args[i + 1].startsWith('-')) {
        branches.push(args[i + 1]);
        i += 1;
      }
    } else if (arg === '--delete' || arg === '-d') {
      if (args[i + 1] && !args[i + 1].startsWith('-')) {
        branches.push(args[i + 1]);
        i += 1;
      }
    }
  }

  return { branches, force };
}

export async function interceptBranchDelete(context: InterceptorContext): Promise<number> {
  const { branches, force } = parseBranchArgs(context.args);
  if (branches.length === 0) {
    return runGitCommand(['branch', ...context.args], {
      cwd: context.gitInfo.repoRoot,
      disableAliases: ['branch'],
    });
  }

  const repoSlug = context.config.github.repo === 'auto' ? context.gitInfo.repoSlug ?? 'local/repo' : context.config.github.repo;
  const defaultBranch = context.gitInfo.defaultBranch ?? 'main';
  const rule = context.config.rules?.branch_delete;
  const branchRules = context.config.github.branch_rules ?? [];

  const approvals: PendingApproval[] = [];

  for (const branchName of branches) {
    const protectedBranch = isProtectedBranch(branchName, context.config.github.protected_branches ?? []);
    const branchRule = branchRules.find((entry) => matchesBranchPattern(branchName, entry.pattern));

    if (branchRule?.skip_checks) {
      context.metrics.track('operation_allowed', {
        hook: 'alias:branch',
        operation_type: 'branch_delete',
        repo: repoSlug,
        branch: branchName,
        reason: 'branch_rule_skip_checks',
      }).catch(() => undefined);
      await logOperation(context.gitInfo.repoRoot, {
        event: 'branch_delete',
        operation: 'branch_delete',
        repo: repoSlug,
        branch: branchName,
        outcome: 'skip_checks',
      });
      continue;
    }

    const { ahead } = await getAheadBehind(branchName, defaultBranch, context.gitInfo.repoRoot);

    const reasons: string[] = [];
    if (protectedBranch) reasons.push('protected_branch');
    if (force) reasons.push('force_delete');
    if (ahead > 0) reasons.push(`unmerged_commits:${ahead}`);
    if (branchRule?.risk_level) reasons.push(`branch_rule_risk:${branchRule.risk_level}`);

    const humanPreview = protectedBranch
      ? `Delete protected branch ${branchName}${ahead > 0 ? ` with ${ahead} unmerged commits` : ''}`
      : `Delete branch ${branchName}${ahead > 0 ? ` with ${ahead} unmerged commits` : ''}`;

    let riskScore = protectedBranch ? 9 : force ? 7.5 : 6;
    riskScore += Math.min(ahead * 0.4, 2);
    if (branchRule?.risk_level === 'low') riskScore = Math.min(riskScore, 5);
    if (branchRule?.risk_level === 'high') riskScore = Math.max(riskScore, 8.5);
    if (rule?.risk_score != null) riskScore = rule.risk_score;
    riskScore = clampRisk(riskScore);

    const excludedByRule = rule?.exclude_patterns?.some((pattern) => matchesBranchPattern(branchName, pattern));
    if (excludedByRule) {
      context.metrics.track('operation_allowed', {
        hook: 'alias:branch',
        operation_type: 'branch_delete',
        repo: repoSlug,
        branch: branchName,
        reason: 'rule_excluded',
      }).catch(() => undefined);
      await logOperation(context.gitInfo.repoRoot, {
        event: 'branch_delete',
        operation: 'branch_delete',
        repo: repoSlug,
        branch: branchName,
        outcome: 'rule_excluded',
      });
      continue;
    }

    const enforcement = resolveEnforcement(context.modeSettings, rule?.action, 'require_approval');

    if (enforcement.action === 'allow' || enforcement.action === 'warn') {
      if (enforcement.action === 'warn' || context.modeSettings?.show_warnings) {
        console.warn(chalk.yellow(`SafeRun warning: deleting branch '${branchName}'.`));
      }
      context.metrics.track('operation_allowed', {
        hook: 'alias:branch',
        operation_type: 'branch_delete',
        repo: repoSlug,
        branch: branchName,
        reason: enforcement.action === 'warn' ? 'policy_warn' : 'policy_allow',
      }).catch(() => undefined);
      await logOperation(context.gitInfo.repoRoot, {
        event: 'branch_delete',
        operation: 'branch_delete',
        repo: repoSlug,
        branch: branchName,
        outcome: enforcement.action === 'warn' ? 'policy_warn' : 'policy_allow',
      });
      continue;
    }

    const requiresApproval = enforcement.requiresApproval || enforcement.shouldBlock;
    const command = `git branch ${force ? '-D' : '-d'} ${branchName}`;

    try {
      const dryRun = await context.client.gitOperation({
        operationType: 'branch_delete',
        target: `${repoSlug}#${branchName}`,
        command,
        metadata: {
          repo: repoSlug,
          branch: branchName,
          protectedBranch,
          force,
          unmergedCommits: ahead,
        },
        riskScore: riskScore / 10,
        humanPreview,
        requiresApproval,
        reasons,
      });

      if (!dryRun.needsApproval && !enforcement.shouldBlock) {
        context.metrics.track('operation_allowed', {
          hook: 'alias:branch',
          operation_type: 'branch_delete',
          repo: repoSlug,
          branch: branchName,
          reason: 'api_allows',
        }).catch(() => undefined);
        await logOperation(context.gitInfo.repoRoot, {
          event: 'branch_delete',
          operation: 'branch_delete',
          repo: repoSlug,
          branch: branchName,
          outcome: 'api_allows',
        });
        continue;
      }

      if (!dryRun.needsApproval && enforcement.shouldBlock) {
        console.error(chalk.red(`SafeRun policy blocks deletion of '${branchName}'.`));
        context.metrics.track('operation_blocked', {
          hook: 'alias:branch',
          operation_type: 'branch_delete',
          repo: repoSlug,
          branch: branchName,
          reason: 'policy_block',
        }).catch(() => undefined);
        await logOperation(context.gitInfo.repoRoot, {
          event: 'branch_delete',
          operation: 'branch_delete',
          repo: repoSlug,
          branch: branchName,
          outcome: 'blocked',
          reason: 'policy_block',
        });
        return 1;
      }

      const flow = new ApprovalFlow({
        client: context.client,
        metrics: context.metrics,
        config: context.config,
        modeSettings: context.modeSettings,
      });
      const outcome = await flow.requestApproval(dryRun);
      if (outcome !== ApprovalOutcome.Approved && outcome !== ApprovalOutcome.Bypassed) {
        await context.client.confirmGitOperation({
          changeId: dryRun.changeId,
          status: 'cancelled',
          metadata: { branch: branchName, repo: repoSlug },
        });
        await logOperation(context.gitInfo.repoRoot, {
          event: 'branch_delete',
          operation: 'branch_delete',
          repo: repoSlug,
          branch: branchName,
          outcome: 'cancelled',
        });
        console.error(chalk.red(`SafeRun blocked deletion of branch '${branchName}'.`));
        return 1;
      }

      approvals.push({
        branch: branchName,
        changeId: dryRun.changeId,
        metadata: { branch: branchName, repo: repoSlug, bypassed: outcome === ApprovalOutcome.Bypassed },
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      console.error(chalk.red(`SafeRun error while evaluating branch delete: ${message}`));
      context.metrics.track('operation_allowed', {
        hook: 'alias:branch',
        operation_type: 'branch_delete',
        repo: repoSlug,
        branch: branchName,
        reason: 'api_error',
      }).catch(() => undefined);
      await logOperation(context.gitInfo.repoRoot, {
        event: 'branch_delete',
        operation: 'branch_delete',
        repo: repoSlug,
        branch: branchName,
        outcome: 'api_error',
        error: message,
      });
    }
  }

  const exitCode = await runGitCommand(['branch', ...context.args], {
    cwd: context.gitInfo.repoRoot,
    disableAliases: ['branch'],
  });

  for (const approval of approvals) {
    await context.client.confirmGitOperation({
      changeId: approval.changeId,
      status: exitCode === 0 ? 'applied' : 'failed',
      metadata: exitCode === 0 ? approval.metadata : { ...approval.metadata, exitCode },
    });
  }

  if (exitCode === 0) {
    for (const branchName of branches) {
      context.metrics.track('operation_allowed', {
        hook: 'alias:branch',
        operation_type: 'branch_delete',
        repo: repoSlug,
        branch: branchName,
        reason: 'executed',
      }).catch(() => undefined);
      await logOperation(context.gitInfo.repoRoot, {
        event: 'branch_delete',
        operation: 'branch_delete',
        repo: repoSlug,
        branch: branchName,
        outcome: 'executed',
      });
    }
  } else {
    for (const branchName of branches) {
      context.metrics.track('operation_blocked', {
        hook: 'alias:branch',
        operation_type: 'branch_delete',
        repo: repoSlug,
        branch: branchName,
        reason: 'git_failed',
      }).catch(() => undefined);
      await logOperation(context.gitInfo.repoRoot, {
        event: 'branch_delete',
        operation: 'branch_delete',
        repo: repoSlug,
        branch: branchName,
        outcome: 'failed',
        exitCode,
      });
    }
  }

  return exitCode;
}

interface PendingApproval {
  branch: string;
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

  let action: EnforcementAction = (ruleAction as EnforcementAction | undefined) ?? defaultAction;

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
