import chalk from 'chalk';
import Table from 'cli-table3';
import https from 'https';
import { execGit, getGitInfo, isGitRepository, listHooks } from '../utils/git';
import { loadConfig } from '../utils/config';
import { loadManifest } from '../hooks/installer';
import { resolveApiKey } from '../utils/api-client';
import { readLogEntries } from '../utils/logger';

export class StatusCommand {
  async run(options?: { agents?: boolean; pending?: boolean }): Promise<void> {
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
      console.log(chalk.gray('No AI agent detected'));
      console.log(chalk.gray('\n💡 To improve detection for ChatGPT/Claude sessions:'));
      console.log(chalk.cyan('   saferun shell-init --auto'));
      return;
    }

    console.log(chalk.bold('Active Detection Signals:\n'));

    const table = new Table({
      head: ['Source', 'Confidence', 'Agent Type', 'Reason'],
      style: { head: ['cyan'] },
    });

    signals.forEach((signal) => {
      const confidenceColor = signal.confidence >= 0.8 ? chalk.green : signal.confidence >= 0.5 ? chalk.yellow : chalk.gray;

      table.push([
        signal.source.toUpperCase(),
        confidenceColor((signal.confidence * 100).toFixed(0) + '%'),
        signal.agentType || 'unknown',
        signal.reason || '-',
      ]);
    });

    console.log(table.toString());

    console.log(chalk.bold(`\nTotal Detection Score: ${(score * 100).toFixed(0)}%`));
    console.log(chalk.gray(`Enforcement Action: ${action.toUpperCase()}`));

    if (action === 'allow' || action === 'warn') {
      console.log(chalk.gray('\n💡 Score below blocking threshold. Operations will proceed with warnings.'));
    }

    console.log(chalk.gray('\n📊 View feedback statistics:'));
    console.log(chalk.cyan('   saferun feedback stats'));
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

    console.log(chalk.cyan('\n🛡️  SafeRun Status\n'));

    const summaryTable = new Table({ head: ['Component', 'Status'], style: { head: ['cyan'] } });
    summaryTable.push(
      ['Mode', chalk.bold(config.mode.toUpperCase())],
      ['Hooks directory', gitInfo.gitDir],
      ['SafeRun hooks', manifest?.hooks?.length ? chalk.green('Installed') : chalk.yellow('Not installed')],
      ['API key', resolveApiKey(config) ? chalk.green('Configured') : chalk.red('Missing')],
    );

    console.log(summaryTable.toString());

    if (hooks.length) {
      console.log(chalk.gray('\nExisting hooks:')); 
      hooks.forEach((hook) => console.log(`  • ${hook}`));
    } else {
      console.log(chalk.gray('\nNo hooks detected in git/hooks directory.'));
    }

    await this.printAliasStatus(gitInfo.repoRoot);

    const apiStatus = await this.checkApi(config.api.url);
    console.log(`\nSafeRun API: ${apiStatus ? chalk.green('reachable') : chalk.red('unreachable')}`);

    console.log(`\nConfig path: ${chalk.cyan(`${gitInfo.repoRoot}/.saferun/config.yml`)}`);

    await this.printRecentActivity(gitInfo.repoRoot);
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

  private async printAliasStatus(repoRoot: string): Promise<void> {
    console.log(chalk.gray('\nGit alias overrides:'));
    for (const alias of ['branch', 'reset', 'clean']) {
      let value = '<not set>';
      try {
        value = (await execGit(['config', '--get', `alias.${alias}`], { cwd: repoRoot })).trim();
      } catch {
        value = chalk.yellow('<unset>');
      }
      const managed = value.includes('saferun hook');
      console.log(`  ${alias.padEnd(6)} ${managed ? chalk.green('SafeRun') : value}`);
    }
  }

