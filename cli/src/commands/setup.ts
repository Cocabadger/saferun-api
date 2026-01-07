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
import { registerProtectedRepo } from '../utils/protected-repos';
import { loadGlobalConfig, saveGlobalConfig, setGlobalMode } from '../utils/global-config';

const execAsync = promisify(exec);

const SAFERUN_DASHBOARD_URL = 'https://saferun.dev';
const SAFERUN_API_URL = process.env.SAFERUN_API_URL || 'https://saferun-api.up.railway.app';
const SLACK_APP_URL = 'https://api.slack.com/apps';
const GITHUB_APP_URL = 'https://github.com/apps/saferun-ai/installations/new';

interface SetupOptions {
  skipSlack?: boolean;
  skipGithub?: boolean;
  apiKey?: string;
  manual?: boolean;  // Full wizard with all prompts
}

interface UnifiedSetupStatus {
  slack: boolean;
  github: boolean;
  ready: boolean;
}

export class SetupCommand {
  private apiKey?: string;
  private slackConfigured = false;
  private githubAppInstalled = false;
  private repoInitialized = false;
  private shellWrapperConfigured = false;
  private protectionMode: string = 'block';
  private currentSessionState?: string; // OAuth session state for unified polling
  private setupErrors: string[] = []; // Track setup failures
  private hasCriticalError = false; // Blocks "Setup Complete" message

  async run(options: SetupOptions = {}): Promise<void> {
    console.log(chalk.cyan('\n🛡️  SafeRun Setup Wizard\n'));
    
    // Manual mode = full wizard with all prompts
    if (options.manual) {
      console.log(chalk.gray('Running in manual mode (full wizard).\n'));
      await this.runManualWizard(options);
      return;
    }

    // Streamlined setup: minimal prompts, smart defaults
    console.log(chalk.gray('Quick setup with smart defaults. Use --manual for full control.\n'));

    // Step 1: API Key (auto-use existing, or switch via --api-key)
    await this.stepApiKey(options.apiKey);
    if (!this.apiKey) {
      console.log(chalk.red('\n❌ Setup cancelled: API key is required.\n'));
      process.exitCode = 1;
      return;
    }

    // Step 2: Slack OAuth (required)
    if (!options.skipSlack) {
      await this.stepSlackStreamlined();
    }

    // Step 3: GitHub App (auto-install)
    if (!options.skipGithub) {
      await this.stepGitHubAppStreamlined();
    }

    // Step 4: Apply recommended defaults (no prompts)
    await this.applyRecommendedDefaults();

    // Step 5: Auto-verify installation
    await this.verifyInstallation();

    // Summary (or failure report)
    this.printSummary();
  }

