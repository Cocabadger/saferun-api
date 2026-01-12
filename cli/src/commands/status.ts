import chalk from 'chalk';
import https from 'https';
import { execGit, getGitInfo, isGitRepository, listHooks } from '../utils/git';
import { loadConfig } from '../utils/config';
import { loadManifest } from '../hooks/installer';
import { resolveApiKey } from '../utils/api-client';
import { readLogEntries } from '../utils/logger';
import { backgroundSync } from '../utils/sync';

export class StatusCommand {
  private tailCount: number = 10;

  async run(options?: { agents?: boolean; pending?: boolean; tail?: number }): Promise<void> {
    // Lazy background sync - update settings if stale
    backgroundSync().catch(() => {/* silent */});

    if (options?.tail) {
      this.tailCount = options.tail;
    }

    if (options?.agents) {
      await this.showAgentStatus();
      return;
    }

    if (options?.pending) {
      await this.showPendingApprovals();
      return;
    }

    await this.showGeneralStatus();
  }

  private async showAgentStatus(): Promise<void> {
    const isRepo = await isGitRepository();
    if (!isRepo) {
      console.error(chalk.red('❌ Not inside a git repository.'));
      process.exitCode = 1;
      return;
    }

    const gitInfo = await getGitInfo();
    if (!gitInfo) {
      console.error(chalk.red('❌ Unable to determine git repository information.'));
      process.exitCode = 1;
      return;
    }

    console.log(chalk.cyan('\n🤖 AI Agent Detection Status\n'));

    // Collect all signals
    const { collectAllSignals, calculateDetectionScore, getEnforcementAction } = await import('../utils/ai-detection');
    const signals = await collectAllSignals(gitInfo.repoRoot);
    const score = calculateDetectionScore(signals);
    const action = getEnforcementAction(score);

    if (signals.length === 0) {
      console.log(chalk.green('✅ No AI agent detected'));
      console.log(chalk.gray('\n💡 To improve detection for ChatGPT/Claude sessions:'));
      console.log(chalk.cyan('   saferun shell-init --auto'));
      return;
    }

    console.log(chalk.bold('Active Detection Signals:\n'));

    signals.forEach((signal, i) => {
      const confidenceColor = signal.confidence >= 0.8 ? chalk.green : signal.confidence >= 0.5 ? chalk.yellow : chalk.gray;
      console.log(chalk.white(`  ${i + 1}. `) + chalk.cyan(signal.source.toUpperCase()));
      console.log(chalk.gray(`     Confidence: `) + confidenceColor((signal.confidence * 100).toFixed(0) + '%'));
      console.log(chalk.gray(`     Agent: `) + chalk.white(signal.agentType || 'unknown'));
      if (signal.reason) {
        console.log(chalk.gray(`     Reason: `) + chalk.white(signal.reason));
      }
      console.log('');
    });

    console.log(chalk.bold(`Total Detection Score: ${(score * 100).toFixed(0)}%`));
    console.log(chalk.gray(`Enforcement Action: ${action.toUpperCase()}`));

    if (action === 'allow' || action === 'warn') {
      console.log(chalk.gray('\n💡 Score below blocking threshold. Operations will proceed with warnings.'));
    }
  }