  private async printRecentActivity(repoRoot: string): Promise<void> {
    const entries = await readLogEntries(repoRoot);
    if (entries.length === 0) {
      console.log(chalk.gray('\nNo recent activity.'));
      return;
    }

    console.log(chalk.cyan('\n📋 Recent Activity (last 10)\n'));

    // Get last 10 operations
    const recent = entries.slice(-10);

    // Group by outcome
    const blocked = recent.filter(e => e.outcome === 'blocked' || e.event === 'blocked');
    const approved = recent.filter(e => e.outcome === 'approved' || e.event === 'approved');
    const allowed = recent.filter(e => e.outcome === 'allowed' || e.event === 'allow');
    const aiOps = recent.filter(e => e.is_ai_generated === true);

    // Summary stats
    console.log(chalk.gray(`Total: ${recent.length} | `) +
                chalk.red(`Blocked: ${blocked.length} | `) +
                chalk.green(`Approved: ${approved.length} | `) +
                chalk.yellow(`Allowed: ${allowed.length} | `) +
                chalk.magenta(`AI: ${aiOps.length}`));
    console.log('');

    // Show operations in table
    const activityTable = new Table({
      head: ['Time', 'Event', 'Operation', 'Target', 'Outcome'],
      style: { head: ['cyan'] },
      colWidths: [20, 12, 15, 25, 12],
    });

    recent.forEach((entry) => {
      const ts = entry.ts ? new Date(entry.ts).toLocaleTimeString() : 'unknown';
      const event = (entry.event || 'event').toString().slice(0, 10);
      const operation = (entry.operation || '-').toString().slice(0, 13);
      const target = (entry.branch || entry.target || '-').toString().slice(0, 23);
      const outcome = (entry.outcome || entry.reason || '-').toString().slice(0, 10);

      // Color code outcome
      let outcomeColored = outcome;
      if (outcome.includes('block')) {
        outcomeColored = chalk.red(outcome);
      } else if (outcome.includes('approv')) {
        outcomeColored = chalk.green(outcome);
      } else if (outcome.includes('allow')) {
        outcomeColored = chalk.yellow(outcome);
      }

      // Add AI indicator
      const eventWithAI = entry.is_ai_generated ? `🤖 ${event}` : event;

      activityTable.push([
        chalk.gray(ts),
        eventWithAI,
        operation,
        chalk.gray(target),
        outcomeColored,
      ]);
    });

    console.log(activityTable.toString());

    // Show helpful tips
    if (blocked.length > 0) {
      console.log(chalk.yellow(`\n⚠️  ${blocked.length} operation(s) were blocked. Check policies if this is unexpected.`));
    }

    if (aiOps.length > 0) {
      console.log(chalk.magenta(`\n🤖 ${aiOps.length} AI agent operation(s) detected. View details:`));
      console.log(chalk.cyan('   saferun history --ai-only'));
    }

    console.log(chalk.gray('\n💡 View full history: saferun history -n 50'));
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
    console.log(chalk.cyan('\n⏳ Pending Approvals\n'));

    // Read local cache for pending operations
    const { OperationCache } = await import('../utils/cache');
    const cache = new OperationCache(gitInfo.repoRoot);
    
    try {
      const fs = await import('fs');
      const path = await import('path');
      const cacheDir = path.join(gitInfo.repoRoot, '.saferun', 'cache');
      
      if (!fs.existsSync(cacheDir)) {
        console.log(chalk.gray('No pending operations found.'));
        return;
      }

      const cacheFiles = fs.readdirSync(cacheDir).filter(f => f.endsWith('.json'));
      
      if (cacheFiles.length === 0) {
        console.log(chalk.gray('No pending operations found.'));
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
        console.log(chalk.gray('No pending operations found.'));
        return;
      }

      const table = new Table({
        head: ['Operation', 'Target', 'Risk', 'Time', 'Change ID'],
        style: { head: ['cyan'] },
      });

      pendingOps.forEach((op) => {
        const riskColor = op.risk >= 0.8 ? chalk.red : op.risk >= 0.5 ? chalk.yellow : chalk.green;
        const timeAgo = this.getTimeAgo(new Date(op.timestamp));
        
        table.push([
          op.operation,
          op.target,
          riskColor((op.risk * 10).toFixed(1)),
          chalk.gray(timeAgo),
          op.changeId ? chalk.gray(op.changeId.slice(0, 8)) : '-',
        ]);
      });

      console.log(table.toString());
      console.log(chalk.gray(`\nTotal: ${pendingOps.length} pending operation(s)`));
      console.log(chalk.gray('\n💡 Approve operations at:'));
      console.log(chalk.cyan(`   ${config.api.url}/approvals`));
    } catch (error) {
      console.error(chalk.red('Error reading pending operations:'), error);
    }
  }

  private getTimeAgo(date: Date): string {
    const seconds = Math.floor((Date.now() - date.getTime()) / 1000);
    
    if (seconds < 60) return `${seconds}s ago`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
    return `${Math.floor(seconds / 86400)}d ago`;
  }
}
