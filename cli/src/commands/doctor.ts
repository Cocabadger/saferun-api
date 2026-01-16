/**
 * SafeRun Doctor Command
 * Health check for all SafeRun components
 */

import chalk from 'chalk';
import https from 'https';
import fs from 'fs';
import path from 'path';
import os from 'os';

import { getGitInfo, isGitRepository, listHooks } from '../utils/git';
import { loadGlobalConfig, globalConfigExists } from '../utils/global-config';
import { isRepoProtectedSync, getProtectedRepoSync, listProtectedRepos } from '../utils/protected-repos';
import { loadManifest } from '../hooks/installer';
import {
  loadGlobalCredentials,
  resolveApiKey,
  maskApiKey,
  getGlobalConfigDir,
  getCredentialsPath,
} from '../utils/credentials';
import { wrapperExists, checkBinaryWrapperInPath, getPathExportCommand } from '../utils/binary-wrapper';
import { backgroundSync } from '../utils/sync';

const SAFERUN_API_URL = 'https://saferun-api.up.railway.app';

interface CheckResult {
  name: string;
  status: 'ok' | 'warn' | 'error' | 'skip';
  message: string;
  detail?: string;
}

export class DoctorCommand {
  private checks: CheckResult[] = [];

  async run(): Promise<void> {
    // Lazy background sync - update settings if stale
    backgroundSync().catch(() => {/* silent */});

    console.log(chalk.cyan('\n🩺 SafeRun Health Check\n'));

    // Run all checks
    await this.checkApiKey();
    await this.checkApiServer();
    await this.checkGlobalConfig();
    await this.checkProtectedRepo();
    await this.checkSlack();
    await this.checkGitHubApp();
    await this.checkGitHooks();
    await this.checkShellWrapper();
    await this.checkBinaryWrapper();
    // Note: .gitignore check removed - config is now in ~/.saferun/ (global)
    await this.checkFilePermissions();

    // Print results
    this.printResults();
  }

  private async checkGlobalConfig(): Promise<void> {
    if (globalConfigExists()) {
      const config = await loadGlobalConfig();
      this.checks.push({
        name: 'Global Config',
        status: 'ok',
        message: `Mode: ${config.mode.toUpperCase()}`,
        detail: '~/.saferun/config.yml',
      });
    } else {
      this.checks.push({
        name: 'Global Config',
        status: 'warn',
        message: 'Using defaults',
        detail: 'Run "saferun setup" to customize',
      });
    }
  }

  private async checkProtectedRepo(): Promise<void> {
    const isRepo = await isGitRepository();
    
    if (!isRepo) {
      this.checks.push({
        name: 'Protected Repo',
        status: 'skip',
        message: 'Not in a git repository',
      });
      return;
    }

    const gitInfo = await getGitInfo();
    if (!gitInfo) {
      this.checks.push({
        name: 'Protected Repo',
        status: 'error',
        message: 'Could not get git info',
      });
      return;
    }

    const isProtected = isRepoProtectedSync(gitInfo.repoRoot);
    const repoInfo = getProtectedRepoSync(gitInfo.repoRoot);

    if (isProtected) {
      this.checks.push({
        name: 'Protected Repo',
        status: 'ok',
        message: `Registered (${repoInfo?.github || repoInfo?.name || 'local'})`,
        detail: 'Protected via global registry',
      });
    } else {
      this.checks.push({
        name: 'Protected Repo',
        status: 'error',
        message: 'Not protected',
        detail: 'Run "saferun init" to protect this repo',
      });
    }
  }

  private async checkApiKey(): Promise<void> {
    const apiKey = await resolveApiKey();
    
    if (!apiKey) {
      this.checks.push({
        name: 'API Key',
        status: 'error',
        message: 'Not configured',
        detail: 'Run "saferun setup" to configure',
      });
      return;
    }

    // Check where it came from
    const globalCreds = await loadGlobalCredentials();
    const source = process.env.SAFERUN_API_KEY 
      ? 'environment variable' 
      : globalCreds.api_key 
        ? 'global config (~/.saferun/credentials)' 
        : 'local config';

    this.checks.push({
      name: 'API Key',
      status: 'ok',
      message: `Configured (${maskApiKey(apiKey)})`,
      detail: `Source: ${source}`,
    });
  }

