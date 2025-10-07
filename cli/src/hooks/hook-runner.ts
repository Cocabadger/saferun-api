import chalk from 'chalk';

import { createSafeRunClient } from '../utils/api-client';
import { OperationCache } from '../utils/cache';
import {
  getGitInfo,
  getUnmergedCommitCount,
  isProtectedBranch,
  execGit,
  getCurrentBranch,
  GitEnvironmentInfo,
  matchesBranchPattern,
} from '../utils/git';
import { loadConfig, SafeRunConfig, ModeSettings, OperationRuleConfig } from '../utils/config';
import { MetricsCollector } from '../utils/metrics';
import { logOperation } from '../utils/logger';
import { ApprovalFlow, ApprovalOutcome } from '../utils/approval-flow';
import { SafeRunClient } from '@saferun/sdk';
import { detectAIAgent, AIAgentInfo, getAIAgentType, shouldApplyStrictPolicyForAI } from '../utils/ai-detection';

interface HookContext {
  hook: string;
  args: string[];
  gitInfo: GitEnvironmentInfo;
  config: SafeRunConfig;
  modeSettings?: ModeSettings;
  client: any; // SafeRunClient | OfflineClient
  cache: OperationCache;
  metrics: MetricsCollector;
  aiInfo: AIAgentInfo;
  aiSignals?: any[]; // Detection signals
  aiScore?: number;  // Detection score
}

const ZERO_SHA = '0000000000000000000000000000000000000000';

type EnforcementAction = 'allow' | 'warn' | 'require_approval' | 'block';

interface EnforcementDecision {
  action: EnforcementAction;
  requiresApproval: boolean;
  shouldBlock: boolean;
}

