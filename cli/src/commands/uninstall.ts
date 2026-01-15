import chalk from 'chalk';
import inquirer from 'inquirer';
import fs from 'fs';
import path from 'path';
import os from 'os';
import { execGit, getGitInfo, isGitRepository } from '../utils/git';
import { uninstallHooks } from '../hooks/installer';
import { unregisterProtectedRepo, listProtectedRepos } from '../utils/protected-repos';
import { readLogEntries } from '../utils/logger';
import Table from 'cli-table3';

export class UninstallCommand {
  async run(options: { global?: boolean } = {}): Promise<void> {
    if (options.global) {
      await this.runGlobalUninstall();
      return;
    }

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

    // Show statistics before uninstalling
    await this.showStatistics(gitInfo.repoRoot);

    const { confirm } = await inquirer.prompt([
      {
        type: 'confirm',
        name: 'confirm',
        message: 'Remove SafeRun hooks and restore backups?',
        default: false, // Changed to false - make user think twice
      },
    ]);

    if (!confirm) {
      console.log(chalk.yellow('SafeRun uninstall cancelled.'));
      return;
    }

    await uninstallHooks(gitInfo.repoRoot, gitInfo.gitDir);
    await this.restoreAliases(gitInfo.repoRoot);
    
    // Remove from global protected repos registry
    const wasProtected = await unregisterProtectedRepo(gitInfo.repoRoot);
    
    console.log(chalk.green('✅ SafeRun hooks removed. Existing hooks restored if backups were found.'));
    if (wasProtected) {
      console.log(chalk.gray('   Removed from global protected repos registry.'));
    }
    console.log(chalk.gray('\n💡 To reinstall: saferun init'));
  }

  private async showStatistics(repoRoot: string): Promise<void> {
    console.log(chalk.cyan('\n📊 SafeRun Protection Statistics\n'));

    const entries = await readLogEntries(repoRoot);

    if (entries.length === 0) {
      console.log(chalk.gray('No SafeRun activity recorded.\n'));
      return;
    }

    // Calculate statistics
    const totalOps = entries.length;
    const blockedOps = entries.filter((e) => e.outcome === 'blocked' || e.event === 'blocked').length;
    const approvedOps = entries.filter((e) => e.outcome === 'approved' || e.event === 'approved').length;
    const aiOps = entries.filter((e) => e.is_ai_generated === true).length;
    const dangerousOps = entries.filter((e) => 
      e.operation === 'force_push' || 
      e.operation === 'branch_delete' || 
      e.operation === 'hard_reset'
    ).length;

    // Summary table
    const summaryTable = new Table({
      head: ['Metric', 'Count'],
      style: { head: ['cyan'] },
    });

    summaryTable.push(
      ['Total Operations', chalk.bold(totalOps.toString())],
      ['Dangerous Operations Intercepted', chalk.yellow(dangerousOps.toString())],
      ['Operations Blocked', chalk.red(blockedOps.toString())],
      ['Operations Approved', chalk.green(approvedOps.toString())],
      ['AI Agent Operations', chalk.magenta(aiOps.toString())],
    );

    console.log(summaryTable.toString());

    // Time range
    if (entries.length > 0) {
      const firstEntry = entries[0];
      const lastEntry = entries[entries.length - 1];
      const firstDate = firstEntry.ts ? new Date(firstEntry.ts).toLocaleDateString() : 'unknown';
      const lastDate = lastEntry.ts ? new Date(lastEntry.ts).toLocaleDateString() : 'unknown';
      console.log(chalk.gray(`\nActive from ${firstDate} to ${lastDate}`));
    }

    // Show last 5 protected operations
    const protectedOps = entries.filter((e) => 
      e.outcome === 'blocked' || 
      e.outcome === 'approved' ||
      ['force_push', 'branch_delete', 'hard_reset'].includes(e.operation as string)
    ).slice(-5);

    if (protectedOps.length > 0) {
      console.log(chalk.cyan('\n🛡️  Recent Protected Operations:\n'));
      
      protectedOps.forEach((op) => {
        const ts = op.ts ? new Date(op.ts).toLocaleString() : 'unknown';
        const operation = op.operation || 'operation';
        const outcome = op.outcome || 'protected';
        const target = op.branch || op.target || '';
        const aiIndicator = op.is_ai_generated ? chalk.magenta('🤖 ') : '';
        
        console.log(`  ${chalk.gray(ts)} ${aiIndicator}${operation} → ${outcome} ${target ? `(${target})` : ''}`);
      });
    }

    // Show value proposition
    console.log(chalk.cyan('\n💎 SafeRun Protected You From:\n'));
    
    const protectionPoints = [];
    
    if (blockedOps > 0) {
      protectionPoints.push(`  ✓ ${blockedOps} potentially destructive ${blockedOps === 1 ? 'operation' : 'operations'}`);
    }
    
    if (aiOps > 0) {
      protectionPoints.push(`  ✓ ${aiOps} AI agent ${aiOps === 1 ? 'operation' : 'operations'} requiring review`);
    }
    
    if (dangerousOps > 0) {
      protectionPoints.push(`  ✓ ${dangerousOps} risky Git ${dangerousOps === 1 ? 'command' : 'commands'}`);
    }

    if (protectionPoints.length > 0) {
      protectionPoints.forEach(point => console.log(chalk.green(point)));
    } else {
      console.log(chalk.gray('  No dangerous operations detected yet'));
    }

    console.log('');
  }

