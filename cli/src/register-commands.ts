import { Command } from 'commander';

export function registerCommands(program: Command) {
  program
    .command('init')
    .description('Install SafeRun git protections in the current repository')
    .option('--auto', 'Run without prompts using sensible defaults')
    .action(async (options) => {
      const { InitCommand } = await import('./commands/init');
      await new InitCommand().run({ auto: options.auto ?? false });
    });

  program
    .command('uninstall')
    .description('Remove SafeRun hooks from the current repository')
    .action(async () => {
      const { UninstallCommand } = await import('./commands/uninstall');
      await new UninstallCommand().run();
    });

  program
    .command('status')
    .description('Show SafeRun protection status for this repo')
    .option('--agents', 'Show AI agent detection status and signals')
    .option('--pending', 'Show pending approvals')
    .action(async (options) => {
      const { StatusCommand } = await import('./commands/status');
      await new StatusCommand().run({ agents: options.agents, pending: options.pending });
    });

  program
    .command('history')
    .description('Show recent SafeRun activity')
    .option('-n, --limit <n>', 'Limit number of entries', '20')
    .option('--since <date>', 'Show operations since date (e.g., "2024-01-01", "7d")')
    .option('--until <date>', 'Show operations until date')
    .option('--operation <type>', 'Filter by operation type (e.g., "force_push")')
    .option('--ai-only', 'Show only AI agent operations')
    .option('--export <format>', 'Export to file (json, csv)')
    .action(async (options) => {
      const { HistoryCommand } = await import('./commands/history');
      const limit = Number.parseInt(options.limit, 10) || 20;
      await new HistoryCommand().run({
        limit,
        since: options.since,
        until: options.until,
        operation: options.operation,
        aiOnly: options.aiOnly,
        export: options.export,
      });
    });

  const config = program
    .command('config')
    .description('View or modify SafeRun configuration');

  config
    .command('show')
    .description('Print current SafeRun configuration')
    .action(async () => {
      const { ConfigCommand } = await import('./commands/config');
      await new ConfigCommand().show();
    });

  config
    .command('set <path> <value>')
    .description('Set a configuration value (dot notation)')
    .action(async (path: string, value: string) => {
      const { ConfigCommand } = await import('./commands/config');
      await new ConfigCommand().set(path, value);
    });

  config
    .command('mode <mode>')
    .description('Switch SafeRun protection mode')
    .action(async (mode: string) => {
      const { ConfigCommand } = await import('./commands/config');
      await new ConfigCommand().set('mode', mode);
    });

  config
    .command('slack')
    .description('Configure Slack notifications')
    .option('--channel <channel>', 'Slack channel (e.g., #my-team)')
    .option('--webhook-url <url>', 'Slack webhook URL')
    .option('--bot-token <token>', 'Slack bot token (xoxb-...)')
    .option('--disable', 'Disable Slack notifications')
    .option('--test', 'Send test notification')
    .option('--show', 'Show current Slack configuration')
    .action(async (options: any) => {
      const { ConfigCommand } = await import('./commands/config');
      await new ConfigCommand().slack(options);
    });

  // saferun allow - whitelist management
  program
    .command('allow')
    .description('Manage whitelist for bots and automation')
    .argument('[subcommand]', 'Subcommand: ci, bot, automation, agent, list, remove')
    .argument('[args...]', 'Additional arguments')
    .allowUnknownOption(true)
    .action(async (subcommand: string, args: string[], options: any) => {
      const { AllowCommand } = await import('./commands/allow');
      const cmd = new AllowCommand();

      switch (subcommand) {
        case 'ci':
          await cmd.addCI(options.scope || args[0] || 'ci', options.reason);
          break;
        case 'bot':
          await cmd.addBot(options.name || options.email || args[0], options.reason);
          break;
        case 'automation':
          await cmd.addAutomation(options.context || args[0], options.reason);
          break;
        case 'agent':
          await cmd.addAgent(options.id || args[0], options.type, options.reason);
          break;
        case 'list':
          await cmd.list();
          break;
        case 'remove':
          await cmd.remove(args[0]);
          break;
        default:
          console.log('Usage: saferun allow <ci|bot|automation|agent|list|remove>');
      }
    });

  // saferun feedback - view detection feedback
  program
    .command('feedback')
    .description('View AI detection feedback and statistics')
    .argument('[subcommand]', 'Subcommand: stats, list, sync')
    .action(async (subcommand?: string) => {
      const { FeedbackCommand } = await import('./commands/feedback');
      const cmd = new FeedbackCommand();

      switch (subcommand) {
        case 'stats':
          await cmd.stats();
          break;
        case 'list':
          await cmd.list();
          break;
        case 'sync':
          await cmd.sync();
          break;
        default:
          await cmd.stats(); // Default to stats
      }
    });

  // saferun shell-init - setup shell integration
  program
    .command('shell-init')
    .description('Setup shell integration for AI session detection')
    .option('--auto', 'Automatically add to shell config')
    .option('--shell <type>', 'Shell type (zsh, bash, fish)')
    .action(async (options) => {
      const { ShellInitCommand } = await import('./commands/shell-init');
      await new ShellInitCommand().run({ auto: options.auto, shell: options.shell });
    });

  // saferun agent - agent registration
  program
    .command('agent')
    .description('Manage AI agent registration')
    .argument('[subcommand]', 'Subcommand: register, unregister, status')
    .argument('[args...]', 'Additional arguments')
    .action(async (subcommand?: string, args?: string[], options?: any) => {
      const { AgentCommand } = await import('./commands/agent');
      const cmd = new AgentCommand();

      switch (subcommand) {
        case 'register':
          await cmd.register(args?.[0] || 'unknown', { id: options?.id, version: options?.version });
          break;
        case 'unregister':
          await cmd.unregister();
          break;
        case 'status':
        default:
          await cmd.status();
      }
    });

  program
    .command('hook')
    .description('Internal command used by SafeRun git aliases')
    .argument('<handler>')
    .argument('[args...]')
    .allowUnknownOption(true)
    .action(async (handler: string, forwarded: string[] = []) => {
      const { HookCommand } = await import('./commands/hook');
      const exitCode = await new HookCommand().run(handler, forwarded);
      process.exit(exitCode);
    });
}
