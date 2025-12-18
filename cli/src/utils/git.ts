import { execFile, spawn } from 'child_process';
import { promisify } from 'util';
import fs from 'fs';
import path from 'path';

const execFileAsync = promisify(execFile);

export interface BranchRule {
  pattern: string;
  risk_level?: 'low' | 'medium' | 'high';
  require_approval?: boolean;
  allow_force_push?: boolean;
  skip_checks?: boolean;
}

export interface GitEnvironmentInfo {
  repoRoot: string;
  gitDir: string;
  remoteUrl?: string;
  repoSlug?: string;
  defaultBranch?: string;
}

export async function isGitRepository(cwd = process.cwd()): Promise<boolean> {
  try {
    await execGit(['rev-parse', '--is-inside-work-tree'], { cwd });
    return true;
  } catch {
    return false;
  }
}

export async function getRepositoryRoot(cwd = process.cwd()): Promise<string | null> {
  try {
    const output = await execGit(['rev-parse', '--show-toplevel'], { cwd });
    return output.trim();
  } catch {
    return null;
  }
}

export async function getGitDir(cwd = process.cwd()): Promise<string | null> {
  try {
    const output = await execGit(['rev-parse', '--git-dir'], { cwd });
    return path.resolve(cwd, output.trim());
  } catch {
    return null;
  }
}

export async function getRemoteUrl(remote = 'origin', cwd = process.cwd()): Promise<string | undefined> {
  try {
    const output = await execGit(['remote', 'get-url', remote], { cwd });
    return output.trim();
  } catch {
    return undefined;
  }
}

export async function getRepoSlug(cwd = process.cwd()): Promise<string | undefined> {
  const remote = await getRemoteUrl('origin', cwd);
  if (!remote) {
    return undefined;
  }

  const githubMatch = remote.match(/github\.com[:\/](.+?)(\.git)?$/i);
  if (githubMatch) {
    return githubMatch[1];
  }

  return remote;
}

export async function getDefaultBranch(cwd = process.cwd()): Promise<string | undefined> {
  try {
    const output = await execGit(['symbolic-ref', 'refs/remotes/origin/HEAD'], { cwd });
    const parts = output.trim().split('/');
    return parts[parts.length - 1];
  } catch {
    return undefined;
  }
}

export async function getCurrentBranch(cwd = process.cwd()): Promise<string | undefined> {
  try {
    const output = await execGit(['rev-parse', '--abbrev-ref', 'HEAD'], { cwd });
    const branch = output.trim();
    return branch === 'HEAD' ? undefined : branch;
  } catch {
    return undefined;
  }
}

export async function listHooks(gitDir: string): Promise<string[]> {
  const hooksPath = path.join(gitDir, 'hooks');
  if (!fs.existsSync(hooksPath)) {
    return [];
  }

  return fs
    .readdirSync(hooksPath, { withFileTypes: true })
    .filter((entry) => entry.isFile() && !entry.name.endsWith('.sample'))
    .map((entry) => entry.name);
}

export function matchesBranchPattern(branch: string, pattern: string): boolean {
  if (pattern === branch) {
    return true;
  }

  const escaped = pattern
    .split('*')
    .map((part) => part.replace(/[.+?^${}()|[\]\\]/g, '\\$&'))
    .join('.*');

  const regex = new RegExp(`^${escaped}$`);
  return regex.test(branch);
}

export function isProtectedBranch(branch: string, protectedBranches: string[]): boolean {
  return protectedBranches.some((pattern) => matchesBranchPattern(branch, pattern));
}

export async function getGitInfo(cwd = process.cwd()): Promise<GitEnvironmentInfo | null> {
  const repoRoot = await getRepositoryRoot(cwd);
  if (!repoRoot) {
    return null;
  }

  const gitDir = await getGitDir(cwd);
  if (!gitDir) {
    return null;
  }

  const [remoteUrl, repoSlug, defaultBranch] = await Promise.all([
    getRemoteUrl('origin', cwd),
    getRepoSlug(cwd),
    getDefaultBranch(cwd),
  ]);

  return {
    repoRoot,
    gitDir,
    remoteUrl,
    repoSlug,
    defaultBranch,
  };
}