  /**
   * Full wizard with all prompts (--manual mode)
   */
  private async runManualWizard(options: SetupOptions): Promise<void> {
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

    // If new key provided via --api-key flag, use it (switch accounts)
    if (providedKey && isValidApiKeyFormat(providedKey)) {
      const existingKey = await resolveApiKey();
      if (existingKey && existingKey !== providedKey) {
        console.log(chalk.yellow(`Switching from: ${maskApiKey(existingKey)}`));
        console.log(chalk.yellow('⚠️  Note: Slack/GitHub will need reconnection for new key\n'));
      }
      await saveGlobalCredentials({ api_key: providedKey });
      this.apiKey = providedKey;
      console.log(chalk.green(`✓ API key saved: ${maskApiKey(providedKey)}`));
      console.log('');
      return;
    }

    // Check if already configured - use it automatically
    const existingKey = await resolveApiKey();
    if (existingKey) {
      console.log(chalk.green(`✓ Using API key: ${maskApiKey(existingKey)} (from ~/.saferun/credentials)`));
      this.apiKey = existingKey;
      console.log('');
      return;
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
    console.log('  1. Go to ' + chalk.bold('saferun.dev'));
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
   * Streamlined Slack setup - minimal prompts
   */
  private async stepSlackStreamlined(): Promise<void> {
    console.log(chalk.bold('\n☁️  Connecting Slack...'));
    
    const slackStatus = await this.checkSlackStatus();
    
    if (slackStatus.valid === false) {
      console.log(chalk.yellow(`   ⚠️  Previous connection expired. Reconnecting...`));
    } else if (slackStatus.configured) {
      console.log(chalk.green(`   ✓ Slack connected: ${slackStatus.teamName || 'configured'}`));
      this.slackConfigured = true;
      return;
    }

    // Auto-open OAuth
    const oauthUrl = await this.getSlackOAuthUrl();
    if (!oauthUrl) {
      console.log(chalk.red('   ❌ Failed to get authorization URL.'));
      return;
    }

    console.log(chalk.gray('   Opening browser for Slack authorization...'));
    await this.openBrowser(oauthUrl);
    
    console.log(chalk.yellow('   ⏳ Waiting for Slack authorization...'));
    const connected = await this.pollSlackConnection();
    
    if (connected) {
      console.log(chalk.green('   ✓ Slack connected!'));
      this.slackConfigured = true;
    } else {
      console.log(chalk.yellow('   ⚠️  Slack connection timed out. Run setup again to retry.'));
    }
  }

  /**
   * Streamlined GitHub App setup - minimal prompts
   */
  private async stepGitHubAppStreamlined(): Promise<void> {
    console.log(chalk.bold('\n☁️  Connecting GitHub App...'));
    
    const githubStatus = await this.checkGitHubStatus();
    
    if (githubStatus.valid === false) {
      console.log(chalk.yellow(`   ⚠️  Previous installation removed. Reinstalling...`));
    } else if (githubStatus.installed) {
      console.log(chalk.green(`   ✓ GitHub App installed: ${githubStatus.accountLogin || 'configured'}`));
      this.githubAppInstalled = true;
      return;
    }

    // Auto-open GitHub App install
    let githubInstallUrl = GITHUB_APP_URL;
    if (this.currentSessionState) {
      githubInstallUrl = `${GITHUB_APP_URL}?state=${this.currentSessionState}`;
    }

    console.log(chalk.gray('   Opening browser for GitHub App installation...'));
    await this.openBrowser(githubInstallUrl);
    
    if (this.currentSessionState) {
      console.log(chalk.yellow('   ⏳ Waiting for GitHub App installation...'));
      const status = await this.pollUnifiedSetup(120000); // 2 min
      
      if (status.github) {
        console.log(chalk.green('   ✓ GitHub App installed!'));
        this.githubAppInstalled = true;
      } else {
        console.log(chalk.yellow('   ⚠️  GitHub App not detected. You can install later.'));
      }
    } else {
      console.log(chalk.gray('   Complete installation in browser, then run setup again.'));
    }
  }

  /**
   * Apply recommended security defaults (no prompts)
   * STRICT MODE: Errors are tracked, not silently ignored
   */
  private async applyRecommendedDefaults(): Promise<void> {
    console.log(chalk.bold('\n🔧 Applying recommended security defaults...\n'));
    
    const isRepo = await isGitRepository();
    
    if (isRepo) {
      const gitInfo = await getGitInfo();
      
      if (gitInfo) {
        // Install hooks - CRITICAL: must succeed
        try {
          const hooksResult = await installHooks({ 
            repoRoot: gitInfo.repoRoot, 
            gitDir: gitInfo.gitDir 
          });
          console.log(chalk.green(`   ✓ ${hooksResult.installed.length} git hooks installed`));
          this.repoInitialized = true;
        } catch (err) {
          const errorMsg = `Failed to install git hooks: ${err}`;
          console.log(chalk.red(`   ✗ ${errorMsg}`));
          this.setupErrors.push(errorMsg);
          this.hasCriticalError = true; // Hooks are critical for protection
        }

        // Add to .gitignore
        try {
          const gitignoreCheck = await checkGitignore(gitInfo.repoRoot);
          if (!gitignoreCheck.hasSaferunEntries) {
            await addToGitignore(gitInfo.repoRoot);
            console.log(chalk.green('   ✓ Added .saferun to .gitignore'));
          } else {
            console.log(chalk.green('   ✓ .gitignore already configured'));
          }
        } catch (err) {
          console.log(chalk.yellow(`   ⚠️  Could not update .gitignore: ${err}`));
          this.setupErrors.push(`gitignore: ${err}`);
        }

        // Register repo with BLOCK mode
        try {
          await registerProtectedRepo(gitInfo.repoRoot, { 
            name: gitInfo.repoSlug || undefined,
            mode: 'block',
          });
          this.protectionMode = 'block';
          console.log(chalk.green('   ✓ Protection mode: BLOCK (safest)'));
        } catch (err) {
          console.log(chalk.yellow(`   ⚠️  Could not register repo: ${err}`));
          this.setupErrors.push(`repo registration: ${err}`);
        }
      }
    } else {
      console.log(chalk.gray('   (Not in a git repository - skipping local setup)'));
    }

    // Set global mode to block
    try {
      await setGlobalMode('block');
      this.protectionMode = 'block';
    } catch (err) {
      this.setupErrors.push(`global mode: ${err}`);
    }

    // Configure shell wrapper automatically
    try {
      const shell = process.env.SHELL || '/bin/zsh';
      const shellName = path.basename(shell);
      const homeDir = os.homedir();
      
      let rcFile: string | null = null;
      if (shellName === 'zsh') {
        rcFile = path.join(homeDir, '.zshrc');
      } else if (shellName === 'bash') {
        rcFile = path.join(homeDir, '.bashrc');
      }

      if (rcFile) {
        const rcContent = fs.existsSync(rcFile) ? fs.readFileSync(rcFile, 'utf-8') : '';
        
        if (rcContent.includes('saferun shell-init')) {
          console.log(chalk.green('   ✓ Shell wrapper already configured'));
          this.shellWrapperConfigured = true;
        } else {
          const initLine = '\n# SafeRun shell integration\neval "$(saferun shell-init)"\n';
          fs.appendFileSync(rcFile, initLine);
          console.log(chalk.green(`   ✓ Shell wrapper added to ${rcFile}`));
          console.log(chalk.yellow(`     Run: source ${rcFile}`));
          this.shellWrapperConfigured = true;
        }
      } else {
        console.log(chalk.yellow(`   ⚠️  Unsupported shell: ${shellName}`));
        this.setupErrors.push(`Unsupported shell: ${shellName}`);
      }
    } catch (err) {
      const errorMsg = `Failed to configure shell wrapper: ${err}`;
      console.log(chalk.red(`   ✗ ${errorMsg}`));
      this.setupErrors.push(errorMsg);
    }

    console.log('');
  }

  /**
   * Verify installation by checking hooks exist on disk
   */
  private async verifyInstallation(): Promise<void> {
    if (!this.repoInitialized) return;
    
    const gitInfo = await getGitInfo();
    if (!gitInfo) return;

    console.log(chalk.gray('Verifying installation...'));
    
    // Check that at least pre-push hook exists
    const prePushHook = path.join(gitInfo.gitDir, 'hooks', 'pre-push');
    if (!fs.existsSync(prePushHook)) {
      const errorMsg = 'pre-push hook not found on disk after installation';
      console.log(chalk.red(`   ✗ ${errorMsg}`));
      this.setupErrors.push(errorMsg);
      this.hasCriticalError = true;
      this.repoInitialized = false;
    } else {
      // Check hook contains saferun
      const hookContent = fs.readFileSync(prePushHook, 'utf-8');
      if (!hookContent.includes('saferun')) {
        const errorMsg = 'pre-push hook exists but does not contain SafeRun';
        console.log(chalk.red(`   ✗ ${errorMsg}`));
        this.setupErrors.push(errorMsg);
        this.hasCriticalError = true;
        this.repoInitialized = false;
      } else {
        console.log(chalk.green('   ✓ Hooks verified on disk\n'));
      }
    }
  }

  /**
   * Step 2: Configure Slack notifications via OAuth (manual mode)
   */
  private async stepSlack(): Promise<void> {
    console.log(chalk.bold('\nStep 2/6: Slack Notifications'));
    console.log(chalk.gray('─'.repeat(40)));
    console.log(chalk.yellow('⚠️  Slack is REQUIRED for security alerts (force push, branch delete, etc.)\n'));

    // Check if already configured via OAuth (with token validation)
    const slackStatus = await this.checkSlackStatus();
    
    // Handle case where token was revoked (app removed from Slack)
    if (slackStatus.valid === false) {
      console.log(chalk.yellow(`⚠️  Slack was connected (${slackStatus.teamName}) but the app was removed.`));
      console.log(chalk.gray('   You need to reconnect to receive notifications.\n'));
      // Don't set slackConfigured, proceed to OAuth
    } else if (slackStatus.configured) {
      console.log(chalk.green(`✓ Slack already connected: ${slackStatus.teamName || slackStatus.channel || 'configured'}`));
      this.slackConfigured = true;
      
      const { reconfigure } = await inquirer.prompt([{
        type: 'confirm',
        name: 'reconfigure',
        message: 'Reconnect Slack?',
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
      message: 'Connect Slack:',
      choices: [
        { name: '🔗 Add to Slack (recommended, one-click setup)', value: 'oauth' },
        { name: '⏭️  Skip for now (⚠️ you won\'t receive alerts!)', value: 'skip' },
      ],
    }]);

    if (method === 'skip') {
      console.log(chalk.yellow('\n⚠️  Skipping Slack. You won\'t receive security alerts!'));
      console.log(chalk.gray('   Run "saferun setup" later to connect.\n'));
      return;
    }

    // OAuth flow
    console.log(chalk.cyan('\n📋 Connecting Slack via OAuth:\n'));
    console.log('  1. Browser will open Slack authorization page');
    console.log('  2. Click ' + chalk.bold('"Allow"') + ' to grant SafeRun access');
    console.log('  3. You\'ll see "Slack Connected!" confirmation');
    console.log('');

    // Get OAuth URL from backend
    const oauthUrl = await this.getSlackOAuthUrl();
    if (!oauthUrl) {
      console.log(chalk.red('❌ Failed to get authorization URL. Please try again later.'));
      return;
    }

    const { openBrowser } = await inquirer.prompt([{
      type: 'confirm',
      name: 'openBrowser',
      message: 'Open Slack authorization in browser?',
      default: true,
    }]);

    if (openBrowser) {
      await this.openBrowser(oauthUrl);
    } else {
      console.log(chalk.cyan('\nOpen this URL manually:'));
      console.log(chalk.bold(oauthUrl) + '\n');
    }

    console.log(chalk.yellow('\n⏳ Waiting for Slack authorization...'));
    console.log(chalk.gray('   (Press Ctrl+C to cancel)\n'));

    // Poll for completion
    const connected = await this.pollSlackConnection();
    
    if (connected) {
      console.log(chalk.green('\n✓ Slack connected successfully!'));
      console.log(chalk.gray('  Notifications will be sent to your Slack workspace.'));
      this.slackConfigured = true;
    } else {
      console.log(chalk.yellow('\n⚠️  Slack connection timed out.'));
      console.log(chalk.gray('   Run "saferun setup" again to retry.'));
    }
    
    console.log('');
  }

  /**
   * Step 3: Install GitHub App (with unified polling)
   */
  private async stepGitHubApp(): Promise<void> {
    console.log(chalk.bold('\nStep 3/6: GitHub App'));
    console.log(chalk.gray('─'.repeat(40)));
    
    console.log(chalk.cyan('\n📋 Why GitHub App?\n'));
    console.log('  GitHub App catches dangerous operations that bypass CLI:');
    console.log('  • Force pushes made directly on GitHub');
    console.log('  • Branch deletions via GitHub UI');
    console.log('  • Changes from other machines without SafeRun\n');

    // Check if already installed (with validation)
    const githubStatus = await this.checkGitHubStatus();
    
    // Handle case where app was uninstalled from GitHub
    if (githubStatus.valid === false) {
      console.log(chalk.yellow(`⚠️  GitHub App was installed (${githubStatus.accountLogin}) but has been removed.`));
      console.log(chalk.gray('   You need to reinstall to enable webhook protection.\n'));
      // Don't set githubAppInstalled, proceed to installation
    } else if (githubStatus.installed) {
      console.log(chalk.green(`✓ GitHub App already installed: ${githubStatus.accountLogin || 'configured'}`));
      this.githubAppInstalled = true;
      
      const { reinstall } = await inquirer.prompt([{
        type: 'confirm',
        name: 'reinstall',
        message: 'Reinstall GitHub App?',
        default: false,
      }]);

      if (!reinstall) {
        console.log('');
        return;
      }
    }

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

    // Build GitHub App URL with state parameter for linking
    let githubInstallUrl = GITHUB_APP_URL;
    if (this.currentSessionState) {
      githubInstallUrl = `${GITHUB_APP_URL}?state=${this.currentSessionState}`;
    }
    
    await this.openBrowser(githubInstallUrl);

    // If we have a session state, use unified polling
    if (this.currentSessionState) {
      console.log(chalk.yellow('\n⏳ Waiting for GitHub App installation...'));
      console.log(chalk.gray('   (This will auto-detect when installation completes)'));
      console.log(chalk.gray('   (Press Ctrl+C to cancel)\n'));
      
      const status = await this.pollUnifiedSetup(180000); // 3 minutes timeout
      
      if (status.github) {
        console.log(chalk.green('\n✓ GitHub App linked to your SafeRun account!'));
        this.githubAppInstalled = true;
      } else {
        console.log(chalk.yellow('\n⚠️  GitHub App installation not detected.'));
        console.log(chalk.gray('   This could mean the callback URL is not configured in GitHub App settings.'));
        console.log(chalk.gray('   Check: https://github.com/settings/apps/saferun-ai → Setup URL\n'));
        
        const { installed } = await inquirer.prompt([{
          type: 'confirm',
          name: 'installed',
          message: 'Did you complete the GitHub App installation?',
          default: false,  // Changed to false - user must explicitly confirm
        }]);
        
        if (installed) {
          this.githubAppInstalled = true;
          console.log(chalk.yellow('   Note: Webhook protection may not work until callback is properly configured.'));
        }
      }
    } else {
      // Fallback to manual confirmation (no session state)
      const { installed } = await inquirer.prompt([{
        type: 'confirm',
        name: 'installed',
        message: 'Did you complete the GitHub App installation?',
        default: false,  // Changed to false - user must explicitly confirm
      }]);

      if (installed) {
        this.githubAppInstalled = true;
        console.log(chalk.green('\n✓ GitHub App installed!\n'));
      }
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

    // Register repo in global protected-repos registry
    console.log(chalk.gray('\nRegistering repository...'));
    await registerProtectedRepo(gitInfo.repoRoot, { name: gitInfo.repoSlug || undefined });
    console.log(chalk.green('✓ Repository registered in global registry'));

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

    // Save mode to GLOBAL config (not local - prevents rollback on git reset)
    const globalConfig = await loadGlobalConfig();
    globalConfig.mode = mode;
    await saveGlobalConfig(globalConfig);

    console.log(chalk.green(`\n✓ Protection mode set to: ${mode.toUpperCase()}`));
    console.log(chalk.gray('   Saved to ~/.saferun/config.yml (global)'));
    console.log('');
  }

  /**
   * Print setup summary - shows errors if any critical failures
   */
  private printSummary(): void {
    console.log(chalk.cyan('\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n'));
    
    // If critical error occurred, show failure message
    if (this.hasCriticalError) {
      console.log(chalk.red.bold('❌ SafeRun Setup FAILED\n'));
      console.log(chalk.red('Critical errors occurred during setup:\n'));
      for (const error of this.setupErrors) {
        console.log(chalk.red(`  • ${error}`));
      }
      console.log(chalk.yellow('\n⚠️  Your repository is NOT protected!'));
      console.log(chalk.gray('\nTry running with --manual flag for step-by-step troubleshooting:'));
      console.log(chalk.cyan('  saferun setup --manual\n'));
      process.exitCode = 1;
      return;
    }

    console.log(chalk.bold('🎉 SafeRun Setup Complete!\n'));

    console.log('Your setup:');
    console.log(`  ${this.apiKey ? chalk.green('✓') : chalk.red('✗')} API Key:       ${this.apiKey ? 'configured (global)' : 'not configured'}`);
    console.log(`  ${this.slackConfigured ? chalk.green('✓') : chalk.yellow('⚠')} Slack:         ${this.slackConfigured ? 'connected' : 'not configured'}`);
    console.log(`  ${this.githubAppInstalled ? chalk.green('✓') : chalk.yellow('⚠')} GitHub App:    ${this.githubAppInstalled ? 'installed' : 'not installed'}`);
    console.log(`  ${this.repoInitialized ? chalk.green('✓') : chalk.yellow('⚠')} Repository:    ${this.repoInitialized ? 'hooks installed' : 'skipped (run "saferun init")'}`);
    console.log(`  ${this.shellWrapperConfigured ? chalk.green('✓') : chalk.yellow('⚠')} Shell Wrapper: ${this.shellWrapperConfigured ? 'configured' : 'not configured'}`);
    console.log(`  ${this.protectionMode ? chalk.green('✓') : chalk.gray('○')} Mode:          ${this.protectionMode ? this.protectionMode.toUpperCase() : 'not set'}`);

    // Show non-critical warnings if any
    if (this.setupErrors.length > 0 && !this.hasCriticalError) {
      console.log(chalk.yellow('\nWarnings:'));
      for (const error of this.setupErrors) {
        console.log(chalk.yellow(`  ⚠️  ${error}`));
      }
    }

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

  private async checkSlackStatus(): Promise<{ configured: boolean; channel?: string; teamName?: string; valid?: boolean }> {
    if (!this.apiKey) return { configured: false };
    
    try {
      // Check OAuth installation first, with validation to ensure token is still active
      const response = await fetch(`${SAFERUN_API_URL}/auth/slack/status?validate=true`, {
        headers: { 'X-API-Key': this.apiKey },
      });
      
      if (response.ok) {
        const data = await response.json();
        // Check both connected AND valid (token not revoked)
        if (data.connected && data.valid !== false) {
          return {
            configured: true,
            teamName: data.team_name,
            channel: data.channel_id,
            valid: data.valid,
          };
        }
      }
      
      // Fallback: check legacy notification settings
      const legacyResponse = await fetch(`${SAFERUN_API_URL}/v1/settings/notifications`, {
        headers: { 'X-API-Key': this.apiKey },
      });
      
      if (legacyResponse.ok) {
        const data = await legacyResponse.json();
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

  /**
   * Check if GitHub App is installed for this API key (with optional token validation)
   */
  private async checkGitHubStatus(): Promise<{ installed: boolean; accountLogin?: string; valid?: boolean }> {
    if (!this.apiKey) return { installed: false };
    
    try {
      const response = await fetch(`${SAFERUN_API_URL}/auth/github/status?validate=true`, {
        headers: { 'X-API-Key': this.apiKey },
      });
      
      if (response.ok) {
        const data = await response.json();
        if (data.installed && data.valid !== false) {
          return {
            installed: true,
            accountLogin: data.account_login,
            valid: data.valid,
          };
        }
        // Installation was removed
        if (data.valid === false) {
          return {
            installed: false,
            accountLogin: data.account_login,
            valid: false,
          };
        }
      }
    } catch {
      // Ignore errors
    }
    
    return { installed: false };
  }

  /**
   * Get OAuth URL from backend (also stores session state for unified polling)
   */
  private async getSlackOAuthUrl(): Promise<string | null> {
    if (!this.apiKey) return null;
    
    try {
      const response = await fetch(`${SAFERUN_API_URL}/auth/slack/session`, {
        method: 'POST',
        headers: { 'X-API-Key': this.apiKey },
      });
      
      if (response.ok) {
        const data = await response.json();
        // Store session state for unified polling
        if (data.state) {
          this.currentSessionState = data.state;
        }
        return data.url;
      }
    } catch {
      // Ignore errors
    }
    
    return null;
  }

  /**
   * Poll for Slack OAuth completion
   */
  private async pollSlackConnection(timeoutMs: number = 120000): Promise<boolean> {
    const startTime = Date.now();
    const pollInterval = 2000; // 2 seconds
    
    while (Date.now() - startTime < timeoutMs) {
      try {
        const response = await fetch(`${SAFERUN_API_URL}/auth/slack/status`, {
          headers: { 'X-API-Key': this.apiKey },
        });
        
        if (response.ok) {
          const data = await response.json();
          if (data.connected) {
            return true;
          }
        }
      } catch {
        // Ignore errors, keep polling
      }
      
      // Wait before next poll
      await new Promise(resolve => setTimeout(resolve, pollInterval));
      process.stdout.write('.');
    }
    
    return false;
  }

  /**
   * Poll unified setup status (Slack + GitHub in single session)
   * Uses the session state from OAuth flow to track both providers
   */
  private async pollUnifiedSetup(timeoutMs: number = 300000): Promise<UnifiedSetupStatus> {
    const startTime = Date.now();
    const pollInterval = 2000; // 2 seconds
    
    let lastStatus: UnifiedSetupStatus = { slack: false, github: false, ready: false };
    let slackAnnounced = false;
    let githubAnnounced = false;
    
    while (Date.now() - startTime < timeoutMs) {
      try {
        // Use session state if available, fallback to API key polling
        const url = this.currentSessionState 
          ? `${SAFERUN_API_URL}/auth/setup/status?state=${this.currentSessionState}`
          : `${SAFERUN_API_URL}/auth/setup/status`;
          
        const response = await fetch(url, {
          headers: { 'X-API-Key': this.apiKey },
        });
        
        if (response.ok) {
          const data: UnifiedSetupStatus = await response.json();
          lastStatus = data;
          
          // Announce Slack when it connects
          if (data.slack && !slackAnnounced) {
            console.log(chalk.green('\n✓ Slack connected!'));
            slackAnnounced = true;
            this.slackConfigured = true;
            
            if (!data.github) {
              console.log(chalk.yellow('⏳ Waiting for GitHub App installation...'));
            }
          }
          
          // Announce GitHub when it connects
          if (data.github && !githubAnnounced) {
            console.log(chalk.green('\n✓ GitHub App installed!'));
            githubAnnounced = true;
            this.githubAppInstalled = true;
            
            if (!data.slack) {
              console.log(chalk.yellow('⏳ Waiting for Slack connection...'));
            }
          }
          
          // Both connected!
          if (data.ready) {
            return data;
          }
        }
      } catch {
        // Ignore errors, keep polling
      }
      
      // Wait before next poll
      await new Promise(resolve => setTimeout(resolve, pollInterval));
      process.stdout.write('.');
    }
    
    return lastStatus;
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
