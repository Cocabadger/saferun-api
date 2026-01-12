import chalk from 'chalk';
import inquirer from 'inquirer';
import { getGitInfo, isGitRepository } from '../utils/git';
import { loadConfig, saveConfig } from '../utils/config';
import { resolveApiKey } from '../utils/api-client';

interface BranchesOptions {
  set?: string;
  add?: string;
  remove?: string;
}

export class SettingsCommand {
  private apiUrl: string = '';
  private apiKey: string = '';

  private async init(): Promise<boolean> {
    const isRepo = await isGitRepository();
    if (!isRepo) {
      console.error(chalk.red('❌ Not inside a git repository.'));
      process.exitCode = 1;
      return false;
    }

    const gitInfo = await getGitInfo();
    if (!gitInfo) {
      console.error(chalk.red('❌ Unable to determine git repository information.'));
      process.exitCode = 1;
      return false;
    }

    const config = await loadConfig(gitInfo.repoRoot, { allowCreate: false });
    if (!config) {
      console.error(chalk.red('❌ SafeRun not configured. Run: saferun setup'));
      process.exitCode = 1;
      return false;
    }

    this.apiKey = resolveApiKey(config) || '';
    this.apiUrl = config.api?.url || 'https://saferun-api.up.railway.app';

    if (!this.apiKey) {
      console.error(chalk.red('❌ No API key configured.'));
      console.error(chalk.yellow('   Run: saferun setup'));
      process.exitCode = 1;
      return false;
    }

    return true;
  }

  async showAll(): Promise<void> {
    if (!await this.init()) return;

    console.log(chalk.cyan('\n🔧 SafeRun Settings\n'));

    // Get protected branches
    const branches = await this.fetchProtectedBranches();
    if (branches) {
      console.log(chalk.white('Protected Branches:'));
      console.log(chalk.green(`  ${branches.join(', ')}`));
    }

    console.log('');
  }

  async branches(options: BranchesOptions): Promise<void> {
    if (!await this.init()) return;

    // Set branches
    if (options.set) {
      const branches = options.set.split(',').map(b => b.trim()).filter(b => b);
      if (branches.length === 0) {
        console.error(chalk.red('❌ Cannot set empty branch list'));
        process.exitCode = 1;
        return;
      }
      await this.updateProtectedBranches(branches);
      console.log(chalk.green(`✅ Protected branches set to: ${branches.join(', ')}`));
      return;
    }

    // Add branch
    if (options.add) {
      const current = await this.fetchProtectedBranches() || ['main', 'master'];
      const toAdd = options.add.trim();
      if (current.includes(toAdd)) {
        console.log(chalk.yellow(`⚠️  Branch "${toAdd}" is already protected`));
        return;
      }
      const updated = [...current, toAdd];
      await this.updateProtectedBranches(updated);
      console.log(chalk.green(`✅ Added "${toAdd}" to protected branches`));
      console.log(chalk.gray(`   Current: ${updated.join(', ')}`));
      return;
    }

    // Remove branch
    if (options.remove) {
      const current = await this.fetchProtectedBranches() || ['main', 'master'];
      const toRemove = options.remove.trim();
      if (!current.includes(toRemove)) {
        console.log(chalk.yellow(`⚠️  Branch "${toRemove}" is not in protected list`));
        return;
      }
      const updated = current.filter(b => b !== toRemove);
      if (updated.length === 0) {
        console.error(chalk.red('❌ Cannot remove last protected branch'));
        process.exitCode = 1;
        return;
      }
      await this.updateProtectedBranches(updated);
      console.log(chalk.green(`✅ Removed "${toRemove}" from protected branches`));
      console.log(chalk.gray(`   Current: ${updated.join(', ')}`));
      return;
    }

    // Show current (default)
    console.log(chalk.cyan('\n🛡️  Protected Branches\n'));
    const branches = await this.fetchProtectedBranches();
    if (branches && branches.length > 0) {
      console.log(chalk.white('Currently protected:'));
      for (const branch of branches) {
        if (branch.includes('*')) {
          console.log(chalk.green(`  • ${branch}`) + chalk.gray(' (pattern)'));
        } else {
          console.log(chalk.green(`  • ${branch}`));
        }
      }
    } else {
      console.log(chalk.yellow('No protected branches configured'));
      console.log(chalk.gray('Default: main, master'));
    }

    console.log(chalk.gray('\nUsage:'));
    console.log(chalk.gray('  saferun settings branches --set main,develop,release/*'));
    console.log(chalk.gray('  saferun settings branches --add staging'));
    console.log(chalk.gray('  saferun settings branches --remove develop'));
    console.log('');
  }