export async function getUnmergedCommitCount(baseRef: string, branchRef: string, cwd = process.cwd()): Promise<number> {
  try {
    const output = await execGit(['rev-list', '--left-right', '--count', `${baseRef}...${branchRef}`], { cwd });
    const [ahead] = output.trim().split('\t');
    return Number.parseInt(ahead, 10) || 0;
  } catch {
    return 0;
  }
}

export async function getAheadBehind(
  branchRef: string,
  baseRef: string,
  cwd = process.cwd(),
): Promise<{ ahead: number; behind: number }> {
  try {
    const output = await execGit(['rev-list', '--left-right', '--count', `${branchRef}...${baseRef}`], { cwd });
    const [aheadStr = '0', behindStr = '0'] = output.trim().split('\t');
    return {
      ahead: Number.parseInt(aheadStr, 10) || 0,
      behind: Number.parseInt(behindStr, 10) || 0,
    };
  } catch {
    return { ahead: 0, behind: 0 };
  }
}

export async function resolveCommit(ref: string, cwd = process.cwd()): Promise<string | null> {
  try {
    const sha = await execGit(['rev-parse', '--verify', ref], { cwd });
    return sha.trim();
  } catch {
    return null;
  }
}

export async function execGit(args: string[], options: { cwd?: string } = {}): Promise<string> {
  const cwd = options.cwd ?? process.cwd();
  const { stdout } = await execFileAsync('git', args, { cwd });
  return stdout;
}

export async function runGitCommand(
  args: string[],
  options: { cwd?: string; disableAliases?: string[]; env?: NodeJS.ProcessEnv } = {},
): Promise<number> {
  return new Promise((resolve, reject) => {
    const gitArgs: string[] = [];
    for (const alias of options.disableAliases ?? []) {
      gitArgs.push('-c', `alias.${alias}=`);
    }
    gitArgs.push(...args);

    const child = spawn('git', gitArgs, {
      cwd: options.cwd ?? process.cwd(),
      env: { ...process.env, ...options.env },
      stdio: 'inherit',
    });

    child.on('error', reject);
    child.on('exit', (code) => resolve(code ?? 0));
  });
}

export async function ensureDir(dirPath: string): Promise<void> {
  await fs.promises.mkdir(dirPath, { recursive: true });
}

export function resolvePath(cwd: string, relativePath: string): string {
  if (path.isAbsolute(relativePath)) {
    return relativePath;
  }
  return path.join(cwd, relativePath);
}

export async function readFileSafe(filePath: string): Promise<string | null> {
  try {
    return await fs.promises.readFile(filePath, 'utf-8');
  } catch {
    return null;
  }
}

export async function writeFileSafe(filePath: string, content: string): Promise<void> {
  await ensureDir(path.dirname(filePath));
  await fs.promises.writeFile(filePath, content, 'utf-8');
}

export async function pathExists(filePath: string): Promise<boolean> {
  try {
    await fs.promises.access(filePath);
    return true;
  } catch {
    return false;
  }
}

/**
 * Get current git user name and email
 */
export async function getGitAuthor(cwd = process.cwd()): Promise<{ name: string; email: string } | undefined> {
  try {
    // First check environment variables (used by AI agents/tooling)
    const envName = process.env.GIT_AUTHOR_NAME || process.env.GIT_COMMITTER_NAME;
    const envEmail = process.env.GIT_AUTHOR_EMAIL || process.env.GIT_COMMITTER_EMAIL;
    
    if (envName && envEmail) {
      return { name: envName, email: envEmail };
    }
    
    // Fallback to git config
    const name = (await execGit(['config', 'user.name'], { cwd })).trim();
    const email = (await execGit(['config', 'user.email'], { cwd })).trim();
    
    if (name && email) {
      return { name, email };
    }
    
    return undefined;
  } catch {
    return undefined;
  }
}
