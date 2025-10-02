import chalk from 'chalk';
import inquirer from 'inquirer';
import path from 'path';
import fs from 'fs';
import { execGit, getGitInfo, isGitRepository, listHooks, ensureDir } from '../utils/git';
import { loadConfig, saveConfig, setConfigValue, SafeRunConfig } from '../utils/config';
import { installHooks } from '../hooks/installer';

export interface InitOptions {
  auto: boolean;
}

export class InitCommand {
  async run(options: InitOptions): Promise<void> {
    const cwdIsRepo = await isGitRepository();
    if (!cwdIsRepo) {
      console.error(chalk.red('❌ SafeRun must be initialized inside a git repository.'));
      process.exitCode = 1;
      return;
    }

    const gitInfo = await getGitInfo();
    if (!gitInfo) {
      console.error(chalk.red('❌ Unable to determine git repository information.'));
      process.exitCode = 1;
      return;
    }

    console.log(chalk.cyan('\n🛡️  SafeRun CLI Setup\n'));

    let config = await loadConfig(gitInfo.repoRoot, { allowCreate: true });
    config = await this.configure(config, gitInfo.repoRoot, options.auto, gitInfo.repoSlug, gitInfo.defaultBranch);
    await saveConfig(config, gitInfo.repoRoot);

    const hooksInfo = await installHooks({ repoRoot: gitInfo.repoRoot, gitDir: gitInfo.gitDir });

    await this.configureAliases(gitInfo.repoRoot);

    this.printSummary(config, hooksInfo.installed.length, gitInfo.gitDir);
  }

  private async configure(
    config: SafeRunConfig,
    repoRoot: string,
    auto: boolean,
    repoSlug?: string,
    defaultBranch?: string,
  ): Promise<SafeRunConfig> {
    const protectedBranches = new Set(config.github.protected_branches);
    if (defaultBranch && !protectedBranches.has(defaultBranch)) {
      protectedBranches.add(defaultBranch);
    }

    if (repoSlug && (config.github.repo === 'auto' || !config.github.repo)) {
      config.github.repo = repoSlug;
    }

    if (auto) {
      config.mode = (process.env.SAFERUN_MODE as typeof config.mode) ?? config.mode;
      config.github.protected_branches = Array.from(protectedBranches);
      this.ensureApiKey(config);
      return config;
    }

    const answers = await inquirer.prompt([
      {
        type: 'list',
        name: 'mode',
        message: 'Select SafeRun protection mode:',
        default: config.mode,
        choices: [
          { name: '👀  Monitor (log only)', value: 'monitor' },
          { name: '⚠️   Warn (warnings, no blocking)', value: 'warn' },
          { name: '🛑  Block (require approval)', value: 'block' },
          { name: '🔒  Enforce (strict blocking)', value: 'enforce' },
        ],
      },
      {
        type: 'input',
        name: 'protectedBranches',
        message: 'Protected branches (comma separated):',
        default: Array.from(protectedBranches).join(', '),
        filter: (input: string) => input.split(',').map((value) => value.trim()).filter(Boolean),
      },
      {
        type: 'input',
        name: 'githubRepo',
        message: 'GitHub repository (owner/repo):',
        default: repoSlug ?? config.github.repo ?? 'auto',
      },
      {
        type: 'password',
        name: 'apiKey',
        message: 'SafeRun API key (leave empty to use environment variable):',
        mask: '*',
        validate: (value: string) => (!value ? true : value.length >= 16 || 'API key looks too short'),
      },
    ]);

    setConfigValue(config, 'mode', answers.mode);
    setConfigValue(config, 'github.protected_branches', answers.protectedBranches);

    if (answers.githubRepo && answers.githubRepo !== 'auto') {
      setConfigValue(config, 'github.repo', answers.githubRepo);
    }

    if (answers.apiKey) {
      setConfigValue(config, 'api.key', answers.apiKey);
    } else {
      this.ensureApiKey(config);
    }

    return config;
  }

  private ensureApiKey(config: SafeRunConfig): void {
    if (!config.api.key && !process.env.SAFERUN_API_KEY) {
      console.warn(
        chalk.yellow(
          '\n⚠️  SafeRun API key is not configured. Set SAFERUN_API_KEY env or update .saferun/config.yml',
        ),
      );
    }
  }

  private async configureAliases(repoRoot: string): Promise<void> {
    const aliasMap: Record<string, string> = {
      branch: '!saferun hook git-branch',
      reset: '!saferun hook git-reset',
      clean: '!saferun hook git-clean',
    };

    const backupPath = path.join(repoRoot, '.saferun', 'alias-backup.json');
    let backup: Record<string, string | null> = {};
    if (fs.existsSync(backupPath)) {
      try {
        backup = JSON.parse(await fs.promises.readFile(backupPath, 'utf-8'));
      } catch {
        backup = {};
      }
    }

    for (const [alias, command] of Object.entries(aliasMap)) {
      let current: string | null = null;
      try {
        current = (await execGit(['config', '--get', `alias.${alias}`], { cwd: repoRoot })).trim();
      } catch {
        current = null;
      }

      if (current && current.includes('saferun hook')) {
        // Already configured by SafeRun
        continue;
      }

      if (!(alias in backup)) {
        backup[alias] = current;
      }

      await execGit(['config', '--replace-all', `alias.${alias}`, command], { cwd: repoRoot });
    }

    await ensureDir(path.dirname(backupPath));
    await fs.promises.writeFile(backupPath, JSON.stringify(backup, null, 2));
  }

  private async printSummary(config: SafeRunConfig, hooksInstalled: number, gitDir: string): Promise<void> {
    console.log(chalk.green('\n✅ SafeRun initialized successfully!\n'));
    console.log(chalk.gray('Mode:        '), chalk.bold(config.mode.toUpperCase()));
    console.log(chalk.gray('Git hooks:   '), hooksInstalled > 0 ? chalk.green(`${hooksInstalled} installed`) : chalk.yellow('none installed'));

    const existingHooks = await listHooks(gitDir);
    if (existingHooks.length > 0) {
      console.log(chalk.gray('Hooks dir:   '), gitDir);
    }

    console.log('\nNext steps:');
    console.log(`  • Run ${chalk.cyan('saferun status')} to verify configuration`);
    console.log(`  • Review ${chalk.cyan('.saferun/config.yml')} for advanced options`);
    console.log(`  • Try a protected action (e.g. ${chalk.cyan('git push --force')}) to see SafeRun in action`);
  }
}
