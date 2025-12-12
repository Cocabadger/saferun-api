/**
 * SafeRun Setup Wizard
 * Complete onboarding in one command: API Key → Slack → GitHub App → Repo Setup
 */

import chalk from 'chalk';
import inquirer from 'inquirer';
import { exec } from 'child_process';
import { promisify } from 'util';
import path from 'path';
import fs from 'fs';
import os from 'os';

import { getGitInfo, isGitRepository } from '../utils/git';
import { loadConfig, saveConfig, SafeRunConfig, ProtectionMode } from '../utils/config';
import { installHooks } from '../hooks/installer';
import {
  loadGlobalCredentials,
  saveGlobalCredentials,
  hasApiKey,
  isValidApiKeyFormat,
  maskApiKey,
  getGlobalConfigDir,
  resolveApiKey,
} from '../utils/credentials';
import { checkGitignore, addToGitignore } from '../utils/gitignore';

const execAsync = promisify(exec);

const SAFERUN_DASHBOARD_URL = 'https://saferun-landing.vercel.app';
const SAFERUN_API_URL = 'https://saferun-api.up.railway.app';
const SLACK_APP_URL = 'https://api.slack.com/apps';
const GITHUB_APP_URL = 'https://github.com/apps/saferun-ai/installations/new';

interface SetupOptions {
  skipSlack?: boolean;
  skipGithub?: boolean;
  apiKey?: string;
}

export class SetupCommand {
  private apiKey?: string;
  private slackConfigured = false;
  private githubAppInstalled = false;
  private repoInitialized = false;
  private shellWrapperConfigured = false;
  private protectionMode: string = 'block';

  async run(options: SetupOptions = {}): Promise<void> {
    console.log(chalk.cyan('\n🛡️  SafeRun Setup Wizard\n'));
    console.log(chalk.gray('This wizard will help you set up complete SafeRun protection.\n'));

    // Step 1: API Key
    await this.stepApiKey(options.apiKey);
    if (!this.apiKey) {
      console.log(chalk.red('\n❌ Setup cancelled: API key is required.\n'));
      process.exitCode = 1;
      return;
    }

    // Step 2: Slack (required for alerts)
    if (!options.skipSlack) {
      await this.stepSlack();
    } else {
      console.log(chalk.yellow('\n⚠️  Skipping Slack setup (--skip-slack)\n'));
    }

    // Step 3: GitHub App (optional but recommended)
    if (!options.skipGithub) {
      await this.stepGitHubApp();
    } else {
      console.log(chalk.yellow('\n⚠️  Skipping GitHub App setup (--skip-github)\n'));
    }

    // Step 4: Repository Setup (if in a git repo)
    await this.stepRepoSetup();

    // Step 5: Shell Wrapper (extra protection)
    await this.stepShellWrapper();

    // Step 6: Protection Mode
    await this.stepProtectionMode();

    // Summary
    this.printSummary();
  }

  /**
   * Step 1: Configure API Key
   */
  private async stepApiKey(providedKey?: string): Promise<void> {
    console.log(chalk.bold('Step 1/6: API Key'));
    console.log(chalk.gray('─'.repeat(40)));

    // Check if already configured
    const existingKey = await resolveApiKey();
    if (existingKey) {
      console.log(chalk.green(`✓ API key already configured: ${maskApiKey(existingKey)}`));
      
      const { useExisting } = await inquirer.prompt([{
        type: 'confirm',
        name: 'useExisting',
        message: 'Use existing API key?',
        default: true,
      }]);

      if (useExisting) {
        this.apiKey = existingKey;
        console.log('');
        return;
      }
    }

    // If key provided via flag
    if (providedKey) {
      if (isValidApiKeyFormat(providedKey)) {
        await saveGlobalCredentials({ api_key: providedKey });
        this.apiKey = providedKey;
        console.log(chalk.green(`✓ API key saved to ${getGlobalConfigDir()}/credentials`));
        console.log('');
        return;
      } else {
        console.log(chalk.yellow('⚠️  Provided API key has invalid format (should start with sr_)'));
      }
    }

    // Interactive prompt
    console.log(chalk.cyan('\n📋 How to get your API key:\n'));
    console.log('  1. Go to ' + chalk.bold('saferun.dev') + ' (or saferun-landing.vercel.app)');
    console.log('  2. Sign up with GitHub or email');
    console.log('  3. Copy your API key from the dashboard');
    console.log(chalk.gray('     (starts with "sr_...")\n'));

    const { openDashboard } = await inquirer.prompt([{
      type: 'confirm',
      name: 'openDashboard',
      message: 'Open SafeRun website in browser?',
      default: true,
    }]);

    if (openDashboard) {
      await this.openBrowser(SAFERUN_DASHBOARD_URL);
      console.log(chalk.gray('\n✓ Browser opened. Copy your API key after signing up.\n'));
    }

    const { apiKey } = await inquirer.prompt([{
      type: 'password',
      name: 'apiKey',
      message: 'Enter your SafeRun API key:',
      mask: '*',
      validate: (value: string) => {
        if (!value) return 'API key is required';
        if (!isValidApiKeyFormat(value)) {
          return 'Invalid format. API key should start with "sr_" and be at least 20 characters.';
        }
        return true;
      },
    }]);

    // Validate with API
    const isValid = await this.validateApiKey(apiKey);
    if (!isValid) {
      console.log(chalk.red('❌ API key validation failed. Please check your key and try again.'));
      return;
    }

    // Save globally
    await saveGlobalCredentials({ api_key: apiKey });
    this.apiKey = apiKey;
    
    console.log(chalk.green(`\n✓ API key saved to ${getGlobalConfigDir()}/credentials (chmod 600)`));
    console.log('');
  }

