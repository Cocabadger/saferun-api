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
  test?: boolean;
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

    // Test mode - send test notification
    if (options.test) {
      await this.testSlack(apiKey, config.api.url);
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

    // Interactive mode if no options provided
    if (!options.channel && !options.webhookUrl && !options.botToken) {
      const answers = await inquirer.prompt([
        {
          type: 'list',
          name: 'method',
          message: 'Choose Slack integration method:',
          choices: [
            { name: 'Webhook URL (recommended, easier setup)', value: 'webhook' },
            { name: 'Bot Token (advanced, more features)', value: 'bot' },
          ],
        },
        {
          type: 'input',
          name: 'webhookUrl',
          message: 'Slack Webhook URL:',
          when: (answers: any) => answers.method === 'webhook',
          validate: (value: string) => {
            if (!value) return 'Webhook URL is required';
            if (!value.startsWith('https://hooks.slack.com/')) {
              return 'Invalid webhook URL. Should start with https://hooks.slack.com/';
            }
            return true;
          },
        },
        {
          type: 'input',
          name: 'botToken',
          message: 'Slack Bot Token (xoxb-...):',
          when: (answers: any) => answers.method === 'bot',
          validate: (value: string) => {
            if (!value) return 'Bot token is required';
            if (!value.startsWith('xoxb-')) {
              return 'Invalid bot token. Should start with xoxb-';
            }
            return true;
          },
        },
        {
          type: 'input',
          name: 'channel',
          message: 'Slack Channel:',
          default: '#saferun-alerts',
          validate: (value: string) => {
            if (!value.startsWith('#') && !value.startsWith('@')) {
              return 'Channel should start with # or @';
            }
            return true;
          },
        },
      ]);

      options.webhookUrl = answers.webhookUrl || undefined;
      options.botToken = answers.botToken || undefined;
      options.channel = answers.channel;
    }

    // Configure slack
    if (!options.webhookUrl && !options.botToken) {
      console.error(chalk.red('❌ Either --webhook-url or --bot-token required'));
      process.exitCode = 1;
      return;
    }

    await this.configureSlack(apiKey, config.api.url, {
      slack_webhook_url: options.webhookUrl,
      slack_bot_token: options.botToken,
      slack_channel: options.channel || '#saferun-alerts',
      slack_enabled: true,
      notification_channels: ['slack'],
    });

    console.log(chalk.green('\n✅ Slack notifications configured!'));
    console.log(chalk.gray(`   Channel: ${options.channel || '#saferun-alerts'}`));
    console.log(chalk.gray('\n💡 Test with: saferun config slack --test'));
    console.log(chalk.gray('   Or trigger a SafeRun operation (e.g., git push --force)'));
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

  private async testSlack(apiKey: string, apiUrl: string): Promise<void> {
    console.log(chalk.gray('Sending test notification...\n'));

    const url = `${apiUrl}/v1/settings/notifications/test/slack`;

    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: {
          'X-API-Key': apiKey,
        },
      });

      if (!response.ok) {
        const error = await response.text();
        console.error(chalk.red(`❌ Failed to send test notification: ${error}`));
        process.exitCode = 1;
        return;
      }

      const result = await response.json();
      console.log(chalk.green('✅ ' + result.message));
      console.log(chalk.gray('\n💡 Check your Slack channel for the test message'));
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
