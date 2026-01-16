import chalk from 'chalk';
import { dump as dumpYaml } from 'js-yaml';
import inquirer from 'inquirer';
import { getGitInfo, isGitRepository } from '../utils/git';
import { loadConfig, saveConfig, setConfigValue, SafeRunConfig } from '../utils/config';
import { resolveApiKey } from '../utils/api-client';

interface SlackConfigOptions {
  channel?: string;
  webhookUrl?: string;
  botToken?: string;
  disable?: boolean;

  show?: boolean;
}

export class ConfigCommand {
  async show(): Promise<void> {
    const config = await this.load();
    if (!config) {
      return;
    }
    const yaml = dumpYaml(config, { lineWidth: 120 });
    console.log(yaml);
  }



  async slack(options: SlackConfigOptions): Promise<void> {
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
    const apiKey = resolveApiKey(config);

    if (!apiKey) {
      console.error(chalk.red('❌ No API key configured.'));
      console.error(chalk.yellow('   Set SAFERUN_API_KEY env or run: saferun init'));
      process.exitCode = 1;
      return;
    }

    console.log(chalk.cyan('\n🔔 SafeRun Slack Configuration\n'));

    // Show current configuration
    if (options.show) {
      await this.showSlackConfig(apiKey, config.api.url);
      return;
    }



    // Disable slack
    if (options.disable) {
      await this.configureSlack(apiKey, config.api.url, {
        slack_enabled: false,
        slack_channel: '#saferun-alerts',
        notification_channels: ['slack'],
      });
      console.log(chalk.green('✅ Slack notifications disabled'));
      return;
    }

    console.log(chalk.cyan('To configure Slack, please run:'));
    console.log(chalk.green('  saferun setup'));
    console.log(chalk.gray('\nSupported commands:'));
    console.log(chalk.gray('  saferun config slack --show'));

    console.log(chalk.gray('  saferun config slack --disable'));
  }

  private async configureSlack(
    apiKey: string,
    apiUrl: string,
    config: any
  ): Promise<void> {
    const url = `${apiUrl}/v1/settings/notifications`;

    const response = await fetch(url, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': apiKey,
      },
      body: JSON.stringify(config),
    });

    if (!response.ok) {
      const error = await response.text();
      throw new Error(`Failed to configure Slack: ${error}`);
    }
  }



  private async showSlackConfig(apiKey: string, apiUrl: string): Promise<void> {
    const url = `${apiUrl}/v1/settings/notifications`;

    try {
      const response = await fetch(url, {
        method: 'GET',
        headers: {
          'X-API-Key': apiKey,
        },
      });

      if (!response.ok) {
        const error = await response.text();
        console.error(chalk.red(`❌ Failed to get configuration: ${error}`));
        process.exitCode = 1;
        return;
      }

      const settings = await response.json();

      console.log(chalk.cyan('📋 Current Slack Configuration:\n'));
      console.log(`  Status: ${settings.slack_enabled ? chalk.green('✓ Enabled') : chalk.gray('✗ Disabled')}`);
      console.log(`  Channel: ${chalk.yellow(settings.slack_channel || '#saferun-alerts')}`);

      if (settings.slack_webhook_url) {
        console.log(`  Webhook: ${chalk.gray(settings.slack_webhook_url)}`);  // Already masked by API
      } else {
        console.log(`  Webhook: ${chalk.gray('Not configured')}`);
      }

      if (settings.slack_bot_token) {
        console.log(`  Bot Token: ${chalk.gray(settings.slack_bot_token)}`);  // Already masked by API
      } else {
        console.log(`  Bot Token: ${chalk.gray('Not configured')}`);
      }


      console.log(`  ${chalk.gray('💡 Use --disable to turn off notifications')}`);
    } catch (error: any) {
      console.error(chalk.red(`❌ Error: ${error.message}`));
      process.exitCode = 1;
    }
  }

  private async load(): Promise<SafeRunConfig | null> {
    const isRepo = await isGitRepository();
    if (!isRepo) {
      console.error(chalk.red('❌ Not inside a git repository.'));
      return null;
    }

    const gitInfo = await getGitInfo();
    if (!gitInfo) {
      console.error(chalk.red('❌ Unable to determine git repository information.'));
      return null;
    }

    const config = await loadConfig(gitInfo.repoRoot, { allowCreate: true });
    return config;
  }
}