  private async showGeneralStatus(): Promise<void> {
    const isRepo = await isGitRepository();
    if (!isRepo) {
      console.error(chalk.red('❌ Not inside a git repository.'));
      process.exitCode = 1;
      return;
    }

    const gitInfo = await getGitInfo();
    if (!gitInfo) {
      console.error(chalk.red('❌ Unable to determine git repository information.'));
      process.exitCode = 1;
      return;
    }

    const config = await loadConfig(gitInfo.repoRoot, { allowCreate: true });
    const manifest = await loadManifest(gitInfo.repoRoot);
    const hooks = await listHooks(gitInfo.gitDir);
    const apiStatus = await this.checkApi(config.api.url);

    // Header
    console.log('');
    console.log(chalk.cyan('═══════════════════════════════════════════════'));
    console.log(chalk.cyan.bold('           🛡️  SafeRun Status Report'));
    console.log(chalk.cyan('═══════════════════════════════════════════════'));
    console.log('');

    // Protection Status
    const modeColor = config.mode === 'block' ? chalk.green : chalk.yellow;
    console.log(chalk.white.bold('PROTECTION'));
    console.log(chalk.gray('───────────────────────────────────────────────'));
    console.log(`  Mode:        ${modeColor.bold(config.mode.toUpperCase())}`);
    console.log(`  Hooks:       ${manifest?.hooks?.length ? chalk.green('✓ Installed') : chalk.yellow('✗ Not installed')}`);
    console.log(`  API Key:     ${resolveApiKey(config) ? chalk.green('✓ Configured') : chalk.red('✗ Missing')}`);
    console.log(`  API Server:  ${apiStatus ? chalk.green('✓ Reachable') : chalk.red('✗ Unreachable')}`);
    console.log('');

    // Git Hooks
    console.log(chalk.white.bold('GIT HOOKS'));
    console.log(chalk.gray('───────────────────────────────────────────────'));
    if (hooks.length) {
      hooks.forEach((hook) => console.log(`  ${chalk.green('•')} ${hook}`));
    } else {
      console.log(chalk.gray('  No hooks installed'));
    }
    console.log('');

    // Alias overrides
    console.log(chalk.white.bold('COMMAND INTERCEPTS'));
    console.log(chalk.gray('───────────────────────────────────────────────'));
    for (const alias of ['branch', 'reset', 'clean', 'push', 'commit']) {
      let managed = false;
      try {
        const value = (await execGit(['config', '--get', `alias.${alias}`], { cwd: gitInfo.repoRoot })).trim();
        managed = value.includes('saferun hook');
      } catch {
        // alias not set
      }
      const status = managed ? chalk.green('✓ Protected') : chalk.gray('○ Standard');
      console.log(`  git ${alias.padEnd(8)} ${status}`);
    }
    console.log('');

    // Config path
    console.log(chalk.white.bold('CONFIG'));
    console.log(chalk.gray('───────────────────────────────────────────────'));
    console.log(`  Global: ${chalk.cyan('~/.saferun/config.yml')}`);
    console.log(`  Repo:   ${chalk.cyan(gitInfo.repoRoot)}`);
    console.log('');

    // Recent activity
    await this.printRecentActivity(gitInfo.repoRoot);

    console.log(chalk.cyan('═══════════════════════════════════════════════'));
    console.log('');
  }

  private async checkApi(url: string): Promise<boolean> {
    return new Promise((resolve) => {
      try {
        const { hostname, pathname, port, protocol } = new URL(url);
        const options: https.RequestOptions = {
          hostname,
          path: pathname === '/' ? '/health' : `${pathname.replace(/\/$/, '')}/health`,
          port: port ? Number(port) : protocol === 'https:' ? 443 : 80,
          method: 'GET',
          timeout: 2000,
        };
        const req = https.request(options, (res) => {
          res.destroy();
          resolve(res.statusCode ? res.statusCode < 500 : false);
        });
        req.on('error', () => resolve(false));
        req.on('timeout', () => {
          req.destroy();
          resolve(false);
        });
        req.end();
      } catch {
        resolve(false);
      }
    });
  }

