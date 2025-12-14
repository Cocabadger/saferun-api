/**
 * Protected repositories registry
 * Stores list of protected repos in ~/.saferun/protected-repos.json
 * This is invisible to AI agents and cannot be modified through git operations
 */

import fs from 'fs';
import path from 'path';
import os from 'os';

const GLOBAL_CONFIG_DIR = path.join(os.homedir(), '.saferun');
const PROTECTED_REPOS_FILE = path.join(GLOBAL_CONFIG_DIR, 'protected-repos.json');

export interface ProtectedRepo {
  path: string;           // Absolute path to repo
  name?: string;          // Optional friendly name (e.g., "my-app")
  github?: string;        // GitHub repo slug (e.g., "owner/repo")
  addedAt: string;        // ISO timestamp
  mode?: string;          // Protection mode override for this repo
}

export interface ProtectedReposRegistry {
  version: number;
  repos: ProtectedRepo[];
}

const DEFAULT_REGISTRY: ProtectedReposRegistry = {
  version: 1,
  repos: [],
};

/**
 * Ensure global config directory exists
 */
function ensureGlobalConfigDir(): void {
  if (!fs.existsSync(GLOBAL_CONFIG_DIR)) {
    fs.mkdirSync(GLOBAL_CONFIG_DIR, { mode: 0o700, recursive: true });
  }
}

/**
 * Load protected repos registry (sync for shell wrapper performance)
 */
export function loadProtectedReposSync(): ProtectedReposRegistry {
  try {
    if (!fs.existsSync(PROTECTED_REPOS_FILE)) {
      return DEFAULT_REGISTRY;
    }
    
    const content = fs.readFileSync(PROTECTED_REPOS_FILE, 'utf-8');
    const registry = JSON.parse(content) as ProtectedReposRegistry;
    
    // Migration: ensure version field
    if (!registry.version) {
      registry.version = 1;
    }
    
    return registry;
  } catch {
    return DEFAULT_REGISTRY;
  }
}

/**
 * Load protected repos registry (async version)
 */
export async function loadProtectedRepos(): Promise<ProtectedReposRegistry> {
  return loadProtectedReposSync();
}

/**
 * Save protected repos registry
 */
export async function saveProtectedRepos(registry: ProtectedReposRegistry): Promise<void> {
  ensureGlobalConfigDir();
  
  const content = JSON.stringify(registry, null, 2);
  await fs.promises.writeFile(PROTECTED_REPOS_FILE, content, { mode: 0o600 });
}

/**
 * Normalize path for comparison (resolve symlinks, remove trailing slashes)
 */
function normalizePath(p: string): string {
  try {
    // Resolve to absolute path and remove trailing slashes
    const resolved = path.resolve(p);
    return resolved.replace(/\/+$/, '');
  } catch {
    return p.replace(/\/+$/, '');
  }
}

/**
 * Check if a path is protected (sync for shell wrapper)
 */
export function isRepoProtectedSync(repoPath: string): boolean {
  const registry = loadProtectedReposSync();
  const normalizedPath = normalizePath(repoPath);
  
  return registry.repos.some(repo => normalizePath(repo.path) === normalizedPath);
}

/**
 * Check if a path is protected (async version)
 */
export async function isRepoProtected(repoPath: string): Promise<boolean> {
  return isRepoProtectedSync(repoPath);
}

/**
 * Get protected repo info by path
 */
export function getProtectedRepoSync(repoPath: string): ProtectedRepo | undefined {
  const registry = loadProtectedReposSync();
  const normalizedPath = normalizePath(repoPath);
  
  return registry.repos.find(repo => normalizePath(repo.path) === normalizedPath);
}

/**
 * Get protected repo info by path (async version)
 */
export async function getProtectedRepo(repoPath: string): Promise<ProtectedRepo | undefined> {
  return getProtectedRepoSync(repoPath);
}

/**
 * Register a repository as protected
 */
export async function registerProtectedRepo(
  repoPath: string,
  options: { name?: string; github?: string; mode?: string } = {}
): Promise<void> {
  const registry = await loadProtectedRepos();
  const normalizedPath = normalizePath(repoPath);
  
  // Check if already registered
  const existingIndex = registry.repos.findIndex(
    repo => normalizePath(repo.path) === normalizedPath
  );
  
  const newRepo: ProtectedRepo = {
    path: normalizedPath,
    name: options.name,
    github: options.github,
    addedAt: new Date().toISOString(),
    mode: options.mode,
  };
  
  if (existingIndex >= 0) {
    // Update existing
    registry.repos[existingIndex] = {
      ...registry.repos[existingIndex],
      ...newRepo,
      addedAt: registry.repos[existingIndex].addedAt, // Keep original addedAt
    };
  } else {
    // Add new
    registry.repos.push(newRepo);
  }
  
  await saveProtectedRepos(registry);
}

/**
 * Unregister a repository (remove protection)
 */
export async function unregisterProtectedRepo(repoPath: string): Promise<boolean> {
  const registry = await loadProtectedRepos();
  const normalizedPath = normalizePath(repoPath);
  
  const initialLength = registry.repos.length;
  registry.repos = registry.repos.filter(
    repo => normalizePath(repo.path) !== normalizedPath
  );
  
  if (registry.repos.length < initialLength) {
    await saveProtectedRepos(registry);
    return true;
  }
  
  return false;
}

/**
 * List all protected repositories
 */
export async function listProtectedRepos(): Promise<ProtectedRepo[]> {
  const registry = await loadProtectedRepos();
  return registry.repos;
}

/**
 * Update protection mode for a repo
 */
export async function updateRepoMode(repoPath: string, mode: string): Promise<boolean> {
  const registry = await loadProtectedRepos();
  const normalizedPath = normalizePath(repoPath);
  
  const repo = registry.repos.find(r => normalizePath(r.path) === normalizedPath);
  if (repo) {
    repo.mode = mode;
    await saveProtectedRepos(registry);
    return true;
  }
  
  return false;
}
