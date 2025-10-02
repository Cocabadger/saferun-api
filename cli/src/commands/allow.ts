/**
 * Command: saferun allow
 * Add entries to whitelist to reduce false positives
 */

import chalk from 'chalk';
import { getGitInfo } from '../utils/git';
import { addToWhitelist, removeFromWhitelist, listWhitelist, WhitelistEntry } from '../utils/whitelist';
import Table from 'cli-table3';

export class AllowCommand {
  async addCI(scope: string, reason?: string): Promise<void> {
    const gitInfo = await getGitInfo();
    if (!gitInfo) {
      console.error(chalk.red('Error: Not a git repository'));
      process.exit(1);
    }

    await addToWhitelist(gitInfo.repoRoot, {
      type: 'ci',
      identifier: scope,
      reason: reason || `CI/CD system: ${scope}`,
    });

    console.log(chalk.green(`✓ Added CI system "${scope}" to whitelist`));
    console.log(chalk.gray(`  Operations from ${scope} will be allowed automatically`));
  }

  async addBot(name: string, reason?: string): Promise<void> {
    const gitInfo = await getGitInfo();
    if (!gitInfo) {
      console.error(chalk.red('Error: Not a git repository'));
      process.exit(1);
    }

    await addToWhitelist(gitInfo.repoRoot, {
      type: 'bot',
      identifier: name,
      reason: reason || `Bot: ${name}`,
    });

    console.log(chalk.green(`✓ Added bot "${name}" to whitelist`));
    console.log(chalk.gray(`  Git operations by this bot will be allowed`));
  }

  async addAutomation(context: string, reason?: string): Promise<void> {
    const gitInfo = await getGitInfo();
    if (!gitInfo) {
      console.error(chalk.red('Error: Not a git repository'));
      process.exit(1);
    }

    await addToWhitelist(gitInfo.repoRoot, {
      type: 'automation',
      identifier: context,
      reason: reason || `Automation: ${context}`,
    });

    console.log(chalk.green(`✓ Added automation "${context}" to whitelist`));
    console.log(chalk.gray(`  This automation context will be allowed`));
  }

  async addAgent(id: string, type?: string, reason?: string): Promise<void> {
    const gitInfo = await getGitInfo();
    if (!gitInfo) {
      console.error(chalk.red('Error: Not a git repository'));
      process.exit(1);
    }

    await addToWhitelist(gitInfo.repoRoot, {
      type: 'agent',
      identifier: id,
      scope: type ? `type:${type}` : undefined,
      reason: reason || `AI Agent: ${id}`,
    });

    console.log(chalk.green(`✓ Added agent "${id}" to whitelist`));
    if (type) {
      console.log(chalk.gray(`  Type: ${type}`));
    }
  }

  async list(): Promise<void> {
    const gitInfo = await getGitInfo();
    if (!gitInfo) {
      console.error(chalk.red('Error: Not a git repository'));
      process.exit(1);
    }

    const entries = await listWhitelist(gitInfo.repoRoot);

    if (entries.length === 0) {
      console.log(chalk.yellow('No whitelist entries'));
      console.log(chalk.gray('\nAdd entries with:'));
      console.log(chalk.gray('  saferun allow ci --scope jenkins'));
      console.log(chalk.gray('  saferun allow bot --name "renovate[bot]"'));
      return;
    }

    console.log(chalk.bold('\n🤍 Whitelist Entries\n'));

    const table = new Table({
      head: ['Type', 'Identifier', 'Scope', 'Added', 'Reason'],
      style: { head: ['cyan'] },
    });

    entries.forEach((entry) => {
      table.push([
        entry.type.toUpperCase(),
        entry.identifier,
        entry.scope || '-',
        new Date(entry.added_at).toLocaleDateString(),
        entry.reason || '-',
      ]);
    });

    console.log(table.toString());
    console.log(chalk.gray(`\nTotal: ${entries.length} entries`));
  }

  async remove(identifier: string): Promise<void> {
    const gitInfo = await getGitInfo();
    if (!gitInfo) {
      console.error(chalk.red('Error: Not a git repository'));
      process.exit(1);
    }

    const removed = await removeFromWhitelist(gitInfo.repoRoot, identifier);

    if (removed) {
      console.log(chalk.green(`✓ Removed "${identifier}" from whitelist`));
    } else {
      console.log(chalk.yellow(`Entry "${identifier}" not found in whitelist`));
    }
  }
}