  private async printRecentActivity(repoRoot: string): Promise<void> {
    const entries = await readLogEntries(repoRoot);
    
    console.log(chalk.white.bold('RECENT ACTIVITY'));
    console.log(chalk.gray('───────────────────────────────────────────────'));
    
    if (entries.length === 0) {
      console.log(chalk.gray('  No activity recorded yet'));
      console.log('');
      return;
    }

    // Get last N operations (no filter - show everything)
    const recent = entries.slice(-this.tailCount);

    // Calculate stats - 3 categories: Approved, Declined, Info (checkout)
    const approved = recent.filter(e => 
      e.outcome === 'approved' || 
      e.outcome === 'allowed' ||
      e.outcome === 'executed' ||
      e.outcome === 'api_auto_execute' ||
      e.event === 'allow' ||
      e.event === 'approved'
    ).length;
    const infoEvents = recent.filter(e => e.event === 'checkout').length;
    const declined = recent.filter(e => {
      if (e.event === 'checkout') return false; // Don't count checkout as declined
      return e.outcome === 'blocked' || 
             e.outcome === 'cancelled' || 
             e.outcome === 'timeout' ||
             e.event === 'error' ||
             e.event === 'blocked' ||
             (e.outcome && String(e.outcome).includes('error'));
    }).length;
    const aiOps = recent.filter(e => e.is_ai_generated === true).length;

    // Calculate time range
    const firstDate = recent[0]?.ts ? new Date(recent[0].ts) : null;
    const lastDate = recent[recent.length - 1]?.ts ? new Date(recent[recent.length - 1].ts) : null;
    let timeRange = '';
    if (firstDate && lastDate) {
      const daysDiff = Math.ceil((lastDate.getTime() - firstDate.getTime()) / (1000 * 60 * 60 * 24));
      if (daysDiff === 0) {
        timeRange = 'Today';
      } else if (daysDiff === 1) {
        timeRange = 'Last 2 days';
      } else {
        timeRange = `Last ${daysDiff + 1} days`;
      }
    }
    
    // Summary line - only show AI count if not all operations are from AI
    const aiSuffix = aiOps > 0 && aiOps < recent.length 
      ? `  ${chalk.magenta('🤖 ' + aiOps)}` 
      : '';
    console.log(`  ${chalk.gray(timeRange)}  |  ` +
                `${chalk.white(recent.length)} ops  ` +
                `${chalk.green('✓ ' + approved)}  ` +
                `${chalk.red('✗ ' + declined)}` +
                aiSuffix);
    console.log('');

    // Show each operation with hierarchy
    recent.forEach((entry) => {
      const ts = entry.ts ? new Date(entry.ts as string) : null;
      const dateStr = ts ? ts.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) : '';
      const timeStr = ts ? ts.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' }) : '';
      
      const operation = this.formatOperation(String(entry.operation || entry.event || 'unknown'));
      const target = String(entry.branch || entry.target || entry.to || '');
      const outcome = String(entry.outcome || entry.reason || '');
      const error = String(entry.error || entry.reason || '');
      const event = String(entry.event || '');
      
      // AI indicator
      const aiIcon = entry.is_ai_generated ? chalk.magenta('🤖') : '  ';
      
      // 3 types: approved, declined, info (checkout, etc.)
      const isApproved = outcome === 'approved' || outcome === 'allowed' || outcome === 'executed' || outcome === 'api_auto_execute' || event === 'allow' || event === 'approved';
      const isInfo = event === 'checkout'; // Just informational, not approve/decline
      const isDeclined = !isApproved && !isInfo;
      
      // Build reason string for declined operations
      let declineReason = '';
      if (!isApproved) {
        if (outcome === 'cancelled') {
          declineReason = 'User cancelled';
        } else if (outcome === 'timeout') {
          declineReason = 'Timed out';
        } else if (outcome === 'blocked') {
          declineReason = 'Blocked by policy';
        } else if (error) {
          // Use actual error message
          const errorStr = error.toString();
          declineReason = errorStr.length > 60 ? errorStr.slice(0, 60) + '...' : errorStr;
        } else if (outcome.includes('error') || entry.event === 'error') {
          declineReason = 'API error';
        } else if (outcome) {
          declineReason = outcome;
        }
      }

      // Line 1: Date, Time, AI icon, Operation (colored by type)
      let opColor = chalk.gray; // info
      if (isApproved) opColor = chalk.green;
      else if (isDeclined) opColor = chalk.red;
      console.log(`  ${chalk.gray(dateStr)} ${chalk.white(timeStr)}  ${aiIcon} ${opColor.bold(operation)}`);
      
      // Line 2: Target (if any)
      if (target) {
        console.log(`                        └─ ${chalk.white(target)}`);
      }
      
      // Line 3: Outcome (Approved, Declined, or nothing for info)
      if (isApproved) {
        console.log(`                        └─ ${chalk.green.bold('✓ Approved')}`);
      } else if (isDeclined) {
        console.log(`                        └─ ${chalk.red.bold('✗ Declined')}`);
        // Line 4: Reason for decline (yellow for user actions, red for errors)
        if (declineReason) {
          const reasonColor = declineReason.includes('User') ? chalk.yellow : chalk.red;
          console.log(`                           ${reasonColor('↳ ' + declineReason)}`);
        }
      }
      // Info events (checkout) - no status line, just the operation
      
      console.log(''); // Empty line between entries
    });
  }

  private formatOperation(op: string): string {
    const opMap: Record<string, string> = {
      'force_push': 'Force Push',
      'reset_hard': 'Reset --hard',
      'branch_delete': 'Branch Delete',
      'clean': 'Git Clean',
      'commit_protected': 'Commit (protected)',
      'commit': 'Commit',
      'merge': 'Merge',
      'error': 'Error',
      'allow': 'Allow',
    };
    return opMap[op] || op;
  }

  private async showPendingApprovals(): Promise<void> {
    const isRepo = await isGitRepository();
    if (!isRepo) {
      console.error(chalk.red('❌ Not inside a git repository.'));
      process.exitCode = 1;
      return;
    }

    const gitInfo = await getGitInfo();
    if (!gitInfo) {
      console.error(chalk.red('❌ Unable to determine git repository information.'));
      process.exitCode = 1;
      return;
    }

    const config = await loadConfig(gitInfo.repoRoot, { allowCreate: true });
    
    console.log('');
    console.log(chalk.cyan.bold('⏳ Pending Approvals'));
    console.log(chalk.gray('───────────────────────────────────────────────'));

    // Read local cache for pending operations
    const fs = await import('fs');
    const path = await import('path');
    const cacheDir = path.join(gitInfo.repoRoot, '.saferun', 'cache');
    
    if (!fs.existsSync(cacheDir)) {
      console.log(chalk.gray('  No pending operations'));
      console.log('');
      return;
    }

    const cacheFiles = fs.readdirSync(cacheDir).filter(f => f.endsWith('.json'));
    
    if (cacheFiles.length === 0) {
      console.log(chalk.gray('  No pending operations'));
      console.log('');
      return;
    }

    const pendingOps: Array<{
      operation: string;
      target: string;
      risk: number;
      timestamp: string;
      changeId?: string;
    }> = [];

    for (const file of cacheFiles) {
      try {
        const data = JSON.parse(fs.readFileSync(path.join(cacheDir, file), 'utf-8'));
        if (data.result === 'pending' || data.needsApproval) {
          pendingOps.push({
            operation: data.operation || 'unknown',
            target: data.target || file.replace('.json', ''),
            risk: data.risk || 0,
            timestamp: data.timestamp || new Date(fs.statSync(path.join(cacheDir, file)).mtime).toISOString(),
            changeId: data.changeId,
          });
        }
      } catch {
        // Skip invalid cache files
      }
    }

    if (pendingOps.length === 0) {
      console.log(chalk.gray('  No pending operations'));
      console.log('');
      return;
    }

    pendingOps.forEach((op, i) => {
      const riskColor = op.risk >= 0.8 ? chalk.red : op.risk >= 0.5 ? chalk.yellow : chalk.green;
      const timeAgo = this.getTimeAgo(new Date(op.timestamp));
      
      console.log(`  ${i + 1}. ${chalk.white(op.operation)} → ${op.target}`);
      console.log(`     Risk: ${riskColor((op.risk * 10).toFixed(1) + '/10')}  |  ${chalk.gray(timeAgo)}`);
      if (op.changeId) {
        console.log(`     ID: ${chalk.gray(op.changeId.slice(0, 8))}`);
      }
      console.log('');
    });

    console.log(chalk.gray(`  Total: ${pendingOps.length} pending`));
    console.log(chalk.gray(`  Approve at: ${config.api.url}/approvals`));
    console.log('');
  }

  private getTimeAgo(date: Date): string {
    const seconds = Math.floor((Date.now() - date.getTime()) / 1000);
    
    if (seconds < 60) return `${seconds}s ago`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
    return `${Math.floor(seconds / 86400)}d ago`;
  }
}
