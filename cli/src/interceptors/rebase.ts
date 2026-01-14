import chalk from 'chalk';
import { ApprovalFlow, ApprovalOutcome } from '../utils/approval-flow';
import { runGitCommand, getCurrentBranch, isProtectedBranch } from '../utils/git';
import { logOperation } from '../utils/logger';
import { InterceptorContext } from './types';

interface RebaseParams {
  isInteractive: boolean;
  hasOnto: boolean;
  target?: string;
}

function parseRebaseArgs(args: string[]): RebaseParams {
  const interactiveFlags = new Set(['-i', '--interactive']);
  let isInteractive = false;
  let hasOnto = false;
  let target: string | undefined;

  const nonFlags: string[] = [];

  for (const arg of args) {
    if (interactiveFlags.has(arg)) {
      isInteractive = true;
    } else if (arg === '--onto') {
      hasOnto = true;
    } else if (!arg.startsWith('-')) {
      nonFlags.push(arg);
    }
  }

  // First non-flag arg is usually the target (upstream or branch)
  if (nonFlags.length > 0) {
    target = nonFlags[0];
  }

  return { isInteractive, hasOnto, target };
}

export async function interceptRebase(context: InterceptorContext): Promise<number> {
  const params = parseRebaseArgs(context.args);
  
  // Get repository-specific protected branches
  const repoSlug = context.config.github.repo === 'auto' ? context.gitInfo.repoSlug ?? 'local/repo' : context.config.github.repo;
  const { getProtectedBranchesForRepo } = await import('../utils/config');
  const protectedBranchPatterns = getProtectedBranchesForRepo(context.config, repoSlug);
  const currentBranch = await getCurrentBranch(context.gitInfo.repoRoot);
  const protectedBranch = currentBranch ? isProtectedBranch(currentBranch, protectedBranchPatterns) : false;

  // Allow rebase on non-protected branches without approval
  if (!protectedBranch) {
    console.log(chalk.yellow(`⚠️  Rebase detected on branch: ${currentBranch || 'HEAD'}`));
    console.log(chalk.gray(`   ℹ️  Branch '${currentBranch}' is not protected - proceeding without approval`));
    console.log(chalk.gray(`   (Configure protected branches with: saferun settings branches)\n`));
    
    return runGitCommand(['rebase', ...context.args], {
      cwd: context.gitInfo.repoRoot,
      disableAliases: ['rebase'],
    });
  }
  
  // Calculate risk score based on rebase type
  let riskScore = 6.0; // Base risk for rebase
  const reasons = ['git_rebase'];

  if (params.isInteractive) {
    riskScore = 8.5; // Interactive rebase is higher risk
    reasons.push('interactive_mode');
  }
  if (params.hasOnto) {
    riskScore = Math.max(riskScore, 7.5);
    reasons.push('onto_mode');
  }

  const humanPreview = params.isInteractive
    ? 'Interactive rebase will allow rewriting, combining, or dropping commits. This can corrupt history if done incorrectly.'
    : `Rebase will move your commits on top of ${params.target || 'the target branch'}, rewriting local history.`;

  // Check if blocking is disabled
  if (context.modeSettings?.block_operations === false) {
    if (context.modeSettings?.show_warnings) {
      console.warn(chalk.yellow('SafeRun warning: git rebase will run without approval (block_operations=false).'));
    }
    return runGitCommand(['rebase', ...context.args], {
      cwd: context.gitInfo.repoRoot,
      disableAliases: ['rebase'],
    });
  }

  try {
    const dryRun = await context.client.gitOperation({
      operationType: 'rebase',
      target: repoSlug,
      command: `git rebase ${context.args.join(' ')}`,
      riskScore: riskScore / 10,
      humanPreview,
      requiresApproval: true,
      reasons,
    });

    const flow = new ApprovalFlow({
      client: context.client,
      metrics: context.metrics,
      config: context.config,
      modeSettings: context.modeSettings,
    });

    const outcome = await flow.requestApproval(dryRun);

    if (outcome !== ApprovalOutcome.Approved) {
      console.error(chalk.red('SafeRun blocked git rebase. Approval denied or timed out.'));
      logOperation(context.gitInfo.repoRoot, {
        event: 'rebase_blocked',
        operation: 'rebase',
        command: `git rebase ${context.args.join(' ')}`,
        status: 'blocked',
        reason: 'approval_denied',
      });
      return 1;
    }

    logOperation(context.gitInfo.repoRoot, {
      event: 'rebase_approved',
      operation: 'rebase',
      command: `git rebase ${context.args.join(' ')}`,
      status: 'approved',
      changeId: dryRun.changeId,
    });

    return await runGitCommand(['rebase', ...context.args], {
      cwd: context.gitInfo.repoRoot,
      disableAliases: ['rebase'],
      env: { SAFERUN_APPROVED_CHANGE_ID: dryRun.changeId },
    });

  } catch (error) {
    console.error(chalk.red('SafeRun error: API unreachable. Blocking rebase for safety.'));
    logOperation(context.gitInfo.repoRoot, {
      event: 'rebase_blocked',
      operation: 'rebase',
      command: `git rebase ${context.args.join(' ')}`,
      status: 'blocked',
      reason: 'api_error',
    });
    return 1;
  }
}
