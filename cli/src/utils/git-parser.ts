export type GitOperationType = 'push' | 'branch' | 'reset' | 'clean' | 'rebase' | 'unknown';

export interface GitOperation {
  type: GitOperationType;
  action: string;
  targets: string[];
  flags: string[];
  risk: 'low' | 'medium' | 'high';
  remote?: string;
  branch?: string;
}

import { execFile } from 'child_process';
import { promisify } from 'util';

const execFileAsync = promisify(execFile);

export class GitCommandParser {
  parse(command: string, args: string[]): GitOperation {
    switch (command) {
      case 'push':
        return this.parsePush(args);
      case 'branch':
        return this.parseBranch(args);
      case 'reset':
        return this.parseReset(args);
      case 'clean':
        return this.parseClean(args);
      case 'rebase':
        return this.parseRebase(args);
      default:
        return {
          type: 'unknown',
          action: command,
          targets: [],
          flags: [],
          risk: 'low',
        };
    }
  }

  parsePush(args: string[]): GitOperation {
    const operation: GitOperation = {
      type: 'push',
      action: 'push',
      targets: [],
      flags: [],
      risk: 'low',
    };

    const forceVariants = new Set(['--force', '-f', '--force-with-lease', '--force-if-includes']);
    const nonFlagArgs: string[] = [];

    args.forEach((arg) => {
      if (forceVariants.has(arg)) {
        operation.flags.push('force');
        operation.risk = 'high';
      }
      if (arg === '--all') {
        operation.targets.push('ALL_BRANCHES');
        operation.risk = 'high';
      }
      if (arg === '--tags') {
        operation.targets.push('ALL_TAGS');
      }
      if (arg === '--mirror') {
        operation.flags.push('mirror');
        operation.risk = 'high';
      }

      if (!arg.startsWith('-')) {
        nonFlagArgs.push(arg);
      }
    });

    // Assign remote and branch from non-flag arguments in order
    if (nonFlagArgs.length > 0) {
      operation.remote = nonFlagArgs[0];
    }
    if (nonFlagArgs.length > 1) {
      operation.branch = nonFlagArgs[1];
    }

    if (operation.branch) {
      if (operation.branch.startsWith('+')) {
        operation.flags.push('force-refspec');
        operation.risk = 'high';
      }
      if (operation.branch.startsWith(':')) {
        operation.action = 'delete-remote-branch';
        operation.risk = 'high';
      }
    }

    return operation;
  }

  parseBranch(args: string[]): GitOperation {
    const operation: GitOperation = {
      type: 'branch',
      action: 'branch',
      targets: [],
      flags: [],
      risk: 'low',
    };

    for (let i = 0; i < args.length; i += 1) {
      const arg = args[i];
      const next = args[i + 1];

      if (arg === '-D') {
        operation.action = 'delete';
        operation.flags.push('force');
        operation.risk = 'high';
        if (next && !next.startsWith('-')) {
          operation.targets.push(next);
          i += 1;
        }
        continue;
      }

      if (arg === '--delete' || arg === '-d') {
        operation.action = 'delete';
        operation.risk = 'medium';
        if (next && !next.startsWith('-')) {
          operation.targets.push(next);
          i += 1;
        }
        continue;
      }

      if ((arg === '-m' || arg === '--move') && next && !next.startsWith('-')) {
        operation.action = 'rename';
        operation.targets.push(next);
        operation.risk = 'medium';
        i += 1;
        continue;
      }

      if (arg === '-M' && next && !next.startsWith('-')) {
        operation.action = 'force-rename';
        operation.flags.push('force');
        operation.targets.push(next);
        operation.risk = 'high';
        i += 1;
        continue;
      }
    }

    return operation;
  }

  parseReset(args: string[]): GitOperation {
    const operation: GitOperation = {
      type: 'reset',
      action: 'reset',
      targets: [],
      flags: [],
      risk: 'low',
    };

    if (args.includes('--hard')) {
      operation.flags.push('hard');
      operation.risk = 'high';
    }

    for (const arg of args) {
      if (!arg.startsWith('-')) {
        operation.targets.push(arg);
        if (/HEAD~\d+/.test(arg) || /HEAD\^+/.test(arg)) {
          const distanceMatch = arg.match(/\d+/);
          const distance = distanceMatch ? Number.parseInt(distanceMatch[0], 10) : 1;
          if (distance > 3) {
            operation.risk = 'high';
          } else if (operation.risk !== 'high') {
            operation.risk = 'medium';
          }
        } else if (operation.risk !== 'high') {
          operation.risk = 'medium';
        }
      }
    }

    return operation;
  }

  parseClean(args: string[]): GitOperation {
    const operation: GitOperation = {
      type: 'clean',
      action: 'clean',
      targets: [],
      flags: [],
      risk: 'medium',
    };

    if (args.includes('-f') || args.includes('--force')) {
      operation.flags.push('force');
    }
    if (args.includes('-d') || args.includes('--directories')) {
      operation.flags.push('directories');
    }

    return operation;
  }

  parseRebase(args: string[]): GitOperation {
    const operation: GitOperation = {
      type: 'rebase',
      action: 'rebase',
      targets: [],
      flags: [],
      risk: 'medium',
    };

    const interactiveFlags = new Set(['-i', '--interactive']);

    args.forEach((arg) => {
      if (interactiveFlags.has(arg)) {
        operation.flags.push('interactive');
        operation.risk = 'high';
      }
      if (arg === '--onto') {
        operation.flags.push('onto');
        operation.risk = 'high';
      }
      if (!arg.startsWith('-')) {
        operation.targets.push(arg);
      }
    });

    return operation;
  }

  async resolveAlias(command: string, cwd = process.cwd()): Promise<string[] | null> {
    try {
      const { stdout } = await execFileAsync('git', ['config', '--get', `alias.${command}`], { cwd });
      const resolved = stdout.trim();
      if (!resolved) {
        return null;
      }
      return resolved.split(' ');
    } catch {
      return null;
    }
  }
}