  async interactiveBranches(): Promise<void> {
    if (!await this.init()) return;

    const current = await this.fetchProtectedBranches() || ['main', 'master'];

    console.log(chalk.cyan('\n🛡️  Configure Protected Branches\n'));
    console.log(chalk.gray('Current: ' + current.join(', ')));
    console.log('');

    const { action } = await inquirer.prompt([{
      type: 'list',
      name: 'action',
      message: 'What would you like to do?',
      choices: [
        { name: 'Keep current settings', value: 'keep' },
        { name: 'Add a branch', value: 'add' },
        { name: 'Remove a branch', value: 'remove' },
        { name: 'Replace all (set new list)', value: 'set' },
      ],
    }]);

    if (action === 'keep') {
      console.log(chalk.green('✅ Settings unchanged'));
      return;
    }

    if (action === 'add') {
      const { branch } = await inquirer.prompt([{
        type: 'input',
        name: 'branch',
        message: 'Branch name or pattern (e.g., release/*):',
        validate: (input: string) => input.trim() ? true : 'Branch name required',
      }]);
      await this.branches({ add: branch });
      return;
    }

    if (action === 'remove') {
      const { branch } = await inquirer.prompt([{
        type: 'list',
        name: 'branch',
        message: 'Select branch to remove:',
        choices: current,
      }]);
      await this.branches({ remove: branch });
      return;
    }

    if (action === 'set') {
      const { branches } = await inquirer.prompt([{
        type: 'input',
        name: 'branches',
        message: 'Enter branches (comma-separated):',
        default: current.join(', '),
        validate: (input: string) => input.trim() ? true : 'At least one branch required',
      }]);
      await this.branches({ set: branches });
      return;
    }
  }

  private async fetchProtectedBranches(): Promise<string[] | null> {
    try {
      const response = await fetch(`${this.apiUrl}/v1/settings/protected-branches`, {
        headers: {
          'X-API-Key': this.apiKey,
        },
      });

      if (!response.ok) {
        if (response.status === 404) {
          return ['main', 'master']; // Default
        }
        console.error(chalk.red(`❌ Failed to fetch settings: ${response.status}`));
        return null;
      }

      const data = await response.json();
      return data.branches || ['main', 'master'];
    } catch (error) {
      console.error(chalk.red(`❌ Network error: ${error}`));
      return null;
    }
  }

  private async updateProtectedBranches(branches: string[]): Promise<boolean> {
    try {
      const response = await fetch(`${this.apiUrl}/v1/settings/protected-branches`, {
        method: 'PUT',
        headers: {
          'X-API-Key': this.apiKey,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ branches: branches.join(',') }),  // API expects comma-separated string
      });

      if (!response.ok) {
        const error = await response.text();
        console.error(chalk.red(`❌ Failed to update settings: ${error}`));
        return false;
      }

      // Also save to local config for CLI filtering
      const gitInfo = await getGitInfo();
      if (gitInfo) {
        const config = await loadConfig(gitInfo.repoRoot);
        config.github.protected_branches = branches;
        await saveConfig(config, gitInfo.repoRoot);
      }

      return true;
    } catch (error) {
      console.error(chalk.red(`❌ Network error: ${error}`));
      return false;
    }
  }
}