  /**
   * Step 2: Configure Slack notifications
   */
  private async stepSlack(): Promise<void> {
    console.log(chalk.bold('\nStep 2/6: Slack Notifications'));
    console.log(chalk.gray('─'.repeat(40)));
    console.log(chalk.yellow('⚠️  Slack is REQUIRED for security alerts (force push, branch delete, etc.)\n'));

    // Check if already configured
    const slackStatus = await this.checkSlackStatus();
    if (slackStatus.configured) {
      console.log(chalk.green(`✓ Slack already configured: ${slackStatus.channel || 'webhook'}`));
      this.slackConfigured = true;
      
      const { reconfigure } = await inquirer.prompt([{
        type: 'confirm',
        name: 'reconfigure',
        message: 'Reconfigure Slack?',
        default: false,
      }]);

      if (!reconfigure) {
        console.log('');
        return;
      }
    }

    const { method } = await inquirer.prompt([{
      type: 'list',
      name: 'method',
      message: 'Choose Slack setup method:',
      choices: [
        { name: '🔗 Open browser to create Slack App (recommended)', value: 'browser' },
        { name: '📝 Enter existing tokens', value: 'manual' },
        { name: '⏭️  Skip for now (⚠️ you won\'t receive alerts!)', value: 'skip' },
      ],
    }]);

    if (method === 'skip') {
      console.log(chalk.yellow('\n⚠️  Skipping Slack. You won\'t receive security alerts!'));
      console.log(chalk.gray('   Run "saferun config slack" later to configure.\n'));
      return;
    }

    if (method === 'browser') {
      console.log(chalk.cyan('\n📋 How to create Slack App:\n'));
      console.log('  1. Click ' + chalk.bold('"Create New App"') + ' → "From scratch"');
      console.log('  2. Name it ' + chalk.bold('"SafeRun"') + ' and select your workspace');
      console.log('');
      console.log(chalk.bold('  To get Bot Token:'));
      console.log('  3. Go to ' + chalk.bold('"OAuth & Permissions"') + ' in left menu');
      console.log('  4. Scroll to ' + chalk.bold('"Scopes"') + ' → Add Bot Token Scopes:');
      console.log(chalk.gray('     • chat:write (send messages)'));
      console.log(chalk.gray('     • chat:write.public (post to any channel)'));
      console.log('  5. Click ' + chalk.bold('"Install to Workspace"') + ' at top');
      console.log('  6. Copy ' + chalk.bold('"Bot User OAuth Token"') + ' (starts with xoxb-)');
      console.log('');
      console.log(chalk.bold('  To get Webhook URL (optional but recommended):'));
      console.log('  7. Go to ' + chalk.bold('"Incoming Webhooks"') + ' in left menu');
      console.log('  8. Toggle ON, click "Add New Webhook to Workspace"');
      console.log('  9. Select channel (e.g., #saferun-alerts)');
      console.log('  10. Copy the webhook URL');
      console.log('');
      
      await this.openBrowser(SLACK_APP_URL);
    }

    // Bot Token (required)
    console.log(chalk.cyan('\n📋 Bot Token is REQUIRED to send notifications\n'));
    const { botToken } = await inquirer.prompt([{
      type: 'password',
      name: 'botToken',
      message: 'Paste your Bot User OAuth Token (xoxb-...):',
      mask: '*',
      validate: (value: string) => {
        if (!value) return 'Bot Token is required';
        if (!value.startsWith('xoxb-')) {
          return 'Invalid token. Bot Token should start with xoxb-';
        }
        return true;
      },
    }]);

    // Channel
    const { channel } = await inquirer.prompt([{
      type: 'input',
      name: 'channel',
      message: 'Slack channel for alerts:',
      default: '#saferun-alerts',
      validate: (value: string) => {
        if (!value.startsWith('#') && !value.startsWith('@')) {
          return 'Channel should start with # or @';
        }
        return true;
      },
    }]);

    // Webhook URL (optional)
    const { useWebhook } = await inquirer.prompt([{
      type: 'confirm',
      name: 'useWebhook',
      message: 'Do you also have a Webhook URL? (optional, for backup)',
      default: false,
    }]);

    let webhookUrl = '';
    if (useWebhook) {
      const response = await inquirer.prompt([{
        type: 'input',
        name: 'webhookUrl',
        message: 'Paste your Slack webhook URL:',
        validate: (value: string) => {
          if (value && !value.startsWith('https://hooks.slack.com/')) {
            return 'Invalid URL. Should start with https://hooks.slack.com/';
          }
          return true;
        },
      }]);
      webhookUrl = response.webhookUrl;
    }

    // Configure via API
    const success = await this.configureSlack(botToken, channel, webhookUrl);
    if (success) {
      console.log(chalk.green('\n✓ Slack configured!'));
      console.log(chalk.gray('  Test by triggering a SafeRun operation (e.g., git push --force)'));
      
      this.slackConfigured = true;
    } else {
      console.log(chalk.red('\n❌ Failed to configure Slack. Run "saferun config slack" to try again.'));
    }
    
    console.log('');
  }