export class HookRunner {
  async run(hookType: string, args: string[]): Promise<void> {
    let metrics: MetricsCollector | null = null;
    try {
      if (!hookType) {
        return;
      }

      const gitInfo = await getGitInfo();
      if (!gitInfo) {
        return;
      }

      const config = await loadConfig(gitInfo.repoRoot, { allowCreate: true });
      metrics = new MetricsCollector(gitInfo.repoRoot, config);
      const cache = new OperationCache(gitInfo.repoRoot);
      const modeSettings = config.modes?.[config.mode];

      // Detect AI agent with multi-signal scoring
      const { collectAllSignals, calculateDetectionScore, getEnforcementAction, detectAIAgent } = await import('../utils/ai-detection');
      const signals = await collectAllSignals(gitInfo.repoRoot);
      const detectionScore = calculateDetectionScore(signals);
      const aiInfo = detectAIAgent(); // Keep for backwards compatibility

      if (signals.length > 0 && detectionScore >= 0.3) {
        const agentTypes = [...new Set(signals.map((s) => s.agentType).filter(Boolean))];
        const confidenceLevel = detectionScore >= 0.7 ? 'high' : detectionScore >= 0.5 ? 'medium' : 'low';
        console.log(chalk.cyan(`🤖 AI Agent detected: ${agentTypes.join(', ')} (confidence: ${confidenceLevel})`));

        if (process.env.SAFERUN_DEBUG) {
          console.log(chalk.gray('Detection signals:'));
          signals.forEach((s) => {
            console.log(chalk.gray(`  • ${s.source}: ${s.reason} (${s.confidence})`));
          });
        }
      }

      if (this.shouldBypass(config, modeSettings)) {
        this.debug('Bypassing SafeRun checks due to environment configuration.');
        return;
      }

      const client = createSafeRunClient({ config, cache });

      const context: HookContext = {
        hook: hookType,
        args,
        gitInfo,
        config,
        modeSettings,
        client,
        cache,
        metrics,
        aiInfo,
        aiSignals: signals,
        aiScore: detectionScore,
      };

      switch (hookType) {
        case 'pre-push':
          await this.handlePrePush(context);
          break;
        case 'pre-commit':
          await this.handlePreCommit(context);
          break;
        case 'post-checkout':
          await this.handlePostCheckout(context);
          break;
        default:
          break;
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      console.error(chalk.red(`SafeRun hook error: ${message}`));
    } finally {
      if (metrics) {
        await metrics.dispose();
      }
    }
  }

  private async handlePrePush(context: HookContext): Promise<void> {
    const [localRef, localSha, remoteRef, remoteSha, remoteName = 'origin', remoteUrl = ''] = context.args;

    if (!localRef || !remoteRef) {
      return;
    }

    const branch = remoteRef.replace('refs/heads/', '');
    const repoSlug = context.config.github.repo === 'auto' ? context.gitInfo.repoSlug ?? 'unknown/repo' : context.config.github.repo;
    const protectedBranch = isProtectedBranch(branch, context.config.github.protected_branches ?? []);

    const deletion = localSha === ZERO_SHA || !localSha;
    const newBranch = remoteSha === ZERO_SHA || !remoteSha;

    // Determine if this is deletion, force push, or merge
    let commitsAhead = 0;
    let isForcePush = false;
    let isMergeCommit = false;

    if (!deletion && !newBranch && localSha && remoteSha) {
      commitsAhead = await getUnmergedCommitCount(remoteSha, localSha, context.gitInfo.repoRoot);
      isForcePush = commitsAhead > 0 && !(await this.isAncestor(remoteSha, localSha, context.gitInfo.repoRoot));
      
      // Check if the local commit is a merge commit
      isMergeCommit = await this.isMergeCommit(localSha, context.gitInfo.repoRoot);
    }

    const operationType = deletion ? 'branch_delete' : (isForcePush ? 'force_push' : (isMergeCommit ? 'merge' : 'push'));
    
    // Simple cache key based on operation and branch
    const cacheKey = context.cache.getOperationHash('pre-push', [operationType, repoSlug, branch], {});

    // Get GitHub token for API call
    const githubToken = process.env.GITHUB_TOKEN || process.env.GH_TOKEN;
    if (!githubToken) {
      console.error(chalk.red('GitHub token not found. Set GITHUB_TOKEN or GH_TOKEN environment variable.'));
      process.exit(1);
    }

    try {
      let dryRun;
      
      if (deletion) {
        // Handle remote branch deletion via API
        dryRun = await context.client.deleteGithubBranch({
          repo: repoSlug,
          branch,
          githubToken,
          webhookUrl: context.config.notifications?.webhook_url as string | undefined,
        });
      } else if (isForcePush) {
        // Handle force push via unified API
        const reason = commitsAhead > 0
          ? `Force push will overwrite approximately ${commitsAhead} commits on ${remoteName}`
          : `Force push to ${branch} on ${remoteName}`;

        dryRun = await context.client.forcePushGithub({
          repo: repoSlug,
          branch,
          githubToken,
          reason,
          webhookUrl: context.config.notifications?.webhook_url as string | undefined,
        });
      } else if (isMergeCommit && protectedBranch) {
        // Handle merge to protected branch via API
        const reason = `Merge commit to protected branch ${branch}`;

        dryRun = await context.client.mergeGithub({
          repo: repoSlug,
          sourceBranch: 'feature', // We can't determine exact source from hook
          targetBranch: branch,
          githubToken,
          reason,
          webhookUrl: context.config.notifications?.webhook_url as string | undefined,
        });
      } else {
        // Regular push - allow
        await context.metrics.track('operation_allowed', {
          hook: 'pre-push',
          operation_type: 'push',
          branch,
          repo: repoSlug,
          reason: 'regular_push',
        });
        return;
      }

      // Track the operation
      await context.metrics.track('pre_push_check', {
        hook: 'pre-push',
        operation_type: operationType,
        branch,
        repo: repoSlug,
        needs_approval: dryRun.needsApproval,
        change_id: dryRun.changeId,
      });

      // If no approval needed, API will handle it automatically
      if (!dryRun.needsApproval) {
        if (deletion) {
          // Display formatted auto-execute message with revert info
          console.log('\n' + chalk.cyan('═'.repeat(60)));
          console.log(chalk.bold.white('  🛡️  SafeRun Protection Active'));
          console.log(chalk.cyan('═'.repeat(60)));
          console.log('');
          console.log(chalk.white('Operation: ') + chalk.yellow('Branch Delete'));
          console.log(chalk.white('Branch: ') + chalk.cyan(branch));
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
        } else {
          console.log(chalk.green(`✓ Force push to '${branch}' approved (always requires approval for irreversible operations)`));
        }
        
        await context.metrics.track('operation_allowed', {
          hook: 'pre-push',
          operation_type: operationType,
          branch,
          repo: repoSlug,
          reason: 'api_auto_execute',
        });
        
        await logOperation(context.gitInfo.repoRoot, {
          event: 'allow',
          operation: operationType,
          repo: repoSlug,
          branch,
          reason: 'api_auto_execute',
          change_id: dryRun.changeId,
        });
        
        await context.cache.set(cacheKey, 'safe', 300_000);
        return;
      }

      // Requires approval - show message
      const operationName = deletion ? 'branch deletion' : (isForcePush ? 'force push' : (isMergeCommit ? 'merge to protected branch' : 'operation'));
      console.log('\n' + chalk.yellow(`⚠️  SafeRun: ${operationName} requires approval`));

      // Show AI-specific message if detected
      if (context.aiScore && context.aiScore >= 0.5) {
        console.log(chalk.cyan('🤖 AI Agent Operation Detected'));
        console.log(chalk.gray('This operation requires human approval because:'));
        console.log(chalk.gray('  • AI agents may lack full context'));
        console.log(chalk.gray('  • Human review ensures intentional changes\n'));

        if (context.aiSignals && context.aiSignals.length > 0) {
          console.log(chalk.gray('Detection reasons:'));
          context.aiSignals.forEach((s: any) => {
            console.log(chalk.gray(`  • ${s.reason}`));
          });
          console.log('');
        }
      }

      const approvalFlow = new ApprovalFlow({
        client: context.client,
        metrics: context.metrics,
        config: context.config,
        modeSettings: context.modeSettings,
        timeoutMs: context.config.approval_timeout?.duration ? context.config.approval_timeout.duration * 1000 : undefined,
      });
      
      const outcome = await approvalFlow.requestApproval(dryRun);

      if (outcome === ApprovalOutcome.Approved || outcome === ApprovalOutcome.Bypassed) {
        console.log(chalk.green(`✓ ${operationName} approved - proceeding with operation`));
        
        await context.metrics.track('operation_allowed', {
          hook: 'pre-push',
          operation_type: operationType,
          branch,
          repo: repoSlug,
          reason: 'approved',
          bypassed: outcome === ApprovalOutcome.Bypassed,
        });
        
        await logOperation(context.gitInfo.repoRoot, {
          event: 'approved',
          operation: operationType,
          repo: repoSlug,
          branch,
          bypassed: outcome === ApprovalOutcome.Bypassed,
        });
        
        await context.cache.set(cacheKey, 'safe', 300_000);
        return;
      }

      // Rejected or cancelled
      console.error(chalk.red(`✗ SafeRun blocked the ${operationName}`));

      // Optional feedback prompt (only if AI was detected)
      if (context.aiSignals && context.aiSignals.length > 0 && context.aiScore && context.aiScore >= 0.3) {
        const { promptFeedback } = await import('../utils/feedback');
        await promptFeedback(
          context.gitInfo.repoRoot,
          dryRun.changeId || 'unknown',
          context.aiSignals,
          context.aiScore,
          'blocked',
          operationType
        );
      }

      await context.metrics.track('operation_blocked', {
        hook: 'pre-push',
        operation_type: operationType,
        branch,
        repo: repoSlug,
        reason: 'user_cancelled',
      });
      
      await logOperation(context.gitInfo.repoRoot, {
        event: 'blocked',
        operation: operationType,
        repo: repoSlug,
        branch,
        reason: 'user_cancelled',
      });
      
      await context.cache.set(cacheKey, 'dangerous', 300_000);
      process.exit(1);
    } catch (error) {
      const err = error instanceof Error ? error : new Error(String(error));
      const { shouldBlock, message } = this.handleAPIError(err, context.config);

      console.error(chalk.red(`SafeRun API error: ${err.message}`));
      console.error(shouldBlock ? chalk.red(message) : chalk.yellow(message));

      if (shouldBlock) {
        await context.metrics.track('operation_blocked', {
          hook: 'pre-push',
          operation_type: operationType,
          branch,
          repo: repoSlug,
          reason: 'api_error_blocked',
        });
        await logOperation(context.gitInfo.repoRoot, {
          event: 'blocked',
          operation: operationType,
          repo: repoSlug,
          branch,
          reason: 'API error - fail_mode blocked operation',
        });
        await context.cache.set(cacheKey, 'dangerous', 300_000);
        process.exit(1);
      } else {
        await context.metrics.track('operation_allowed', {
          hook: 'pre-push',
          operation_type: operationType,
          branch,
          repo: repoSlug,
          reason: 'api_error_graceful',
        });
        await logOperation(context.gitInfo.repoRoot, {
          event: 'error',
          operation: operationType,
          repo: repoSlug,
          branch,
          reason: err.message,
        });
        await context.cache.set(cacheKey, 'unknown', 120_000);
      }
    }
  }

  private async handlePreCommit(context: HookContext): Promise<void> {
    const branch = await getCurrentBranch(context.gitInfo.repoRoot);
    if (!branch) {
      return;
    }

    const protectedBranch = isProtectedBranch(branch, context.config.github.protected_branches ?? []);
    if (!protectedBranch) {
      return;
    }

    const repoSlug = context.config.github.repo === 'auto' ? context.gitInfo.repoSlug ?? 'unknown/repo' : context.config.github.repo;
    const rule = this.getRule(context.config, 'commit_protected');
    const enforcement = this.resolveEnforcement(context.modeSettings, rule?.action, 'require_approval');

    if (enforcement.action === 'allow' || enforcement.action === 'warn') {
      if (enforcement.action === 'warn' || context.modeSettings?.show_warnings) {
        console.warn(chalk.yellow(`SafeRun warning: committing directly to protected branch '${branch}'.`));
      }
      await context.metrics.track('operation_allowed', {
        hook: 'pre-commit',
        operation_type: 'commit_protected',
        repo: repoSlug,
        branch,
        reason: enforcement.action === 'warn' ? 'policy_warn' : 'policy_allow',
      }).catch(() => undefined);
      await logOperation(context.gitInfo.repoRoot, {
        event: 'commit',
        operation: 'commit_protected',
        repo: repoSlug,
        branch,
        outcome: enforcement.action === 'warn' ? 'policy_warn' : 'policy_allow',
      });
      return;
    }

    const humanPreview = `Commit to protected branch ${branch}`;
    const riskScore = this.clampRisk(rule?.risk_score ?? 8.5);

    try {
      const dryRun = await context.client.gitOperation({
        operationType: 'commit_protected',
        target: `${repoSlug}#${branch}`,
        command: 'git commit',
        metadata: {
          repo: repoSlug,
          branch,
          protectedBranch: true,
        },
        riskScore: riskScore / 10,
        humanPreview,
        requiresApproval: enforcement.requiresApproval || enforcement.shouldBlock,
        reasons: ['commit_protected_branch'],
      });

      if (!dryRun.needsApproval && !enforcement.shouldBlock) {
        context.metrics.track('operation_allowed', {
          hook: 'pre-commit',
          operation_type: 'commit_protected',
          repo: repoSlug,
          branch,
          reason: 'no_approval_required',
        }).catch(() => undefined);
        await logOperation(context.gitInfo.repoRoot, {
          event: 'commit',
          operation: 'commit_protected',
          repo: repoSlug,
          branch,
          outcome: 'allowed',
        });
        return;
      }

      if (!dryRun.needsApproval && enforcement.shouldBlock) {
        console.error(chalk.red(`SafeRun policy blocks commits on '${branch}'.`));
        await context.metrics.track('operation_blocked', {
          hook: 'pre-commit',
          operation_type: 'commit_protected',
          repo: repoSlug,
          branch,
          reason: 'policy_block',
        }).catch(() => undefined);
        await logOperation(context.gitInfo.repoRoot, {
          event: 'commit',
          operation: 'commit_protected',
          repo: repoSlug,
          branch,
          outcome: 'blocked',
          reason: 'policy_block',
        });
        process.exit(1);
      }

      const flow = new ApprovalFlow({
        client: context.client,
        metrics: context.metrics,
        config: context.config,
        modeSettings: context.modeSettings,
        timeoutMs: context.config.approval_timeout?.duration ? context.config.approval_timeout.duration * 1000 : undefined,
      });
      const outcome = await flow.requestApproval(dryRun);
      if (outcome !== ApprovalOutcome.Approved && outcome !== ApprovalOutcome.Bypassed) {
        // Try to notify API, but exit regardless of success
        try {
          await context.client.confirmGitOperation({
            changeId: dryRun.changeId,
            status: 'cancelled',
            metadata: { repo: repoSlug, branch },
          });
        } catch (apiError) {
          // Ignore API errors when cancelling - we still block the commit
        }
        context.metrics.track('operation_blocked', {
          hook: 'pre-commit',
          operation_type: 'commit_protected',
          repo: repoSlug,
          branch,
          reason: 'user_cancelled',
        }).catch(() => undefined);
        await logOperation(context.gitInfo.repoRoot, {
          event: 'commit',
          operation: 'commit_protected',
          repo: repoSlug,
          branch,
          outcome: 'cancelled',
        });
        console.error(chalk.red(`SafeRun blocked commit on protected branch '${branch}'.`));
        process.exit(1);
      }

      await context.client.confirmGitOperation({
        changeId: dryRun.changeId,
        status: 'applied',
        metadata: { repo: repoSlug, branch, bypassed: outcome === ApprovalOutcome.Bypassed },
      });
      context.metrics.track('operation_allowed', {
        hook: 'pre-commit',
        operation_type: 'commit_protected',
        repo: repoSlug,
        branch,
        reason: 'approved',
      }).catch(() => undefined);
      await logOperation(context.gitInfo.repoRoot, {
        event: 'commit',
        operation: 'commit_protected',
        repo: repoSlug,
        branch,
        outcome: 'approved',
      });
    } catch (error) {
      const err = error instanceof Error ? error : new Error(String(error));
      const { shouldBlock, message } = this.handleAPIError(err, context.config);

      console.error(chalk.red(`SafeRun pre-commit error: ${err.message}`));
      console.error(shouldBlock ? chalk.red(message) : chalk.yellow(message));

      if (shouldBlock) {
        await context.metrics.track('operation_blocked', {
          hook: 'pre-commit',
          operation_type: 'commit_protected',
          repo: repoSlug,
          branch,
          reason: 'api_error_blocked',
        }).catch(() => undefined);
        await logOperation(context.gitInfo.repoRoot, {
          event: 'blocked',
          operation: 'commit_protected',
          repo: repoSlug,
          branch,
          reason: 'API error - fail_mode blocked operation',
        });
        process.exit(1);
      } else {
        await context.metrics.track('operation_allowed', {
          hook: 'pre-commit',
          operation_type: 'commit_protected',
          repo: repoSlug,
          branch,
          reason: 'api_error_graceful',
        }).catch(() => undefined);
        await logOperation(context.gitInfo.repoRoot, {
          event: 'commit',
          operation: 'commit_protected',
          repo: repoSlug,
          branch,
          outcome: 'api_error',
          error: err.message,
        });
      }
    }
  }

  private async handlePostCheckout(context: HookContext): Promise<void> {
    const [previousRef = '', newRef = '', flag = ''] = context.args;
    const repoSlug = context.config.github.repo === 'auto' ? context.gitInfo.repoSlug ?? 'unknown/repo' : context.config.github.repo;

    await logOperation(context.gitInfo.repoRoot, {
      event: 'checkout',
      repo: repoSlug,
      from: previousRef,
      to: newRef,
      flag,
    });
  }

  private shouldBypass(config: SafeRunConfig, modeSettings?: ModeSettings): boolean {
    const allowBypass = modeSettings?.allow_bypass !== false;
    if (!allowBypass) {
      return false;
    }

    const bypassConfig = config.bypass ?? {};
    const ciEnabled = bypassConfig.ci !== false && bypassConfig.ci_environments?.enabled !== false;
    const ciFlags = bypassConfig.ci_environments?.detect_from_env ?? ['CI', 'GITHUB_ACTIONS', 'GITLAB_CI', 'JENKINS_URL', 'CIRCLECI'];

    if (ciEnabled) {
      if (process.env.CI === 'true' || process.env.CI === '1') {
        return true;
      }
      for (const flag of ciFlags) {
        if (process.env[flag]) {
          return true;
        }
      }
    }

    return false;
  }

  private handleAPIError(error: Error, config: SafeRunConfig): { shouldBlock: boolean; message: string } {
    const errorMessage = error.message || String(error);
    const errorHandling = config.api.error_handling;
    const failMode = config.api.fail_mode || 'graceful';

    // Determine error type
    let errorType: keyof typeof errorHandling;
    if (errorMessage.includes('403') || errorMessage.includes('Forbidden') || errorMessage.includes('limit exceeded')) {
      errorType = '403_forbidden';
    } else if (errorMessage.includes('500') || errorMessage.includes('Internal Server Error')) {
      errorType = '500_server_error';
    } else if (errorMessage.includes('timeout') || errorMessage.includes('ETIMEDOUT')) {
      errorType = 'timeout';
    } else {
      errorType = 'network_error';
    }

    // Handle based on fail_mode
    if (failMode === 'strict') {
      return {
        shouldBlock: true,
        message: `🚫 API error (${failMode} mode) - operation blocked for safety: ${errorMessage}`,
      };
    }

    if (failMode === 'permissive') {
      return {
        shouldBlock: false,
        message: `⚠️  API error (${failMode} mode) - proceeding with warning: ${errorMessage}`,
      };
    }

    // Graceful mode: check specific error handling
    const handler = errorHandling?.[errorType];
    if (!handler) {
      return {
        shouldBlock: false,
        message: `⚠️  API error - proceeding with warning: ${errorMessage}`,
      };
    }

    return {
      shouldBlock: handler.action === 'block',
      message: handler.message || errorMessage,
    };
  }

  private async isAncestor(base: string, tip: string, cwd: string): Promise<boolean> {
    try {
      await execGit(['merge-base', '--is-ancestor', base, tip], { cwd });
      return true;
    } catch {
      return false;
    }
  }

  private async isMergeCommit(sha: string, cwd: string): Promise<boolean> {
    try {
      // Get parent count - merge commits have 2+ parents
      const stdout = await execGit(['rev-list', '--parents', '-n', '1', sha], { cwd });
      const parents = stdout.trim().split(' ');
      return parents.length > 2; // First element is the commit itself, so >2 means 2+ parents
    } catch {
      return false;
    }
  }

  private getRule(config: SafeRunConfig, key: string): OperationRuleConfig | undefined {
    return config.rules?.[key];
  }

  private resolveEnforcement(
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

  private clampRisk(score: number): number {
    if (Number.isNaN(score)) {
      return 0;
    }
    return Math.min(10, Math.max(0, score));
  }

  private debug(message: string): void {
    if (process.env.SAFERUN_DEBUG) {
      console.log(chalk.gray(`[SafeRun] ${message}`));
    }
  }
}
