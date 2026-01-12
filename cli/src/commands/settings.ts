import chalk from 'chalk';
import inquirer from 'inquirer';
import { exec } from 'child_process';
import { promisify } from 'util';
import { getGitInfo, isGitRepository } from '../utils/git';
import { loadConfig, saveConfig } from '../utils/config';
import { resolveApiKey } from '../utils/api-client';

const execAsync = promisify(exec);

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
      
      // Smart validation (Layer 2: CLI Warning)
      await this.validateBranchesLocally(branches);
      
      const result = await this.updateProtectedBranches(branches);
      if (result.success) {
        console.log(chalk.green(`✅ Protected branches set to: ${result.patterns?.join(', ') || branches.join(', ')}`));
        
        // Show API warnings if any
        if (result.warnings && result.warnings.length > 0) {
          console.log(chalk.yellow('\n⚠️  Server warnings:'));
          result.warnings.forEach(w => console.log(chalk.yellow(`   • ${w}`)));
        }
      }
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

  private async updateProtectedBranches(branches: string[]): Promise<{
    success: boolean;
    patterns?: string[];
    warnings?: string[];
  }> {
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
        return { success: false };
      }

      const data = await response.json();

      // Also save to local config for CLI filtering
      const gitInfo = await getGitInfo();
      if (gitInfo) {
        const config = await loadConfig(gitInfo.repoRoot);
        config.github.protected_branches = data.patterns || branches;
        await saveConfig(config, gitInfo.repoRoot);
      }

      return {
        success: true,
        patterns: data.patterns,
        warnings: data.warnings,
      };
    } catch (error) {
      console.error(chalk.red(`❌ Network error: ${error}`));
      return { success: false };
    }
  }

  /**
   * Layer 2: Smart CLI validation
   * Check branches against local git repo and warn about suspicious input
   */
  private async validateBranchesLocally(branches: string[]): Promise<void> {
    try {
      // Get all local and remote branches
      const { stdout } = await execAsync('git branch -a --format="%(refname:short)"');
      const gitBranches = stdout.split('\n')
        .map(b => b.trim().replace(/^origin\//, ''))  // Normalize remote branches
        .filter(b => b && !b.startsWith('HEAD'));
      const branchSet = new Set(gitBranches);

      // Common branch names for fuzzy matching
      const COMMON = ['main', 'master', 'develop', 'dev', 'staging', 'production', 'prod', 'release', 'hotfix'];

      for (const branch of branches) {
        // Skip patterns (wildcards)
        if (branch.includes('*')) continue;
        
        // Check for non-ASCII (likely typos)
        if (/[^\x00-\x7F]/.test(branch)) {
          console.log(chalk.yellow(`⚠️  Warning: '${branch}' contains non-ASCII characters (typo?)`));
          continue;
        }

        // Check if branch exists
        if (!branchSet.has(branch)) {
          // Try to find similar branch
          const similar = this.findSimilar(branch, [...branchSet, ...COMMON]);
          if (similar) {
            console.log(chalk.yellow(`⚠️  Warning: '${branch}' not found. Did you mean '${similar}'?`));
          } else {
            console.log(chalk.gray(`ℹ️  Note: '${branch}' not found in current repo (may exist elsewhere)`));
          }
        }
      }
    } catch {
      // Git command failed - skip validation (not in git repo or other issue)
    }
  }

  /**
   * Find similar string using simple Levenshtein-like comparison
   */
  private findSimilar(input: string, candidates: string[]): string | null {
    const inputLower = input.toLowerCase();
    let bestMatch: string | null = null;
    let bestScore = 0;

    for (const candidate of candidates) {
      if (candidate.toLowerCase() === inputLower) continue; // Exact match
      
      const score = this.similarityScore(inputLower, candidate.toLowerCase());
      if (score > 0.6 && score > bestScore) {
        bestScore = score;
        bestMatch = candidate;
      }
    }

    return bestMatch;
  }

  private similarityScore(s1: string, s2: string): number {
    if (Math.abs(s1.length - s2.length) > 3) return 0;
    
    const set1 = new Set(s1);
    const set2 = new Set(s2);
    const intersection = [...set1].filter(c => set2.has(c)).length;
    const union = new Set([...set1, ...set2]).size;
    
    return intersection / union;
  }
}
