import chalk from 'chalk';
import inquirer from 'inquirer';
import { exec } from 'child_process';
import { promisify } from 'util';
import { getGitInfo, isGitRepository } from '../utils/git';
import { loadConfig, saveConfig } from '../utils/config';
import { loadGlobalConfig, saveGlobalConfig } from '../utils/global-config';
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

    // Set branches (with Fail Fast validation)
    if (options.set) {
      const branches = options.set.split(',').map(b => b.trim()).filter(b => b);
      if (branches.length === 0) {
        console.error(chalk.red('❌ Cannot set empty branch list'));
        process.exitCode = 1;
        return;
      }
      
      // Banking Grade: Fail Fast validation
      const validation = await this.validateBranchesStrict(branches);
      if (!validation.valid) {
        console.error(chalk.red(`\n❌ Cannot save: invalid branch names detected\n`));
        validation.errors.forEach(e => console.error(chalk.red(`   • ${e}`)));
        console.log(chalk.yellow(`\n💡 Tip: Use "saferun settings branches" without --set for interactive selection`));
        process.exitCode = 1;
        return;
      }
      
      const result = await this.updateProtectedBranches(branches);
      if (result.success) {
        console.log(chalk.green(`\n✅ Protection active for: [${result.patterns?.join(', ') || branches.join(', ')}]`));
        console.log(chalk.gray('🛡️  Force-pushes to these branches will require Slack approval.'));
        console.log(chalk.gray('⚡  Changes applied immediately. No sync required.\n'));
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
      console.log(chalk.gray('   ⚡ Active immediately\n'));
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
      console.log(chalk.gray('   ⚡ Active immediately\n'));
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

  /**
   * Interactive Multi-Select (Banking Grade)
   * Shows real git branches as checkboxes - no typos possible
   */
  async interactiveBranches(): Promise<void> {
    if (!await this.init()) return;

    const current = await this.fetchProtectedBranches() || ['main', 'master'];
    const gitBranches = await this.getLocalGitBranches();

    console.log(chalk.cyan('\n🛡️  Configure Protected Branches\n'));

    // Build choices from git branches + option for custom pattern
    const choices = [
      ...gitBranches.map(b => ({
        name: b,
        value: b,
        checked: current.includes(b),
      })),
      new inquirer.Separator(),
      { name: chalk.gray('+ Add custom pattern (e.g., release/*)'), value: '__CUSTOM__' },
    ];

    const answers = await inquirer.prompt<{ selected: string[] }>({
      type: 'checkbox',
      name: 'selected',
      message: 'Select branches to protect (Space to select, Enter to confirm):',
      choices,
    });

    let finalBranches: string[] = answers.selected.filter((s: string) => s !== '__CUSTOM__');

    // Handle custom pattern
    if (answers.selected.includes('__CUSTOM__')) {
      const patternAnswer = await inquirer.prompt<{ pattern: string }>({
        type: 'input',
        name: 'pattern',
        message: 'Enter custom pattern (e.g., release/*, hotfix-*):',
        validate: (input: string) => {
          if (!input.trim()) return 'Pattern required';
          if (/[^\x00-\x7F]/.test(input)) return 'Non-ASCII characters not allowed';
          return true;
        },
      });
      if (patternAnswer.pattern.trim()) {
        finalBranches.push(patternAnswer.pattern.trim());
      }
    }

    if (finalBranches.length === 0) {
      console.log(chalk.yellow('⚠️  No branches selected. Settings unchanged.'));
      return;
    }

    // Save
    const result = await this.updateProtectedBranches(finalBranches);
    if (result.success) {
      console.log(chalk.green(`\n✅ Protection active for: [${finalBranches.join(', ')}]`));
      console.log(chalk.gray('🛡️  Force-pushes to these branches will require Slack approval.'));
      console.log(chalk.gray('⚡  Changes applied immediately. No sync required.\n'));
    }
  }

  /**
   * Get local git branches (for interactive selection)
   */
  private async getLocalGitBranches(): Promise<string[]> {
    try {
      const { stdout } = await execAsync('git branch -a --format="%(refname:short)"');
      const branches = stdout.split('\n')
        .map(b => b.trim().replace(/^origin\//, ''))
        .filter(b => b && !b.startsWith('HEAD') && !b.includes('->'));
      
      // Dedupe and sort (local branches first)
      const unique = [...new Set(branches)];
      return unique.sort((a, b) => {
        // Priority: main, master, develop first
        const priority = ['main', 'master', 'develop'];
        const aIdx = priority.indexOf(a);
        const bIdx = priority.indexOf(b);
        if (aIdx !== -1 && bIdx !== -1) return aIdx - bIdx;
        if (aIdx !== -1) return -1;
        if (bIdx !== -1) return 1;
        return a.localeCompare(b);
      });
    } catch {
      // Fallback if git command fails
      return ['main', 'master'];
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
      return data.patterns || ['main', 'master'];  // API returns 'patterns' array
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

      // ✨ Write-Through Cache: Update BOTH PostgreSQL AND global config
      // This ensures immediate consistency without requiring manual "saferun sync"
      
      // 1. Get repository slug for context-aware storage
      const gitInfo = await getGitInfo();
      const repoSlug = gitInfo?.repoSlug || 'unknown/repo';

      // 2. Save to global config (~/.saferun/config.yml) with repository isolation
      const globalConfig = await loadGlobalConfig();
      
      // Initialize repositories map if it doesn't exist
      if (!globalConfig.github.repositories) {
        globalConfig.github.repositories = {};
      }
      
      // Store protected branches for THIS specific repository
      globalConfig.github.repositories[repoSlug] = {
        protected_branches: data.patterns || branches,
      };
      
      // Update sync metadata
      if (!globalConfig.sync) {
        globalConfig.sync = {};
      }
      globalConfig.sync.last_sync_at = new Date().toISOString();
      globalConfig.sync.sync_source = 'settings_command';
      globalConfig.sync.synced_repo = repoSlug;
      
      await saveGlobalConfig(globalConfig);

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
   * Banking Grade: Strict validation (Fail Fast)
   * Returns errors instead of warnings - blocks invalid input
   */
  private async validateBranchesStrict(branches: string[]): Promise<{
    valid: boolean;
    errors: string[];
  }> {
    const errors: string[] = [];
    
    try {
      const gitBranches = await this.getLocalGitBranches();
      const branchSet = new Set(gitBranches);

      for (const branch of branches) {
        // Allow wildcard patterns without validation
        if (branch.includes('*')) continue;
        
        // Block non-ASCII characters (catches typos like 'mainб')
        if (/[^\x00-\x7F]/.test(branch)) {
          errors.push(`'${branch}' contains non-ASCII characters`);
          continue;
        }

        // Block if branch not found in repo
        if (!branchSet.has(branch)) {
          const similar = this.findSimilar(branch, [...branchSet]);
          if (similar) {
            errors.push(`'${branch}' not found. Did you mean '${similar}'?`);
          } else {
            errors.push(`'${branch}' not found in this repository`);
          }
        }
      }
    } catch {
      // Git command failed - allow through (maybe not in repo)
      // But still check for non-ASCII
      for (const branch of branches) {
        if (/[^\x00-\x7F]/.test(branch)) {
          errors.push(`'${branch}' contains non-ASCII characters`);
        }
      }
    }

    return {
      valid: errors.length === 0,
      errors,
    };
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