  /**
   * Step 3: Install GitHub App
   */
  private async stepGitHubApp(): Promise<void> {
    console.log(chalk.bold('\nStep 3/6: GitHub App'));
    console.log(chalk.gray('─'.repeat(40)));
    
    console.log(chalk.cyan('\n📋 Why GitHub App?\n'));
    console.log('  GitHub App catches dangerous operations that bypass CLI:');
    console.log('  • Force pushes made directly on GitHub');
    console.log('  • Branch deletions via GitHub UI');
    console.log('  • Changes from other machines without SafeRun\n');

    const { install } = await inquirer.prompt([{
      type: 'list',
      name: 'install',
      message: 'Install SafeRun GitHub App?',
      choices: [
        { name: '✅ Yes, open browser to install', value: 'yes' },
        { name: '⏭️  Skip (CLI protection only)', value: 'skip' },
        { name: '✓ Already installed', value: 'done' },
      ],
    }]);

    if (install === 'skip') {
      console.log(chalk.yellow('\n⚠️  Skipping GitHub App. Webhook protection won\'t be active.'));
      console.log(chalk.gray('   Install later at: ' + GITHUB_APP_URL + '\n'));
      return;
    }

    if (install === 'done') {
      this.githubAppInstalled = true;
      console.log(chalk.green('\n✓ GitHub App marked as installed.\n'));
      return;
    }

    console.log(chalk.cyan('\n📋 How to install GitHub App:\n'));
    console.log('  1. Click "Install" on the GitHub page');
    console.log('  2. Select your account or organization');
    console.log('  3. Choose "All repositories" or select specific ones');
    console.log('  4. Click "Install" to confirm\n');

    await this.openBrowser(GITHUB_APP_URL);

    const { installed } = await inquirer.prompt([{
      type: 'confirm',
      name: 'installed',
      message: 'Did you complete the GitHub App installation?',
      default: true,
    }]);

    if (installed) {
      this.githubAppInstalled = true;
      console.log(chalk.green('\n✓ GitHub App installed!\n'));
    }
  }

