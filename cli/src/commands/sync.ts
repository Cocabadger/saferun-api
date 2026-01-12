/**
 * SafeRun Sync Command
 * 
 * Manually sync settings from server to local config.
 * Use when: switching machines, after team policy changes,
 * or when hooks show "stale cache" warning.
 */

import chalk from 'chalk';
import { getGitInfo, isGitRepository } from '../utils/git';
import { loadConfig } from '../utils/config';
import { resolveApiKey } from '../utils/api-client';
import { syncProtectedBranches, getConfigAge, isConfigStale } from '../utils/sync';

export class SyncCommand {
  async run(options: { force?: boolean; verbose?: boolean } = {}): Promise<void> {
    console.log(chalk.cyan('\n🔄 SafeRun Sync\n'));

    // Check if in git repo
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

    // Load config
    const config = await loadConfig(gitInfo.repoRoot, { allowCreate: false });
    if (!config) {
      console.error(chalk.red('❌ SafeRun not configured. Run: saferun setup'));
      process.exitCode = 1;
      return;
    }

    // Show current status
    const age = getConfigAge(config);
    const stale = isConfigStale(config);
    
    console.log(chalk.gray(`Last sync: ${age}`));
    if (stale) {
      console.log(chalk.yellow('Status: Needs update'));
    } else if (!options.force) {
      console.log(chalk.green('Status: Up to date'));
      console.log(chalk.gray('\nUse --force to sync anyway.'));
      return;
    }

    // Get API credentials
    const apiKey = resolveApiKey(config);
    if (!apiKey) {
      console.error(chalk.red('❌ No API key configured.'));
      process.exitCode = 1;
      return;
    }

    const apiUrl = config.api?.url || 'https://saferun-api.up.railway.app';

    // Perform sync
    console.log(chalk.gray('\nSyncing with server...'));
    
    const result = await syncProtectedBranches(apiUrl, apiKey, gitInfo.repoRoot);

    if (result.success) {
      console.log(chalk.green(`\n✅ ${result.message}`));
      
      if (result.protectedBranches && result.protectedBranches.length > 0) {
        console.log(chalk.gray('\nProtected branches:'));
        result.protectedBranches.forEach(b => {
          console.log(chalk.green(`  • ${b}`));
        });
      }
      
      if (options.verbose) {
        const os = await import('os');
        const path = await import('path');
        const globalConfigPath = path.join(os.homedir(), '.saferun', 'config.yml');
        console.log(chalk.gray(`\nConfig saved to: ${globalConfigPath}`));
      }
    } else {
      console.error(chalk.red(`\n❌ ${result.message}`));
      process.exitCode = 1;
    }

    console.log('');
  }
}
