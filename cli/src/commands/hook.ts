import chalk from 'chalk';
import { loadGlobalConfig } from '../utils/global-config';
import { isRepoProtectedSync } from '../utils/protected-repos';
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

    // Check if repo is protected (using global registry)
    if (!isRepoProtectedSync(gitInfo.repoRoot)) {
      // Not protected - pass through
      return runGitCommand(this.mapHandlerToGitCommand(handler, forwarded), { 
        cwd: gitInfo.repoRoot,
        disableAliases: [this.aliasName(handler)] 
      });
    }

    // Load global config (not local!)
    const config = await loadGlobalConfig();
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
        case 'git-push': {
          const { interceptForcePush } = await import('../interceptors/force-push');
          return await interceptForcePush(context);
        }
        case 'git-commit': {
          const { interceptCommit } = await import('../interceptors/commit');
          return await interceptCommit(context);
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
      case 'git-push':
        return 'push';
      case 'git-commit':
        return 'commit';
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
      case 'git-push':
        return ['push', ...args];
      case 'git-commit':
        return ['commit', ...args];
      default: {
        const command = handler.startsWith('git-') ? handler.slice(4) : handler;
        return [command, ...args];
      }
    }
  }
}
