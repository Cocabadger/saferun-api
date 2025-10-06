import chalk from 'chalk';
import { DryRunResult } from '@saferun/sdk';
import { ApprovalFlow, ApprovalOutcome } from '../utils/approval-flow';
import { runGitCommand } from '../utils/git';
import { logOperation } from '../utils/logger';
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
  
  // If no branches to delete, just run the command
  if (branches.length === 0) {
    return runGitCommand(['branch', ...context.args], {
      cwd: context.gitInfo.repoRoot,
      disableAliases: ['branch'],
    });
  }

  const repoSlug = context.config.github.repo === 'auto' ? context.gitInfo.repoSlug ?? 'local/repo' : context.config.github.repo;
  const githubToken = process.env.GITHUB_TOKEN || process.env.GH_TOKEN;
  
  if (!githubToken) {
    console.error(chalk.red('GitHub token not found. Set GITHUB_TOKEN or GH_TOKEN environment variable.'));
    return 1;
  }

  const approvals: PendingApproval[] = [];

  for (const branchName of branches) {
    try {
      // Call SafeRun API to check if branch delete needs approval
      const dryRun: DryRunResult = await context.client.deleteGithubBranch({
        repo: repoSlug,
        branch: branchName,
        githubToken,
        webhookUrl: context.config.notifications?.webhook_url as string | undefined,
      });

      // Track the operation
      context.metrics.track('branch_delete_check', {
        hook: 'alias:branch',
        operation_type: 'branch_delete',
        repo: repoSlug,
        branch: branchName,
        needs_approval: dryRun.needsApproval,
        change_id: dryRun.changeId,
      }).catch(() => undefined);

      // If no approval needed, API will handle it automatically
      if (!dryRun.needsApproval) {
        context.metrics.track('operation_allowed', {
          hook: 'alias:branch',
          operation_type: 'branch_delete',
          repo: repoSlug,
          branch: branchName,
          reason: 'api_auto_execute',
        }).catch(() => undefined);
        
        await logOperation(context.gitInfo.repoRoot, {
          event: 'branch_delete',
          operation: 'branch_delete',
          repo: repoSlug,
          branch: branchName,
          outcome: 'auto_execute',
          change_id: dryRun.changeId,
        });
        
        // Display formatted auto-execute message with revert info
        console.log('\n' + chalk.cyan('═'.repeat(60)));
        console.log(chalk.bold.white('  🛡️  SafeRun Protection Active'));
        console.log(chalk.cyan('═'.repeat(60)));
        console.log('');
        console.log(chalk.white('Operation: ') + chalk.yellow('Branch Delete'));
        console.log(chalk.white('Branch: ') + chalk.cyan(branchName));
        console.log(chalk.white('Risk Score: ') + chalk.green(`${dryRun.riskScore || 0}/10`));
        console.log('');
        console.log(chalk.green('✓ Auto-executed (non-main branch)'));
        console.log('');
        console.log(chalk.cyan('━'.repeat(60)));
        console.log(chalk.bold.yellow('⏰ Revert Window: 2 hours'));
        console.log(chalk.cyan('━'.repeat(60)));
        console.log('');
        if (dryRun.revertUrl) {
          console.log(chalk.white('🌐 Revert URL:'));
          console.log(chalk.blue(`   ${dryRun.revertUrl}`));
          console.log('');
        }
        
        continue;
      }

      // Request approval through SafeRun flow
      const flow = new ApprovalFlow({
        client: context.client,
        metrics: context.metrics,
        config: context.config,
        modeSettings: context.modeSettings,
      });

      const outcome = await flow.requestApproval(dryRun);
      
      if (outcome !== ApprovalOutcome.Approved && outcome !== ApprovalOutcome.Bypassed) {
        console.error(chalk.red(`✗ SafeRun blocked deletion of branch '${branchName}' (${outcome})`));
        
        await logOperation(context.gitInfo.repoRoot, {
          event: 'branch_delete',
          operation: 'branch_delete',
          repo: repoSlug,
          branch: branchName,
          outcome: 'cancelled',
          change_id: dryRun.changeId,
        });
        
        return 1;
      }

      approvals.push({
        branch: branchName,
        changeId: dryRun.changeId,
        bypassed: outcome === ApprovalOutcome.Bypassed,
      });

      console.log(chalk.green(`✓ Branch '${branchName}' approved for deletion`));
      
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      console.error(chalk.red(`SafeRun API error for branch '${branchName}': ${message}`));
      
      context.metrics.track('operation_error', {
        hook: 'alias:branch',
        operation_type: 'branch_delete',
        repo: repoSlug,
        branch: branchName,
        error: message,
      }).catch(() => undefined);
      
      await logOperation(context.gitInfo.repoRoot, {
        event: 'branch_delete',
        operation: 'branch_delete',
        repo: repoSlug,
        branch: branchName,
        outcome: 'api_error',
        error: message,
      });
      
      return 1;
    }
  }

  // Execute git branch delete for approved branches
  if (approvals.length > 0) {
    const exitCode = await runGitCommand(['branch', ...context.args], {
      cwd: context.gitInfo.repoRoot,
      disableAliases: ['branch'],
    });

    // Log execution results
    for (const approval of approvals) {
      if (exitCode === 0) {
        context.metrics.track('operation_executed', {
          hook: 'alias:branch',
          operation_type: 'branch_delete',
          repo: repoSlug,
          branch: approval.branch,
          change_id: approval.changeId,
        }).catch(() => undefined);
        
        await logOperation(context.gitInfo.repoRoot, {
          event: 'branch_delete',
          operation: 'branch_delete',
          repo: repoSlug,
          branch: approval.branch,
          outcome: 'executed',
          change_id: approval.changeId,
        });
      } else {
        await logOperation(context.gitInfo.repoRoot, {
          event: 'branch_delete',
          operation: 'branch_delete',
          repo: repoSlug,
          branch: approval.branch,
          outcome: 'failed',
          exitCode,
          change_id: approval.changeId,
        });
      }
    }

    return exitCode;
  }

  return 0;
}

interface PendingApproval {
  branch: string;
  changeId: string;
  bypassed: boolean;
}