  /**
   * Step 4: Initialize repository
   */
  private async stepRepoSetup(): Promise<void> {
    console.log(chalk.bold('\nStep 4/6: Repository Setup'));
    console.log(chalk.gray('─'.repeat(40)));

    const isRepo = await isGitRepository();
    if (!isRepo) {
      console.log(chalk.yellow('⚠️  Not inside a git repository.'));
      console.log(chalk.gray('   Navigate to a repo and run "saferun init" to set up protection.\n'));
      return;
    }

    const gitInfo = await getGitInfo();
    if (!gitInfo) {
      console.log(chalk.red('❌ Could not determine git repository info.\n'));
      return;
    }

    console.log(chalk.gray(`Repository: ${gitInfo.repoSlug || gitInfo.repoRoot}\n`));

    const { initialize } = await inquirer.prompt([{
      type: 'confirm',
      name: 'initialize',
      message: `Initialize SafeRun in this repository?`,
      default: true,
    }]);

    if (!initialize) {
      console.log(chalk.gray('\n   Run "saferun init" later to initialize.\n'));
      return;
    }

    // Install hooks
    console.log(chalk.gray('\nInstalling git hooks...'));
    try {
      const hooksResult = await installHooks({ 
        repoRoot: gitInfo.repoRoot, 
        gitDir: gitInfo.gitDir 
      });
      console.log(chalk.green(`✓ ${hooksResult.installed.length} hooks installed`));
    } catch (err) {
      console.log(chalk.red(`❌ Failed to install hooks: ${err}`));
    }

    // Check/update .gitignore
    console.log(chalk.gray('\nChecking .gitignore...'));
    const gitignoreCheck = await checkGitignore(gitInfo.repoRoot);
    
    if (!gitignoreCheck.hasSaferunEntries) {
      console.log(chalk.yellow(`⚠️  SafeRun entries not in .gitignore`));
      
      if (gitignoreCheck.missingEntries.length > 0) {
        console.log(chalk.gray('   Missing entries:'));
        for (const entry of gitignoreCheck.missingEntries.slice(0, 3)) {
          console.log(chalk.gray(`     • ${entry}`));
        }
        if (gitignoreCheck.missingEntries.length > 3) {
          console.log(chalk.gray(`     • ... and ${gitignoreCheck.missingEntries.length - 3} more`));
        }
      }

      const { updateGitignore } = await inquirer.prompt([{
        type: 'confirm',
        name: 'updateGitignore',
        message: 'Add SafeRun entries to .gitignore?',
        default: true,
      }]);

      if (updateGitignore) {
        await addToGitignore(gitInfo.repoRoot);
        console.log(chalk.green('✓ .gitignore updated'));
      } else {
        console.log(chalk.yellow('⚠️  Please add .saferun/credentials to .gitignore manually!'));
      }
    } else {
      console.log(chalk.green('✓ .gitignore already has SafeRun entries'));
    }

    // Save local config (mode will be set in Step 5)
    console.log(chalk.gray('\nCreating .saferun/config.yml...'));
    let config = await loadConfig(gitInfo.repoRoot, { allowCreate: true });
    
    // Set repo info
    if (gitInfo.repoSlug) {
      config.github.repo = gitInfo.repoSlug;
    }
    if (gitInfo.defaultBranch) {
      const branches = new Set(config.github.protected_branches);
      branches.add(gitInfo.defaultBranch);
      config.github.protected_branches = Array.from(branches);
    }
    
    await saveConfig(config, gitInfo.repoRoot);
    console.log(chalk.green('✓ Config saved'));

    this.repoInitialized = true;
    console.log('');
  }