  private async restoreAliases(repoRoot: string): Promise<void> {
    const backupPath = path.join(repoRoot, '.saferun', 'alias-backup.json');
    if (!fs.existsSync(backupPath)) {
      // Nothing to restore; remove SafeRun aliases if still configured
      await this.clearAlias(repoRoot, 'branch');
      await this.clearAlias(repoRoot, 'reset');
      await this.clearAlias(repoRoot, 'clean');
      await this.clearAlias(repoRoot, 'push');
      return;
    }

    let backup: Record<string, string | null> = {};
    try {
      backup = JSON.parse(await fs.promises.readFile(backupPath, 'utf-8'));
    } catch {
      backup = {};
    }

    for (const alias of ['branch', 'reset', 'clean', 'push']) {
      const original = backup[alias];
      if (typeof original === 'string' && original.length > 0) {
        await execGit(['config', '--replace-all', `alias.${alias}`, original], { cwd: repoRoot }).catch(() => undefined);
      } else {
        await this.clearAlias(repoRoot, alias);
      }
    }

    try {
      await fs.promises.unlink(backupPath);
    } catch {
      /* ignore */
    }
  }

  private async clearAlias(repoRoot: string, alias: string): Promise<void> {
    try {
      await execGit(['config', '--unset', `alias.${alias}`], { cwd: repoRoot });
    } catch {
      // ignore if unset
    }
  }

  private async runGlobalUninstall(): Promise<void> {
    console.log(chalk.cyan('\n🌐 SafeRun Global Uninstall\n'));

    const globalDir = path.join(os.homedir(), '.saferun');
    const protectedRepos = await listProtectedRepos();

    // Show what will be removed
    console.log(chalk.yellow('This will remove:\n'));
    
    if (fs.existsSync(globalDir)) {
      const files = fs.readdirSync(globalDir);
      console.log(chalk.gray('  ~/.saferun/'));
      files.forEach(f => console.log(chalk.gray(`    ├── ${f}`)));
    }

    if (protectedRepos.length > 0) {
      console.log(chalk.gray(`\n  ${protectedRepos.length} protected repo(s):`));
      protectedRepos.forEach(repo => {
        console.log(chalk.gray(`    • ${repo.name || repo.path}`));
      });
    }

    // Check for shell wrapper
    const zshrcPath = path.join(os.homedir(), '.zshrc');
    let hasShellWrapper = false;
    if (fs.existsSync(zshrcPath)) {
      const content = fs.readFileSync(zshrcPath, 'utf-8');
      hasShellWrapper = content.includes('saferun shell-init') || content.includes('# SafeRun');
    }

    if (hasShellWrapper) {
      console.log(chalk.gray('\n  Shell wrapper in ~/.zshrc'));
    }

    console.log('');

    const { confirm } = await inquirer.prompt([
      {
        type: 'confirm',
        name: 'confirm',
        message: chalk.red('Remove ALL SafeRun data and configuration?'),
        default: false,
      },
    ]);

    if (!confirm) {
      console.log(chalk.yellow('Global uninstall cancelled.'));
      return;
    }

    // Remove global directory
    if (fs.existsSync(globalDir)) {
      fs.rmSync(globalDir, { recursive: true });
      console.log(chalk.green('✓ Removed ~/.saferun/'));
    }

    // Remove shell wrapper from .zshrc
    if (hasShellWrapper) {
      let content = fs.readFileSync(zshrcPath, 'utf-8');
      
      // Remove various forms of SafeRun shell integration
      // Form 1: eval "$(saferun shell-init)"
      content = content.replace(/# SafeRun [sS]hell [iI]ntegration\n?eval "\$\(saferun shell-init\)"\n?/g, '');
      // Form 2: Block with start/end markers
      content = content.replace(/# SafeRun Shell Integration[\s\S]*?# End SafeRun Shell Integration\n?/g, '');
      // Form 3: Just the eval line
      content = content.replace(/eval "\$\(saferun shell-init\)"\n?/g, '');
      
      fs.writeFileSync(zshrcPath, content);
      console.log(chalk.green('✓ Removed shell wrapper from ~/.zshrc'));
    }

    console.log(chalk.green('\n✅ SafeRun completely uninstalled.'));
    console.log(chalk.yellow('\n⚠️  To finish uninstallation, run this command:'));
    console.log(chalk.cyan.bold('   npm uninstall -g @saferun/cli'));
    console.log(chalk.gray('\n💡 To reinstall: npm install -g @saferun/cli && saferun setup'));
    console.log(chalk.yellow('\n⚠️  Run: source ~/.zshrc (or restart terminal)'));
  }
}
