import { Command } from 'commander';

export function registerCommands(program: Command) {
  // ─────────────────────────────────────────────────────────────────
  // SETUP & DIAGNOSTICS
  // ─────────────────────────────────────────────────────────────────

  program
    .command('setup')
    .description('Complete SafeRun setup wizard (API key, Slack, GitHub App, hooks)')
    .option('--api-key <key>', 'Provide API key directly')
    .option('--skip-slack', 'Skip Slack configuration')
    .option('--skip-github', 'Skip GitHub App installation')
    .action(async (options) => {
      const { SetupCommand } = await import('./commands/setup');
      await new SetupCommand().run({
        apiKey: options.apiKey,
        skipSlack: options.skipSlack,
        skipGithub: options.skipGithub,
      });
    });

  program
    .command('doctor')
    .description('Check SafeRun health and configuration')
    .action(async () => {
      const { DoctorCommand } = await import('./commands/doctor');
      await new DoctorCommand().run();
    });

  // ─────────────────────────────────────────────────────────────────
  // REPOSITORY COMMANDS
  // ─────────────────────────────────────────────────────────────────

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
    .option('--global', 'Remove ALL SafeRun data (credentials, config, shell wrapper)')
    .action(async (options) => {
      const { UninstallCommand } = await import('./commands/uninstall');
      await new UninstallCommand().run({ global: options.global });
    });

  program
    .command('status')
    .description('Show SafeRun protection status for this repo')
    .option('--agents', 'Show AI agent detection status and signals')
    .option('--pending', 'Show pending approvals')
    .option('-n, --tail <count>', 'Show last N operations (default: 10)', '10')
    .action(async (options) => {
      const { StatusCommand } = await import('./commands/status');
      await new StatusCommand().run({ 
        agents: options.agents, 
        pending: options.pending,
        tail: parseInt(options.tail, 10) || 10
      });
    });

  program
    .command('is-protected')
    .description('Check if current directory is a protected repository')
    .option('-q, --quiet', 'Quiet mode - only exit code')
    .action(async (options) => {
      const { IsProtectedCommand } = await import('./commands/is-protected');
      const exitCode = await new IsProtectedCommand().run({ quiet: options.quiet });
      process.exit(exitCode);
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

  // REMOVED: config set and config mode - security vulnerability
  // Agents could disable their own protection with "saferun config mode monitor"
  // Mode changes require manual editing of ~/.saferun/config.yml

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

  // saferun agent - agent status (read-only)
  program
    .command('agent')
    .description('View AI agent detection status')
    .argument('[subcommand]', 'Subcommand: status')
    .argument('[args...]', 'Additional arguments')
    .action(async (subcommand?: string, args?: string[], options?: any) => {
      const { AgentCommand } = await import('./commands/agent');
      const cmd = new AgentCommand();

      // Only allow status command (read-only)
      // register/unregister removed for security - agents should not self-register
      await cmd.status();
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
