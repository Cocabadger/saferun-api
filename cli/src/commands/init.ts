import chalk from 'chalk';
import inquirer from 'inquirer';
import path from 'path';
import fs from 'fs';
import { execGit, getGitInfo, isGitRepository, listHooks, ensureDir } from '../utils/git';
import { loadGlobalConfig, saveGlobalConfig, setGlobalMode } from '../utils/global-config';
import { registerProtectedRepo, isRepoProtectedSync } from '../utils/protected-repos';
import { installHooks } from '../hooks/installer';
import { SafeRunConfig, ProtectionMode } from '../utils/config';
import { installBinaryWrapper, printBinaryWrapperInstructions } from '../utils/binary-wrapper';

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

    // Load global config (not local!)
    let config = await loadGlobalConfig();

    // Configure mode and branches
    config = await this.configure(config, gitInfo.repoRoot, options.auto, gitInfo.repoSlug, gitInfo.defaultBranch);

    // Save to global config
    await saveGlobalConfig(config);

    // Register repo in global protected repos registry
    await registerProtectedRepo(gitInfo.repoRoot, {
      github: gitInfo.repoSlug,
      mode: config.mode,
    });

    const hooksInfo = await installHooks({ repoRoot: gitInfo.repoRoot, gitDir: gitInfo.gitDir });

    await this.configureAliases(gitInfo.repoRoot);

    // Install binary wrapper for agent protection
    const wrapperInfo = await installBinaryWrapper(gitInfo.repoRoot);

    this.printSummary(config, hooksInfo.installed.length, gitInfo.gitDir, gitInfo.repoRoot, wrapperInfo.installed);
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

    if (auto) {
      config.mode = (process.env.SAFERUN_MODE as typeof config.mode) ?? config.mode;
      config.github.protected_branches = Array.from(protectedBranches);
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
    ]);

    config.mode = answers.mode as ProtectionMode;
    config.github.protected_branches = answers.protectedBranches;

    return config;
  }

  private async configureAliases(repoRoot: string): Promise<void> {
    const aliasMap: Record<string, string> = {
      branch: '!saferun hook git-branch',
      reset: '!saferun hook git-reset',
      clean: '!saferun hook git-clean',
      push: '!saferun hook git-push',
      commit: '!saferun hook git-commit',
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

  private async printSummary(config: SafeRunConfig, hooksInstalled: number, gitDir: string, repoRoot: string, wrapperInstalled: boolean = false): Promise<void> {
    console.log(chalk.green('\n✅ SafeRun initialized successfully!\n'));
    console.log(chalk.gray('Mode:        '), chalk.bold(config.mode.toUpperCase()));
    console.log(chalk.gray('Git hooks:   '), hooksInstalled > 0 ? chalk.green(`${hooksInstalled} installed`) : chalk.yellow('none installed'));
    console.log(chalk.gray('Binary wrap: '), wrapperInstalled ? chalk.green('✓ .saferun/bin/git') : chalk.yellow('not installed'));
    console.log(chalk.gray('Protected:   '), chalk.green('✓ Registered in global registry'));
    console.log(chalk.gray('Config:      '), chalk.cyan('~/.saferun/config.yml'));

    const existingHooks = await listHooks(gitDir);
    if (existingHooks.length > 0) {
      console.log(chalk.gray('Hooks dir:   '), gitDir);
    }

    // Show critical binary wrapper instructions
    if (wrapperInstalled) {
      printBinaryWrapperInstructions(repoRoot);
    }

    console.log(chalk.white('Next steps:'));
    console.log(`  • Run ${chalk.cyan('saferun doctor')} to verify configuration`);
    console.log(`  • Run ${chalk.cyan('saferun config show')} to see current settings`);
    console.log(`  • Try a protected action (e.g. ${chalk.cyan('git reset --hard')}) to see SafeRun in action`);
  }
}