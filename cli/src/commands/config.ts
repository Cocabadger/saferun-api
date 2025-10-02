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