  /**
   * Step 5: Shell Wrapper
   */
  private async stepShellWrapper(): Promise<void> {
    console.log(chalk.bold('\nStep 5/6: Shell Wrapper'));
    console.log(chalk.gray('─'.repeat(40)));

    console.log(chalk.cyan('\n📋 What is Shell Wrapper?\n'));
    console.log('  Git hooks only run AFTER a command completes.');
    console.log('  Shell Wrapper intercepts commands BEFORE they run!');
    console.log('');
    console.log(chalk.bold('  Commands intercepted:'));
    console.log('    • git push --force  → require approval');
    console.log('    • git reset --hard  → require approval');
    console.log('    • git clean -fd     → require approval');
    console.log('    • git branch -D     → require approval');
    console.log('');

    const { configure } = await inquirer.prompt([{
      type: 'confirm',
      name: 'configure',
      message: 'Enable Shell Wrapper for extra protection?',
      default: true,
    }]);

    if (!configure) {
      console.log(chalk.gray('\n   Run "saferun shell-init --auto" later to configure.\n'));
      return;
    }

    // Run shell-init --auto
    console.log(chalk.gray('\nConfiguring shell integration...'));
    
    try {
      const shell = process.env.SHELL || '/bin/zsh';
      const shellName = path.basename(shell);
      const homeDir = os.homedir();
      
      let rcFile: string;
      if (shellName === 'zsh') {
        rcFile = path.join(homeDir, '.zshrc');
      } else if (shellName === 'bash') {
        rcFile = path.join(homeDir, '.bashrc');
      } else {
        console.log(chalk.yellow(`⚠️  Unsupported shell: ${shellName}`));
        console.log(chalk.gray('   Supported: zsh, bash\n'));
        return;
      }

      // Check if already configured
      const rcContent = fs.existsSync(rcFile) ? fs.readFileSync(rcFile, 'utf-8') : '';
      
      if (rcContent.includes('saferun shell-init')) {
        console.log(chalk.green('✓ Shell Wrapper already configured'));
        this.shellWrapperConfigured = true;
      } else {
        // Add to shell rc file
        const initLine = '\n# SafeRun shell integration\neval "$(saferun shell-init)"\n';
        fs.appendFileSync(rcFile, initLine);
        
        console.log(chalk.green(`✓ Added to ${rcFile}`));
        console.log(chalk.yellow('\n⚠️  Run this to activate in current terminal:'));
        console.log(chalk.cyan(`   source ${rcFile}\n`));
        
        this.shellWrapperConfigured = true;
      }
    } catch (err) {
      console.log(chalk.red(`❌ Failed to configure: ${err}`));
      console.log(chalk.gray('   Run "saferun shell-init --auto" manually.\n'));
    }
  }

  /**
   * Step 6: Select Protection Mode
   */
  private async stepProtectionMode(): Promise<void> {
    console.log(chalk.bold('\nStep 6/6: Protection Mode'));
    console.log(chalk.gray('─'.repeat(40)));

    if (!this.repoInitialized) {
      console.log(chalk.gray('Skipped (repository not initialized)\n'));
      return;
    }

    console.log(chalk.cyan('\n📋 What should SafeRun do when it detects risky operations?\n'));

    const { mode } = await inquirer.prompt([{
      type: 'list',
      name: 'mode',
      message: 'Select protection mode:',
      default: 'block',
      choices: [
        { name: '👀  Monitor — log only, no blocking (for testing)', value: 'monitor' },
        { name: '⚠️   Warn — show warnings, but allow operations', value: 'warn' },
        { name: '🛑  Block — require approval for risky actions (recommended)', value: 'block' },
        { name: '🔒  Enforce — strict blocking, maximum security', value: 'enforce' },
      ],
    }]);

    this.protectionMode = mode;

    // Update config with mode
    const gitInfo = await getGitInfo();
    if (gitInfo) {
      let config = await loadConfig(gitInfo.repoRoot, { allowCreate: false });
      config.mode = mode as ProtectionMode;
      await saveConfig(config, gitInfo.repoRoot);
    }

    console.log(chalk.green(`\n✓ Protection mode set to: ${mode.toUpperCase()}`));
    console.log('');
  }