  private async checkApiServer(): Promise<void> {
    try {
      // Check root endpoint for version info
      const response = await this.fetchWithTimeout(`${SAFERUN_API_URL}/`, 5000);
      const data = await response.json();
      
      this.checks.push({
        name: 'API Server',
        status: 'ok',
        message: `Reachable (v${data.version || 'unknown'})`,
        detail: SAFERUN_API_URL,
      });
    } catch (err) {
      this.checks.push({
        name: 'API Server',
        status: 'error',
        message: 'Unreachable',
        detail: `${SAFERUN_API_URL} - ${err}`,
      });
    }
  }

  private async checkSlack(): Promise<void> {
    const apiKey = await resolveApiKey();
    
    if (!apiKey) {
      this.checks.push({
        name: 'Slack',
        status: 'skip',
        message: 'Skipped (no API key)',
      });
      return;
    }

    try {
      const response = await fetch(`${SAFERUN_API_URL}/v1/settings/doctor/check`, {
        headers: { 'X-API-Key': apiKey },
      });
      
      if (response.ok) {
        const data = await response.json();
        
        if (data.slack_connected) {
          const details: string[] = [];
          
          if (data.slack_team_name) {
            details.push(`Team: ${data.slack_team_name}`);
          }
          
          if (data.slack_channel) {
            details.push(`Channel: ${data.slack_channel}`);
          }

          this.checks.push({
            name: 'Slack',
            status: 'ok',
            message: 'Connected',
            detail: details.join(' | ') || 'OAuth configured',
          });
        } else {
          this.checks.push({
            name: 'Slack',
            status: 'warn',
            message: 'Not configured',
            detail: 'Run "saferun setup" to configure',
          });
        }
      } else {
        this.checks.push({
          name: 'Slack',
          status: 'error',
          message: `API error (${response.status})`,
        });
      }
    } catch {
      this.checks.push({
        name: 'Slack',
        status: 'error',
        message: 'Could not check status',
      });
    }
  }

  private async checkGitHubApp(): Promise<void> {
    const apiKey = await resolveApiKey();
    
    if (!apiKey) {
      this.checks.push({
        name: 'GitHub App',
        status: 'skip',
        message: 'Skipped (no API key)',
      });
      return;
    }

    const isRepo = await isGitRepository();
    
    if (!isRepo) {
      this.checks.push({
        name: 'GitHub App',
        status: 'skip',
        message: 'Not in a git repository',
      });
      return;
    }

    try {
      // Use new doctor endpoint to check GitHub installation
      const response = await fetch(`${SAFERUN_API_URL}/v1/settings/doctor/check`, {
        headers: { 'X-API-Key': apiKey },
      });
      
      if (response.ok) {
        const data = await response.json();
        
        if (data.github_connected) {
          const details: string[] = [];
          
          if (data.github_account) {
            details.push(`Account: ${data.github_account}`);
          }
          
          if (data.github_installation_id) {
            details.push(`ID: ${data.github_installation_id}`);
          }

          this.checks.push({
            name: 'GitHub App',
            status: 'ok',
            message: 'Installed',
            detail: details.join(' | ') || 'OAuth configured',
          });
        } else {
          this.checks.push({
            name: 'GitHub App',
            status: 'warn',
            message: 'Not installed on this repo',
            detail: 'Install at github.com/apps/saferun-ai',
          });
        }
      } else {
        this.checks.push({
          name: 'GitHub App',
          status: 'warn',
          message: 'Could not verify',
          detail: 'Install at github.com/apps/saferun-ai',
        });
      }
    } catch {
      this.checks.push({
        name: 'GitHub App',
        status: 'warn',
        message: 'Could not verify',
        detail: 'Check github.com/apps/saferun-ai',
      });
    }
  }

