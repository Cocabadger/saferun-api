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

    let commitsAhead = 0;
    let isForcePush = false;

    if (!deletion && !newBranch && localSha && remoteSha) {
      commitsAhead = await getUnmergedCommitCount(remoteSha, localSha, context.gitInfo.repoRoot);
      isForcePush = commitsAhead > 0 && !(await this.isAncestor(remoteSha, localSha, context.gitInfo.repoRoot));
    }

    const operationType = deletion ? 'branch_delete' : 'force_push';
    const rule = this.getRule(context.config, operationType);

    const reasons: string[] = [];
    if (deletion) reasons.push('delete_remote_branch');
    if (isForcePush) reasons.push('force_push');
    if (protectedBranch) reasons.push('protected_branch');
    if (commitsAhead > 0) reasons.push(`commits_overwritten:${commitsAhead}`);
    if (context.aiInfo.isAIAgent) {
      reasons.push(`ai_agent:${getAIAgentType(context.aiInfo)}`);
    }

    const humanPreview = deletion
      ? `Delete remote branch ${branch} on ${remoteName}`
      : commitsAhead > 0
          ? `Force push to ${branch} will overwrite approximately ${commitsAhead} commits on ${remoteName}`
          : `Force push to ${branch} on ${remoteName}`;

    let riskScore = deletion ? 7.5 : 6;
    riskScore += Math.min(commitsAhead * 0.5, 2);
    if (protectedBranch) {
      riskScore = Math.max(riskScore, 8.5);
    }
    if (isForcePush) {
      riskScore = Math.max(riskScore, 9);
    }
    // AI agents get higher risk score
    if (shouldApplyStrictPolicyForAI(context.aiInfo)) {
      riskScore = Math.min(riskScore + 1.5, 10);
      reasons.push('ai_strict_policy');
    }
    if (rule?.risk_score != null) {
      riskScore = rule.risk_score;
    }
    riskScore = this.clampRisk(riskScore);

    const metadata = {
      repo: repoSlug,
      branch,
      remote: remoteName,
      remoteUrl,
      localRef,
      localSha,
      remoteRef,
      remoteSha,
      protectedBranch,
      commitsAhead,
      isForcePush,
      deletion,
      // AI metadata
      isAIAgent: context.aiInfo.isAIAgent,
      aiAgentType: context.aiInfo.isAIAgent ? getAIAgentType(context.aiInfo) : undefined,
      aiConfidence: context.aiInfo.confidence,
    };

    const cacheKey = context.cache.getOperationHash('pre-push', context.args, metadata);
    const cacheEntry = await context.cache.get(cacheKey);
    if (cacheEntry?.result === 'safe') {
      await context.metrics.track('operation_allowed', {
        hook: 'pre-push',
        operation_type: operationType,
        branch,
        repo: repoSlug,
        reason: 'cache_hit',
      });
      await logOperation(context.gitInfo.repoRoot, {
        event: 'allow',
        operation: operationType,
        repo: repoSlug,
        branch,
        reason: 'cache_hit',
      });
      return;
    }

    const excludedByRule = rule?.exclude_patterns?.some((pattern) => matchesBranchPattern(branch, pattern));
    if (excludedByRule) {
      await context.metrics.track('operation_allowed', {
        hook: 'pre-push',
        operation_type: operationType,
        branch,
        repo: repoSlug,
        reason: 'rule_excluded',
      });
      await logOperation(context.gitInfo.repoRoot, {
        event: 'allow',
        operation: operationType,
        repo: repoSlug,
        branch,
        reason: 'rule_excluded',
      });
      await context.cache.set(cacheKey, 'safe', 180_000);
      return;
    }

    const enforcement = this.resolveEnforcement(context.modeSettings, rule?.action, 'require_approval');

    if (enforcement.action === 'allow' || enforcement.action === 'warn') {
      if (enforcement.action === 'warn' || context.modeSettings?.show_warnings) {
        console.warn(chalk.yellow(`SafeRun warning: ${humanPreview}`));
      }
      await context.metrics.track('operation_allowed', {
        hook: 'pre-push',
        operation_type: operationType,
        branch,
        repo: repoSlug,
        reason: enforcement.action === 'warn' ? 'policy_warn' : 'policy_allow',
      });
      await logOperation(context.gitInfo.repoRoot, {
        event: 'allow',
        operation: operationType,
        repo: repoSlug,
        branch,
        reason: enforcement.action === 'warn' ? 'policy_warn' : 'policy_allow',
      });
      await context.cache.set(cacheKey, 'safe', 180_000);
      return;
    }

    const requiresApproval = enforcement.requiresApproval || enforcement.shouldBlock;
    const command = deletion ? `git push ${remoteName} :${branch}` : `git push --force ${remoteName} ${branch}`;

    try {
      const dryRun = await context.client.gitOperation({
        operationType,
        target: `${repoSlug}#${branch}`,
        command,
        metadata,
        riskScore: riskScore / 10,
        humanPreview,
        requiresApproval,
        reasons,
      });

      if (!dryRun.needsApproval && !enforcement.shouldBlock) {
        await context.metrics.track('operation_allowed', {
          hook: 'pre-push',
          operation_type: operationType,
          branch,
          repo: repoSlug,
          reason: 'api_allows',
        });
        await logOperation(context.gitInfo.repoRoot, {
          event: 'allow',
          operation: operationType,
          repo: repoSlug,
          branch,
          reason: 'api_allows',
        });
        await context.cache.set(cacheKey, 'safe', 300_000);
        return;
      }

      if (!dryRun.needsApproval && enforcement.shouldBlock) {
        console.error(chalk.red('SafeRun policy blocks this push (approval required but not granted).'));
        await context.metrics.track('operation_blocked', {
          hook: 'pre-push',
          operation_type: operationType,
          branch,
          repo: repoSlug,
          reason: 'policy_block',
        });
        await logOperation(context.gitInfo.repoRoot, {
          event: 'blocked',
          operation: operationType,
          repo: repoSlug,
          branch,
          reason: 'policy_block',
        });
        await context.cache.set(cacheKey, 'dangerous', 300_000);
        process.exit(1);
      }

      // Show AI-specific message if detected
      if (context.aiScore && context.aiScore >= 0.5) {
        console.log('\n' + chalk.cyan('🤖 AI Agent Operation Detected'));
        console.log(chalk.yellow('⚠️  SafeRun Protection Active\n'));
        console.log(chalk.gray('This operation requires human approval because:'));
        console.log(chalk.gray('  • AI agents may lack full context'));
        console.log(chalk.gray('  • Human review ensures intentional changes'));
        console.log(chalk.gray('  • Protects against unintended automation\n'));

        if (context.aiSignals && context.aiSignals.length > 0) {
          console.log(chalk.gray('Detection reasons:'));
          context.aiSignals.forEach((s: any) => {
            console.log(chalk.gray(`  • ${s.reason}`));
          });
          console.log('');
        }
      } else {
        console.log('\n' + chalk.yellow('⚠️  SafeRun Protection Active'));
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
        await context.client.confirmGitOperation({
          changeId: dryRun.changeId,
          status: 'applied',
          metadata: { operationType, repoSlug, branch, bypassed: outcome === ApprovalOutcome.Bypassed },
        });
        await context.metrics.track('operation_allowed', {
          hook: 'pre-push',
          operation_type: operationType,
          branch,
          repo: repoSlug,
          reason: 'approved',
        });
        await logOperation(context.gitInfo.repoRoot, {
          event: 'approved',
          operation: operationType,
          repo: repoSlug,
          branch,
        });
        await context.cache.set(cacheKey, 'safe', 300_000);
        return;
      }

      console.error(chalk.red('SafeRun blocked the push operation.'));

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
