import fs from 'fs';
import path from 'path';
import { promisify } from 'util';
import { getCliVersion } from '../version';

const chmod = promisify(fs.chmod);

export interface HookManifestEntry {
  name: string;
  target: string;
  backup?: string;
}

export interface HookManifest {
  version: string;
  installedAt: string;
  hooks: HookManifestEntry[];
}

export interface InstallHooksOptions {
  repoRoot: string;
  gitDir: string;
  hooks?: string[];
}

export interface InstallHooksResult {
  installed: HookManifestEntry[];
}

const DEFAULT_HOOKS = ['pre-push', 'pre-commit', 'post-checkout'];
const MANIFEST_FILENAME = 'hooks-manifest.json';
const BACKUP_DIRNAME = 'hooks-backup';

export async function installHooks(options: InstallHooksOptions): Promise<InstallHooksResult> {
  const hooks = options.hooks ?? DEFAULT_HOOKS;
  const manifest = await loadManifest(options.repoRoot);
  const entries: HookManifestEntry[] = [];

  for (const hookName of hooks) {
    const entry = await installHook(options.repoRoot, options.gitDir, hookName);
    entries.push(entry);
  }

  const updatedManifest: HookManifest = {
    version: getCliVersion(),
    installedAt: new Date().toISOString(),
    hooks: mergeManifestEntries(manifest?.hooks ?? [], entries),
  };

  await saveManifest(options.repoRoot, updatedManifest);
  return { installed: entries };
}

export async function uninstallHooks(repoRoot: string, gitDir: string): Promise<void> {
  const manifest = await loadManifest(repoRoot);
  if (!manifest) {
    return;
  }

  for (const entry of manifest.hooks) {
    const targetPath = entry.target ?? path.join(gitDir, 'hooks', entry.name);
    if (fs.existsSync(targetPath)) {
      fs.unlinkSync(targetPath);
    }
    if (entry.backup && fs.existsSync(entry.backup)) {
      const originalPath = path.join(gitDir, 'hooks', entry.name);
      fs.copyFileSync(entry.backup, originalPath);
      await chmod(originalPath, 0o755);
    }
  }

  const manifestPath = getManifestPath(repoRoot);
  if (fs.existsSync(manifestPath)) {
    fs.unlinkSync(manifestPath);
  }
}

export async function loadManifest(repoRoot: string): Promise<HookManifest | null> {
  const manifestPath = getManifestPath(repoRoot);
  if (!fs.existsSync(manifestPath)) {
    return null;
  }

  try {
    const data = await fs.promises.readFile(manifestPath, 'utf-8');
    const parsed = JSON.parse(data) as HookManifest;
    return parsed;
  } catch {
    return null;
  }
}

async function installHook(repoRoot: string, gitDir: string, hookName: string): Promise<HookManifestEntry> {
  const hooksDir = path.join(gitDir, 'hooks');
  await fs.promises.mkdir(hooksDir, { recursive: true });

  const templatePath = path.join(__dirname, 'templates', hookName);
  if (!fs.existsSync(templatePath)) {
    throw new Error(`Hook template not found: ${hookName}`);
  }

  const targetPath = path.join(gitDir, 'hooks', hookName);
  let backupPath: string | undefined;

  if (fs.existsSync(targetPath)) {
    const content = await fs.promises.readFile(targetPath, 'utf-8');
    if (!content.includes('SafeRun')) {
      const backupsDir = path.join(repoRoot, '.saferun', BACKUP_DIRNAME);
      await fs.promises.mkdir(backupsDir, { recursive: true });
      backupPath = path.join(backupsDir, `${hookName}-${Date.now()}.bak`);
      fs.copyFileSync(targetPath, backupPath);
    }
  }

  const template = await fs.promises.readFile(templatePath, 'utf-8');
  await fs.promises.writeFile(targetPath, renderTemplate(template), { mode: 0o755 });
  await chmod(targetPath, 0o755);

  return { name: hookName, target: targetPath, backup: backupPath };
}

function renderTemplate(template: string): string {
  return template.replace(/\{\{VERSION\}\}/g, getCliVersion());
}

function getManifestPath(repoRoot: string): string {
  return path.join(repoRoot, '.saferun', MANIFEST_FILENAME);
}

async function saveManifest(repoRoot: string, manifest: HookManifest): Promise<void> {
  const manifestPath = getManifestPath(repoRoot);
  await fs.promises.mkdir(path.dirname(manifestPath), { recursive: true });
  await fs.promises.writeFile(manifestPath, JSON.stringify(manifest, null, 2), 'utf-8');
}

function mergeManifestEntries(existing: HookManifestEntry[], installed: HookManifestEntry[]): HookManifestEntry[] {
  const entries = new Map<string, HookManifestEntry>();
  for (const entry of existing) {
    entries.set(entry.name, entry);
  }
  for (const entry of installed) {
    entries.set(entry.name, entry);
  }
  return Array.from(entries.values());
}
