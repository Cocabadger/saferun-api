import chalk from 'chalk';
import { loadConfig } from '../utils/config';
import { createSafeRunClient } from '../utils/api-client';
import { getGitInfo, runGitCommand } from '../utils/git';
import { MetricsCollector } from '../utils/metrics';
import { InterceptorContext } from '../interceptors/types';

export class HookCommand {
  async run(handler: string, forwarded: string[]): Promise<number> {
    const gitInfo = await getGitInfo();
    if (!gitInfo) {
      return runGitCommand(this.mapHandlerToGitCommand(handler, forwarded), { disableAliases: [this.aliasName(handler)] });
    }

    const config = await loadConfig(gitInfo.repoRoot, { allowCreate: true });
    const modeSettings = config.modes?.[config.mode];

    const metrics = new MetricsCollector(gitInfo.repoRoot, config);
    try {
      const client = createSafeRunClient({ config }) as any;
      const context: InterceptorContext = {
        args: forwarded,
        config,
        gitInfo,
        client,
        metrics,
        modeSettings,
      };

      switch (handler) {
        case 'git-branch': {
          const { interceptBranchDelete } = await import('../interceptors/branch-delete');
          return await interceptBranchDelete(context);
        }
        case 'git-reset': {
          const { interceptReset } = await import('../interceptors/reset-hard');
          return await interceptReset(context);
        }
        case 'git-clean': {
          const { interceptClean } = await import('../interceptors/clean');
          return await interceptClean(context);
        }
        default: {
          console.warn(chalk.yellow(`Unknown SafeRun hook handler: ${handler}`));
          return runGitCommand(this.mapHandlerToGitCommand(handler, forwarded), {
            cwd: gitInfo.repoRoot,
            disableAliases: [this.aliasName(handler)],
          });
        }
      }
    } finally {
      await metrics.dispose();
    }
  }

  private aliasName(handler: string): string {
    switch (handler) {
      case 'git-branch':
        return 'branch';
      case 'git-reset':
        return 'reset';
      case 'git-clean':
        return 'clean';
      default:
        return handler;
    }
  }

  private mapHandlerToGitCommand(handler: string, args: string[]): string[] {
    switch (handler) {
      case 'git-branch':
        return ['branch', ...args];
      case 'git-reset':
        return ['reset', ...args];
      case 'git-clean':
        return ['clean', ...args];
      default: {
        const command = handler.startsWith('git-') ? handler.slice(4) : handler;
        return [command, ...args];
      }
    }
  }
}