  private async checkGitHooks(): Promise<void> {
    const isRepo = await isGitRepository();
    
    if (!isRepo) {
      this.checks.push({
        name: 'Git Hooks',
        status: 'skip',
        message: 'Not in a git repository',
      });
      return;
    }

    const gitInfo = await getGitInfo();
    if (!gitInfo) {
      this.checks.push({
        name: 'Git Hooks',
        status: 'error',
        message: 'Could not get git info',
      });
      return;
    }

    const manifest = await loadManifest(gitInfo.repoRoot);
    const hooks = await listHooks(gitInfo.gitDir);
    
    // Check for SafeRun hooks directly in .git/hooks (more reliable than manifest)
    const expectedHooks = ['pre-push', 'pre-commit', 'post-checkout', 'reference-transaction'];
    const saferunHooks: string[] = [];
    
    for (const hookName of expectedHooks) {
      const hookPath = path.join(gitInfo.gitDir, 'hooks', hookName);
      if (fs.existsSync(hookPath)) {
        try {
          const content = await fs.promises.readFile(hookPath, 'utf-8');
          if (content.includes('SafeRun') || content.includes('saferun')) {
            saferunHooks.push(hookName);
          }
        } catch {
          // Ignore read errors
        }
      }
    }

    if (saferunHooks.length >= 3) {
      // Check if reference-transaction is present (critical for agent protection)
      const hasRefTx = saferunHooks.includes('reference-transaction');
      
      this.checks.push({
        name: 'Git Hooks',
        status: hasRefTx ? 'ok' : 'warn',
        message: `${saferunHooks.length} SafeRun hooks installed`,
        detail: hasRefTx 
          ? saferunHooks.join(', ')
          : `${saferunHooks.join(', ')} (missing reference-transaction for full agent protection)`,
      });
    } else if (saferunHooks.length > 0) {
      this.checks.push({
        name: 'Git Hooks',
        status: 'warn',
        message: `Only ${saferunHooks.length} hooks installed`,
        detail: 'Run "saferun init" to install full protection',
      });
    } else if (hooks.length > 0) {
      this.checks.push({
        name: 'Git Hooks',
        status: 'warn',
        message: 'Hooks exist but SafeRun not initialized',
        detail: 'Run "saferun init" to install protection',
      });
    } else {
      this.checks.push({
        name: 'Git Hooks',
        status: 'error',
        message: 'No hooks installed',
        detail: 'Run "saferun init" to install protection',
      });
    }
  }

  private async checkShellWrapper(): Promise<void> {
    // Check if shell wrapper is in ~/.zshrc or ~/.bashrc
    const home = os.homedir();
    const shellFiles = [
      path.join(home, '.zshrc'),
      path.join(home, '.bashrc'),
      path.join(home, '.bash_profile'),
    ];

    let found = false;
    let shellFile = '';

    for (const file of shellFiles) {
      if (fs.existsSync(file)) {
        try {
          const content = await fs.promises.readFile(file, 'utf-8');
          if (content.includes('saferun_git_wrapper') || content.includes('# SafeRun shell')) {
            found = true;
            shellFile = path.basename(file);
            break;
          }
        } catch {
          // Ignore read errors
        }
      }
    }

    if (found) {
      this.checks.push({
        name: 'Shell Wrapper',
        status: 'ok',
        message: `Active (${shellFile})`,
        detail: 'Intercepts git commands in protected repos',
      });
    } else {
      this.checks.push({
        name: 'Shell Wrapper',
        status: 'warn',
        message: 'Not configured',
        detail: 'Run "saferun shell-init --auto" for extra protection',
      });
    }
  }