  /**
   * Print setup summary
   */
  private printSummary(): void {
    console.log(chalk.cyan('\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n'));
    console.log(chalk.bold('🎉 SafeRun Setup Complete!\n'));

    console.log('Your setup:');
    console.log(`  ${this.apiKey ? chalk.green('✓') : chalk.red('✗')} API Key:       ${this.apiKey ? 'configured (global)' : 'not configured'}`);
    console.log(`  ${this.slackConfigured ? chalk.green('✓') : chalk.yellow('⚠')} Slack:         ${this.slackConfigured ? 'connected' : 'not configured'}`);
    console.log(`  ${this.githubAppInstalled ? chalk.green('✓') : chalk.yellow('⚠')} GitHub App:    ${this.githubAppInstalled ? 'installed' : 'not installed'}`);
    console.log(`  ${this.repoInitialized ? chalk.green('✓') : chalk.yellow('⚠')} Repository:    ${this.repoInitialized ? 'hooks installed' : 'skipped (run "saferun init")'}`);
    console.log(`  ${this.shellWrapperConfigured ? chalk.green('✓') : chalk.yellow('⚠')} Shell Wrapper: ${this.shellWrapperConfigured ? 'configured' : 'not configured'}`);
    console.log(`  ${this.repoInitialized ? chalk.green('✓') : chalk.gray('○')} Mode:          ${this.repoInitialized ? this.protectionMode.toUpperCase() : 'not set'}`);

    console.log(chalk.gray('\nNext steps:'));
    
    if (!this.slackConfigured) {
      console.log(chalk.yellow('  • Run "saferun config slack" to configure notifications'));
    }
    if (!this.githubAppInstalled) {
      console.log(chalk.gray(`  • Install GitHub App: ${GITHUB_APP_URL}`));
    }
    if (!this.shellWrapperConfigured) {
      console.log(chalk.gray('  • Run "saferun shell-init --auto" for extra protection'));
    }
    if (this.repoInitialized) {
      console.log(chalk.cyan('  • Test it: git push --force origin main'));
    }
    
    console.log(chalk.gray('\nVerify setup:'));
    console.log(chalk.cyan('  saferun doctor'));
    
    console.log(chalk.gray('\nDocumentation:'));
    console.log(chalk.cyan('  https://saferun.dev/docs\n'));
  }

  // ─────────────────────────────────────────────────────────────────
  // Helper methods
  // ─────────────────────────────────────────────────────────────────

  private async openBrowser(url: string): Promise<void> {
    const platform = os.platform();
    
    try {
      if (platform === 'darwin') {
        await execAsync(`open "${url}"`);
      } else if (platform === 'win32') {
        await execAsync(`start "" "${url}"`);
      } else {
        // Linux
        await execAsync(`xdg-open "${url}"`);
      }
    } catch {
      console.log(chalk.gray(`\nCouldn't open browser. Please visit:\n${chalk.cyan(url)}\n`));
    }
  }

  private async validateApiKey(apiKey: string): Promise<boolean> {
    try {
      // Use an authenticated endpoint to validate the key
      const response = await fetch(`${SAFERUN_API_URL}/v1/settings`, {
        headers: { 'X-API-Key': apiKey },
      });
      // 200 = valid, 401/403 = invalid, 404 = endpoint not found (still valid key format)
      return response.ok || response.status === 404;
    } catch {
      // Network error - assume key is valid if format is correct
      return true;
    }
  }

  private async checkSlackStatus(): Promise<{ configured: boolean; channel?: string }> {
    if (!this.apiKey) return { configured: false };
    
    try {
      const response = await fetch(`${SAFERUN_API_URL}/v1/settings/notifications`, {
        headers: { 'X-API-Key': this.apiKey },
      });
      
      if (response.ok) {
        const data = await response.json();
        return {
          configured: data.slack_enabled === true,
          channel: data.slack_channel,
        };
      }
    } catch {
      // Ignore errors
    }
    
    return { configured: false };
  }

  private async configureSlack(botToken: string, channel: string, webhookUrl?: string): Promise<boolean> {
    if (!this.apiKey) return false;
    
    try {
      const body: Record<string, any> = {
        slack_enabled: true,
        slack_bot_token: botToken,
        slack_channel: channel,
        notification_channels: ['slack'],
      };
      
      if (webhookUrl) {
        body.slack_webhook_url = webhookUrl;
      }

      const response = await fetch(`${SAFERUN_API_URL}/v1/settings/notifications`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          'X-API-Key': this.apiKey,
        },
        body: JSON.stringify(body),
      });
      
      return response.ok;
    } catch {
      return false;
    }
  }

  private async sendTestSlack(): Promise<void> {
    if (!this.apiKey) return;
    
    console.log(chalk.gray('Sending test notification...'));
    
    try {
      const response = await fetch(`${SAFERUN_API_URL}/v1/settings/notifications/test`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-API-Key': this.apiKey,
        },
      });
      
      if (response.ok) {
        console.log(chalk.green('✓ Test notification sent! Check your Slack channel.'));
      } else {
        console.log(chalk.yellow('⚠️  Could not send test notification.'));
      }
    } catch {
      console.log(chalk.yellow('⚠️  Could not send test notification (network error).'));
    }
  }
}
