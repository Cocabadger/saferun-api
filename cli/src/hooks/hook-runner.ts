import chalk from 'chalk';
import fs from 'fs';
import path from 'path';

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

      // SECURITY: Bypass mechanism removed. Protection is based ONLY on mode:
      // - 'monitor': Log only
      // - 'warn': Show warnings but allow
      // - 'block': Block with approval option
      // - 'enforce': Strict blocking, no exceptions
      // No environment variable bypasses to prevent exploitation by malicious code.

      const client = createSafeRunClient({ config });

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
        case 'reference-transaction':
          await this.handleReferenceTransaction(context);
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
        // Merge commit to protected branch detected
        console.log('\n' + chalk.cyan('═'.repeat(60)));
        console.log(chalk.bold.white('  🔀 Merge Commit Detected'));
        console.log(chalk.cyan('═'.repeat(60)));
        console.log('');
        console.log(chalk.white('Target Branch: ') + chalk.yellow(branch) + chalk.gray(' (protected)'));
        console.log(chalk.white('Source Branch: ') + chalk.gray('unknown (merged via git CLI)'));
        console.log('');
        console.log(chalk.yellow('⚠️  SafeRun Recommendation:'));
        console.log(chalk.gray('  • Use Pull Requests for better tracking and review'));
        console.log(chalk.gray('  • AI agents should use SafeRun SDK for full protection'));
        console.log('');
        console.log(chalk.green('✓ Proceeding with merge (manual merge allowed)'));
        console.log(chalk.cyan('═'.repeat(60)) + '\n');
        
        await context.metrics.track('operation_allowed', {
          hook: 'pre-push',
          operation_type: 'merge',
          branch,
          repo: repoSlug,
          reason: 'manual_merge_cli',
        });
        
        await logOperation(context.gitInfo.repoRoot, {
          event: 'allow',
          operation: 'merge',
          repo: repoSlug,
          branch,
          reason: 'manual_merge_via_git_cli',
        });
        
        return;
      } else {
        // Regular push - check if protected branch requires approval
        if (protectedBranch) {
          // Protected branch push requires approval
          dryRun = await context.client.gitOperation({
            operationType: 'push_protected',
            target: `${repoSlug}#${branch}`,
            command: 'git push',
            metadata: {
              repo: repoSlug,
              branch,
              protectedBranch: true,
            },
            riskScore: 0.5, // Medium risk
            humanPreview: `Push to protected branch ${branch}`,
            requiresApproval: true,
            reasons: ['push_protected_branch'],
          });
          // Continue to approval flow below...
        } else {
          // Non-protected branch - allow
          await context.metrics.track('operation_allowed', {
            hook: 'pre-push',
            operation_type: 'push',
            branch,
            repo: repoSlug,
            reason: 'regular_push_non_protected',
          });
          return;
        }
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
          // Dynamic message based on operation type
          const operationLabel = protectedBranch
            ? `Push to protected branch '${branch}'`
            : isForcePush
            ? `Force push to '${branch}'`
            : isMergeCommit
            ? `Merge to '${branch}'`
            : deletion
            ? `Branch deletion`
            : `Push to '${branch}'`;
          console.log(chalk.green(`✓ ${operationLabel} approved`));
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
      const operationName = deletion 
        ? 'Branch deletion' 
        : protectedBranch
        ? 'Push to protected branch'
        : isForcePush 
        ? 'Force push' 
        : isMergeCommit 
        ? 'Merge to protected branch' 
        : 'Operation';
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

      if (outcome === ApprovalOutcome.Approved) {
        console.log(chalk.green(`✓ ${operationName} approved - proceeding with operation`));
        
        await context.metrics.track('operation_allowed', {
          hook: 'pre-push',
          operation_type: operationType,
          branch,
          repo: repoSlug,
          reason: 'approved',
          // bypassed field removed - no bypass mechanism
        });
        
        await logOperation(context.gitInfo.repoRoot, {
          event: 'approved',
          operation: operationType,
          repo: repoSlug,
          branch,
          // bypassed field removed
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

    // STEP 1: Scan for secrets in ALL commits (not just protected branches)
    const { scanStagedFilesForSecrets } = await import('../utils/secrets-scanner');
    const { secrets, sensitiveFiles } = scanStagedFilesForSecrets(context.gitInfo.repoRoot);

    if (secrets.length > 0 || sensitiveFiles.length > 0) {
      console.error(chalk.red('\n🔐 SECRETS DETECTED! Commit blocked.\n'));

      if (sensitiveFiles.length > 0) {
        console.error(chalk.yellow('Sensitive files found:'));
        sensitiveFiles.forEach((file) => {
          console.error(chalk.yellow(`  • ${file}`));
        });
        console.error('');
      }

      if (secrets.length > 0) {
        console.error(chalk.red('Secret patterns detected:'));
        secrets.forEach((match) => {
          console.error(chalk.red(`  • ${match.file}:${match.line} - ${match.pattern}`));
          if (match.snippet && process.env.SAFERUN_DEBUG) {
            console.error(chalk.gray(`    ${match.snippet}`));
          }
        });
        console.error('');
      }

      console.error(chalk.cyan('To fix:'));
      console.error(chalk.cyan('  1. Remove secrets from staged files'));
      console.error(chalk.cyan('  2. Use environment variables or secret managers'));
      console.error(chalk.cyan('  3. Add sensitive files to .gitignore\n'));

      await context.metrics.track('operation_blocked', {
        hook: 'pre-commit',
        operation_type: 'secrets_detected',
        repo: context.gitInfo.repoSlug ?? 'unknown',
        branch,
        reason: 'secrets_in_commit',
        secrets_count: secrets.length,
        sensitive_files_count: sensitiveFiles.length,
      }).catch(() => undefined);

      process.exit(1);
    }

    // STEP 2: Commits are local operations - protection happens at push time
    // No additional checks needed here - just allow commit to proceed
    return;
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

  /**
   * Handle reference-transaction hook
   * This is called by Git for ANY ref change: reset, branch -D, checkout, rebase, merge
   * It's the ONLY reliable way to intercept operations that bypass PATH/shell configs
   * 
   * Args format from shell hook:
   *   [0] = operation type: "branch-delete", "branch-update", "head-update"
   *   [1] = ref name (branch name or "HEAD")
   *   [2] = old OID
   *   [3] = new OID
   */
  private async handleReferenceTransaction(context: HookContext): Promise<void> {
    const [operationType, refName, oldOid, newOid] = context.args;
    
    if (!operationType || !refName) {
      return;
    }

    const repoSlug = context.config.github.repo === 'auto' 
      ? context.gitInfo.repoSlug ?? 'unknown/repo' 
      : context.config.github.repo;
    
    const currentBranch = await getCurrentBranch(context.gitInfo.repoRoot);
    const protectedBranches = context.config.github.protected_branches ?? [];
    
    // Determine if this affects a protected branch
    let affectedBranch = refName;
    if (operationType === 'head-update') {
      affectedBranch = currentBranch || 'unknown';
    }
    
    const isProtected = isProtectedBranch(affectedBranch, protectedBranches);
    
    // For head-update: check if this is a safe checkout vs dangerous reset
    // Safe: git checkout other-branch (HEAD changes but current branch doesn't lose commits)
    // Dangerous: git reset --hard HEAD~1 (current branch loses commits)
    let isSafeCheckout = false;
    if (operationType === 'head-update' && oldOid && newOid) {
      // If we're just switching branches (not resetting), the branch ref itself won't change
      // The dangerous case is when branch ref moves backwards
      // For now, allow head-update if it's not on a protected branch's own ref
      // The branch-update handler will catch actual branch changes
      
      // Check if this is just HEAD moving (checkout) vs branch pointer moving (reset)
      // HEAD-only moves are generally safe
      isSafeCheckout = true;
    }
    
    // Log the operation
    await logOperation(context.gitInfo.repoRoot, {
      event: 'reference-transaction',
      repo: repoSlug,
      operation: operationType,
      ref: refName,
      oldOid: oldOid?.substring(0, 8),
      newOid: newOid?.substring(0, 8),
      protected: isProtected,
      aiDetected: context.aiScore && context.aiScore >= 0.3,
    });

    // For head-update that's just a checkout, allow it
    if (operationType === 'head-update' && isSafeCheckout) {
      // Just switching branches - allow without blocking
      // The branch-update hook will catch if the branch itself is being modified
      return;
    }

    // Determine operation risk level and description
    let riskLevel: 'low' | 'medium' | 'high' = 'low';
    let operationDescription = '';
    
    switch (operationType) {
      case 'branch-delete':
        riskLevel = isProtected ? 'high' : 'medium';
        operationDescription = `Delete branch: ${refName}`;
        break;
      case 'branch-update':
        riskLevel = isProtected ? 'high' : 'medium';
        operationDescription = `Update branch: ${refName} (${oldOid?.substring(0, 8)} → ${newOid?.substring(0, 8)})`;
        break;
      case 'head-update':
        riskLevel = isProtected ? 'high' : 'medium';
        operationDescription = `HEAD update on ${affectedBranch} (${oldOid?.substring(0, 8)} → ${newOid?.substring(0, 8)})`;
        break;
      default:
        return; // Unknown operation, allow
    }

    // In monitor mode, just log
    if (context.config.mode === 'monitor') {
      console.log(chalk.cyan(`🔍 [Monitor] ${operationDescription}`));
      return;
    }

    // In warn mode, show warning but allow
    if (context.config.mode === 'warn') {
      console.log(chalk.yellow(`⚠️  [Warning] ${operationDescription}`));
      return;
    }

    // Block/Enforce mode on protected branches
    if (isProtected && (context.config.mode === 'block' || context.config.mode === 'enforce')) {
      console.log(chalk.red(`\n🛡️  SafeRun: Dangerous operation detected`));
      console.log(chalk.yellow(`   Operation: ${operationDescription}`));
      console.log(chalk.yellow(`   Branch: ${affectedBranch} (PROTECTED)`));
      console.log(chalk.yellow(`   Risk Level: ${riskLevel.toUpperCase()}`));
      
      if (context.aiScore && context.aiScore >= 0.3) {
        console.log(chalk.cyan(`   AI Agent: Detected (score: ${Math.round(context.aiScore * 100)}%)`));
      }

      // Map operation type to API operation type
      // Try to detect the actual git command from environment or parent process
      let apiOperationType = 'reset_hard';
      let commandDisplay = `git ${operationType.replace('-', ' ')} (via hook)`;
      
      // GIT_REFLOG_ACTION contains the command name (e.g., "reset", "rebase (start)", "pull", "checkout", "merge")
      const reflogAction = process.env.GIT_REFLOG_ACTION?.toLowerCase() || '';
      const gitDir = process.env.GIT_DIR || path.join(context.gitInfo.repoRoot, '.git');
      const resolvedGitDir = path.isAbsolute(gitDir) ? gitDir : path.join(context.gitInfo.repoRoot, gitDir);
      
      // Detect rebase - check multiple indicators
      const rebaseMergeExists = fs.existsSync(path.join(resolvedGitDir, 'rebase-merge'));
      const rebaseApplyExists = fs.existsSync(path.join(resolvedGitDir, 'rebase-apply'));
      const reflogHasRebase = reflogAction.includes('rebase');
      const isRebase = rebaseMergeExists || rebaseApplyExists || reflogHasRebase;
      
      // Detect other operations from GIT_REFLOG_ACTION
      const isReset = reflogAction.startsWith('reset') || reflogAction.includes('reset');
      const isCheckout = reflogAction.startsWith('checkout') || reflogAction.includes('checkout');
      const isMerge = reflogAction.startsWith('merge') || reflogAction.includes('merge');
      const isPull = reflogAction.startsWith('pull') || reflogAction.includes('pull');
      const isAmend = reflogAction.includes('amend');
      const isCherry = reflogAction.includes('cherry');
      
      if (operationType === 'branch-delete') {
        apiOperationType = 'branch_delete';
        commandDisplay = 'git branch -D (via hook)';
      } else if (operationType === 'branch-update') {
        if (isRebase) {
          apiOperationType = 'rebase';
          commandDisplay = 'git rebase (via hook)';
        } else if (isReset) {
          apiOperationType = 'reset_hard';
          commandDisplay = 'git reset --hard (via hook)';
        } else if (isAmend) {
          apiOperationType = 'commit_amend';
          commandDisplay = 'git commit --amend (via hook)';
        } else if (isCherry) {
          apiOperationType = 'cherry_pick';
          commandDisplay = 'git cherry-pick (via hook)';
        } else if (isMerge) {
          apiOperationType = 'merge';
          commandDisplay = 'git merge (via hook)';
        } else if (isPull) {
          apiOperationType = 'pull';
          commandDisplay = 'git pull (via hook)';
        } else if (isCheckout) {
          apiOperationType = 'checkout';
          commandDisplay = 'git checkout (via hook)';
        } else {
          // Default to destructive_history_rewrite for unknown branch updates on protected branches
          // This covers operations we can't precisely identify (rebase, reset, etc.)
          apiOperationType = 'destructive_history_rewrite';
          commandDisplay = reflogAction 
            ? `git ${reflogAction} (via hook)`
            : 'git history change (via hook)';
        }
      }

      // Calculate risk score based on operation type
      const getRiskScore = (): number => {
        switch (apiOperationType) {
          case 'destructive_history_rewrite': return 0.85;
          case 'reset_hard': return 0.85;
          case 'rebase': return 0.85;
          case 'branch_delete': return 0.7;
          case 'commit_amend': return 0.6;
          case 'cherry_pick': return 0.5;
          case 'merge': return 0.5;
          case 'pull': return 0.4;
          case 'checkout': return 0.3;
          default: return riskLevel === 'high' ? 0.8 : 0.5;
        }
      };
      
      // Build reasons array
      const reasons = [`${apiOperationType}_detected`, `protected_branch:${affectedBranch}`];

      // For reference-transaction, use gitOperation API (same as interceptors)
      try {
        const dryRunResult = await context.client.gitOperation({
          operationType: apiOperationType,
          target: `${repoSlug}@${affectedBranch}`,
          command: commandDisplay,
          metadata: {
            repo: repoSlug,
            branch: affectedBranch,
            oldOid: oldOid?.substring(0, 8),
            newOid: newOid?.substring(0, 8),
            refName,
            aiDetected: context.aiScore && context.aiScore >= 0.3,
            reflogAction: reflogAction || undefined,
          },
          riskScore: getRiskScore(),
          humanPreview: operationDescription,
          requiresApproval: true,
          reasons,
        });

        if (!dryRunResult.needsApproval) {
          // Allowed by policy
          console.log(chalk.green('✅ Operation allowed by policy'));
          return;
        }

        // Needs approval - use approval flow
        const approvalFlow = new ApprovalFlow({
          client: context.client,
          metrics: context.metrics,
          config: context.config,
          modeSettings: context.modeSettings,
        });
        
        const outcome = await approvalFlow.requestApproval(dryRunResult);

        if (outcome === ApprovalOutcome.Approved) {
          console.log(chalk.green('✅ Operation approved'));
          await context.metrics.track('operation_approved', {
            hook: 'reference-transaction',
            operation_type: operationType,
            repo: repoSlug,
            branch: affectedBranch,
          }).catch(() => undefined);
          return;
        }

        // Blocked
        console.log(chalk.red('\n❌ Operation blocked by SafeRun'));
        await context.metrics.track('operation_blocked', {
          hook: 'reference-transaction',
          operation_type: operationType,
          repo: repoSlug,
          branch: affectedBranch,
          reason: 'cancelled',
        }).catch(() => undefined);
        
        process.exit(1);
      } catch (error) {
        // SECURITY: Block operation when API unavailable (fail-secure)
        // This is critical - we cannot allow dangerous operations without API verification
        const message = error instanceof Error ? error.message : String(error);
        console.error(chalk.red(`\n🚫 Operation blocked - SafeRun API unreachable`));
        console.error(chalk.yellow(`   Cannot verify safety without API connection.`));
        console.error(chalk.gray(`   Error: ${message}`));
        
        await context.metrics.track('operation_blocked', {
          hook: 'reference-transaction',
          operation_type: operationType,
          repo: repoSlug,
          branch: affectedBranch,
          reason: 'api_unreachable',
        }).catch(() => undefined);
        
        await logOperation(context.gitInfo.repoRoot, {
          event: 'reference-transaction',
          operation: operationType,
          repo: repoSlug,
          branch: affectedBranch,
          outcome: 'blocked_api_error',
          error: message,
        });
        
        process.exit(1);
      }
    }
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