  private async checkBinaryWrapper(): Promise<void> {
    const isRepo = await isGitRepository();
    
    if (!isRepo) {
      this.checks.push({
        name: 'Binary Wrapper',
        status: 'skip',
        message: 'Not in a git repository',
      });
      return;
    }

    const gitInfo = await getGitInfo();
    if (!gitInfo) {
      this.checks.push({
        name: 'Binary Wrapper',
        status: 'skip',
        message: 'Could not get git info',
      });
      return;
    }

    // Check if wrapper file exists
    const hasWrapper = wrapperExists(gitInfo.repoRoot);
    
    if (!hasWrapper) {
      this.checks.push({
        name: 'Binary Wrapper',
        status: 'warn',
        message: 'Not installed',
        detail: 'Run "saferun init" to install protection against direct git calls',
      });
      return;
    }

    // Check if wrapper is in PATH
    const pathCheck = await checkBinaryWrapperInPath(gitInfo.repoRoot);
    
    if (pathCheck.inPath) {
      this.checks.push({
        name: 'Binary Wrapper',
        status: 'ok',
        message: 'Active & in PATH',
        detail: `which git → ${pathCheck.currentGit}`,
      });
    } else {
      // Not critical anymore - reference-transaction hook provides full protection
      this.checks.push({
        name: 'Binary Wrapper',
        status: 'ok',
        message: 'Installed (optional layer)',
        detail: 'reference-transaction hook provides main protection',
      });
    }
  }

  private async checkFilePermissions(): Promise<void> {
    const credentialsPath = getCredentialsPath();
    
    if (!fs.existsSync(credentialsPath)) {
      // Not an error - might use env var
      return;
    }

    try {
      const stats = await fs.promises.stat(credentialsPath);
      const mode = (stats.mode & 0o777).toString(8);
      
      if (mode === '600') {
        this.checks.push({
          name: 'File Permissions',
          status: 'ok',
          message: 'Credentials secured (600)',
          detail: credentialsPath,
        });
      } else {
        this.checks.push({
          name: 'File Permissions',
          status: 'warn',
          message: `Credentials file has mode ${mode}`,
          detail: `Expected 600, got ${mode}. Run: chmod 600 ${credentialsPath}`,
        });
      }
    } catch {
      // Ignore errors
    }
  }

  private printResults(): void {
    let hasErrors = false;
    let hasWarnings = false;

    for (const check of this.checks) {
      let statusIcon: string;
      let statusColor: (s: string) => string;
      
      switch (check.status) {
        case 'ok':
          statusIcon = '✓';
          statusColor = chalk.green;
          break;
        case 'warn':
          statusIcon = '⚠';
          statusColor = chalk.yellow;
          hasWarnings = true;
          break;
        case 'error':
          statusIcon = '✗';
          statusColor = chalk.red;
          hasErrors = true;
          break;
        case 'skip':
          statusIcon = '○';
          statusColor = chalk.gray;
          break;
        default:
          statusIcon = '?';
          statusColor = chalk.white;
      }

      console.log(`${statusColor(statusIcon)} ${chalk.bold(check.name)}`);
      console.log(`  ${check.message}`);
      if (check.detail) {
        console.log(chalk.gray(`  ${check.detail}`));
      }
      console.log('');
    }

    console.log(chalk.gray('─'.repeat(50)));

    if (hasErrors) {
      console.log(chalk.red('\n❌ Some checks failed. Run "saferun setup" to fix.\n'));
      process.exitCode = 1;
    } else if (hasWarnings) {
      console.log(chalk.yellow('\n⚠️  Some warnings. Protection may be incomplete.\n'));
    } else {
      console.log(chalk.green('\n✅ All systems operational!\n'));
    }
  }

  private async fetchWithTimeout(url: string, timeout: number): Promise<Response> {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeout);
    
    try {
      const response = await fetch(url, { signal: controller.signal });
      clearTimeout(timeoutId);
      return response;
    } catch (err) {
      clearTimeout(timeoutId);
      throw err;
    }
  }
}
