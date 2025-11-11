import chalk from 'chalk';
import { dump as dumpYaml } from 'js-yaml';
import { getGitInfo, isGitRepository } from '../utils/git';
import { loadConfig, saveConfig, setConfigValue, SafeRunConfig } from '../utils/config';

export class ConfigCommand {
  async show(): Promise<void> {
    const config = await this.load();
    if (!config) {
      return;
    }
    const yaml = dumpYaml(config, { lineWidth: 120 });
    console.log(yaml);
  }

  async set(path: string, value: string): Promise<void> {
    const config = await this.load();
    if (!config) {
      return;
    }

    let parsed: unknown = value;
    if (value === 'true' || value === 'false') {
      parsed = value === 'true';
    } else if (!Number.isNaN(Number(value))) {
      parsed = Number(value);
    }

    setConfigValue(config, path, parsed);
    const gitInfo = await getGitInfo();
    if (!gitInfo) {
      return;
    }
    await saveConfig(config, gitInfo.repoRoot);
    console.log(chalk.green(`✓ Updated ${path}`));
  }

  async slack(options: {
    channel?: string;
    webhookUrl?: string;
    botToken?: string;
    disable?: boolean;
    show?: boolean;
  }): Promise<void> {
    const config = await this.load();
    if (!config) {
      return;
    }

    const gitInfo = await getGitInfo();
    if (!gitInfo) {
      return;
    }

    const { resolveApiKey } = await import('../utils/api-client');
    const apiKey = resolveApiKey(config);

    if (!apiKey) {
      console.error(chalk.red('❌ No API key configured.'));
      console.error(chalk.yellow('   Set SAFERUN_API_KEY env or run: saferun init'));
      process.exitCode = 1;
      return;
    }

    // Show current configuration
    if (options.show) {
      await this.showSlackConfig(config.api.url, apiKey);
      return;
    }

    // Disable Slack notifications
    if (options.disable) {
      await this.updateSlackConfig(config.api.url, apiKey, {
        slack_enabled: false,
        slack_channel: '#saferun-alerts',
      });
      console.log(chalk.green('✅ Slack notifications disabled'));
      return;
    }

    // Interactive mode if no options provided
    if (!options.channel && !options.webhookUrl && !options.botToken) {
      const inquirer = await import('inquirer');
      const answers = await inquirer.default.prompt([
        {
          type: 'input',
          name: 'webhookUrl',
          message: 'Slack Webhook URL (or leave empty):',
          validate: (value: string) => {
            if (!value) return true;
            if (!value.startsWith('https://hooks.slack.com/')) {
              return 'Invalid webhook URL. Should start with https://hooks.slack.com/';
            }
            return true;
          },
        },
        {
          type: 'input',
          name: 'channel',
          message: 'Slack Channel:',
          default: '#saferun-alerts',
        },
      ]);

      options.webhookUrl = answers.webhookUrl || undefined;
      options.channel = answers.channel;
    }

    // Configure Slack
    if (!options.webhookUrl && !options.botToken) {
      console.error(chalk.red('❌ Either --webhook-url or --bot-token required'));
      process.exitCode = 1;
      return;
    }

    await this.updateSlackConfig(config.api.url, apiKey, {
      slack_webhook_url: options.webhookUrl,
      slack_bot_token: options.botToken,
      slack_channel: options.channel || '#saferun-alerts',
      slack_enabled: true,
      notification_channels: ['slack'],
    });

    console.log(chalk.green('\n✅ Slack notifications configured!'));
    console.log(chalk.gray(`   Channel: ${options.channel || '#saferun-alerts'}`));
    console.log(chalk.gray('\n💡 Test by running: curl -X POST ' + config.api.url + '/v1/settings/notifications/test/slack -H "X-API-Key: ..."'));
  }

  private async showSlackConfig(apiUrl: string, apiKey: string): Promise<void> {
    const url = `${apiUrl}/v1/settings/notifications`;

    try {
      const response = await fetch(url, {
        method: 'GET',
        headers: {
          'X-API-Key': apiKey,
        },
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${await response.text()}`);
      }

      const data = await response.json();

      console.log(chalk.cyan('\n🔔 Slack Configuration:\n'));
      console.log(`  Enabled: ${data.slack_enabled ? chalk.green('Yes') : chalk.red('No')}`);
      console.log(`  Channel: ${data.slack_channel || '#saferun-alerts'}`);
      console.log(`  Webhook: ${data.slack_webhook_url || chalk.gray('Not configured')}`);
      console.log(`  Bot Token: ${data.slack_bot_token || chalk.gray('Not configured')}`);
    } catch (error: any) {
      console.error(chalk.red(`❌ Failed to fetch configuration: ${error.message}`));
      process.exitCode = 1;
    }
  }

  private async updateSlackConfig(
    apiUrl: string,
    apiKey: string,
    settings: any
  ): Promise<void> {
    const url = `${apiUrl}/v1/settings/notifications`;

    try {
      const response = await fetch(url, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          'X-API-Key': apiKey,
        },
        body: JSON.stringify(settings),
      });

      if (!response.ok) {
        const error = await response.text();
        throw new Error(`HTTP ${response.status}: ${error}`);
      }
    } catch (error: any) {
      console.error(chalk.red(`❌ Failed to configure Slack: ${error.message}`));
      process.exitCode = 1;
      throw error;
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
