/**
 * Lazy Background Sync
 * 
 * Architecture:
 * - Local-First: Hooks always read from local .saferun.yml (0ms latency)
 * - Background Update: CLI commands sync if cache is stale (>5 min)
 * - Banking Grade: Silent detached sync for stale cache, warning only if VERY stale (>30 days)
 */

import { loadConfig, saveConfig, SafeRunConfig } from './config';
import { loadGlobalConfig, saveGlobalConfig } from './global-config';
import { getGitInfo, isGitRepository } from './git';
import { resolveApiKey } from './api-client';
import chalk from 'chalk';

const SYNC_INTERVAL_MS = 5 * 60 * 1000;  // 5 minutes
// Banking Grade: Warning only if no connection for a month (vacation, etc.)
// For everything else - silent detached sync handles it
export const STALE_WARNING_MS = 30 * 24 * 60 * 60 * 1000; // 30 days

export interface SyncResult {
  success: boolean;
  updated: boolean;
  message: string;
  protectedBranches?: string[];
}

/**
 * Check if local config is stale (needs sync)
 */
export function isConfigStale(config: SafeRunConfig, thresholdMs: number = SYNC_INTERVAL_MS): boolean {
  if (!config.sync?.last_sync_at) {
    return true; // Never synced
  }
  
  const lastSync = new Date(config.sync.last_sync_at).getTime();
  const now = Date.now();
  
  return (now - lastSync) > thresholdMs;
}

/**
 * Check if config is very stale (show warning in hooks)
 */
export function isConfigVeryStale(config: SafeRunConfig): boolean {
  return isConfigStale(config, STALE_WARNING_MS);
}

/**
 * Get age of config in human readable format
 */
export function getConfigAge(config: SafeRunConfig): string {
  if (!config.sync?.last_sync_at) {
    return 'never synced';
  }
  
  const lastSync = new Date(config.sync.last_sync_at).getTime();
  const ageMs = Date.now() - lastSync;
  
  const minutes = Math.floor(ageMs / 60000);
  const hours = Math.floor(minutes / 60);
  const days = Math.floor(hours / 24);
  
  if (days > 0) return `${days} day(s) ago`;
  if (hours > 0) return `${hours} hour(s) ago`;
  if (minutes > 0) return `${minutes} minute(s) ago`;
  return 'just now';
}

/**
 * Sync protected branches from API to local config
 */
export async function syncProtectedBranches(
  apiUrl: string,
  apiKey: string,
  repoRoot: string
): Promise<SyncResult> {
  try {
    const response = await fetch(`${apiUrl}/v1/settings/protected-branches`, {
      headers: {
        'X-API-Key': apiKey,
      },
    });

    if (!response.ok) {
      if (response.status === 404) {
        // No settings yet - use defaults
        return {
          success: true,
          updated: false,
          message: 'No server settings found, using defaults',
          protectedBranches: ['main', 'master'],
        };
      }
      return {
        success: false,
        updated: false,
        message: `API error: ${response.status}`,
      };
    }

    const data = await response.json();
    const serverBranches = data.patterns || ['main', 'master'];

    // Load GLOBAL config (hooks read from global, not repo-local)
    const config = await loadGlobalConfig();
    const localBranches = config.github?.protected_branches || [];

    // Check if update needed
    const needsUpdate = JSON.stringify(serverBranches.sort()) !== JSON.stringify([...localBranches].sort());

    // Update global config
    config.github = config.github || { repo: 'auto', protected_branches: [] };
    config.github.protected_branches = serverBranches;
    config.sync = {
      last_sync_at: new Date().toISOString(),
      sync_source: 'api',
    };

    await saveGlobalConfig(config);

    // Also update repo-local config so hooks see fresh timestamp
    const repoConfig = await loadConfig(repoRoot, { allowCreate: false });
    if (repoConfig) {
      repoConfig.github = repoConfig.github || { repo: 'auto', protected_branches: [] };
      repoConfig.github.protected_branches = serverBranches;
      repoConfig.sync = {
        last_sync_at: new Date().toISOString(),
        sync_source: 'api',
      };
      await saveConfig(repoConfig, repoRoot);
    }

    return {
      success: true,
      updated: needsUpdate,
      message: needsUpdate 
        ? `Synced ${serverBranches.length} protected branch(es) from server`
        : 'Already up to date',
      protectedBranches: serverBranches,
    };
  } catch (error) {
    return {
      success: false,
      updated: false,
      message: `Sync failed: ${error}`,
    };
  }
}

/**
 * Background sync - runs silently if config is stale
 * Returns true if sync was performed
 */
export async function backgroundSync(silent: boolean = true): Promise<boolean> {
  try {
    const isRepo = await isGitRepository();
    if (!isRepo) return false;

    const gitInfo = await getGitInfo();
    if (!gitInfo) return false;

    const config = await loadConfig(gitInfo.repoRoot, { allowCreate: false });
    if (!config) return false;

    // Check if sync needed
    if (!isConfigStale(config)) {
      return false;
    }

    const apiKey = resolveApiKey(config);
    if (!apiKey) return false;

    const apiUrl = config.api?.url || 'https://saferun-api.up.railway.app';

    const result = await syncProtectedBranches(apiUrl, apiKey, gitInfo.repoRoot);

    if (!silent && result.updated) {
      console.log(chalk.gray(`🔄 Background sync: ${result.message}`));
    }

    return result.success;
  } catch {
    return false;
  }
}

/**
 * Print sync status message (positive UX)
 * Shows green checkmark if recently synced, warning only if very stale (>30 days)
 * 
 * Banking Grade: Silent by default. Background sync handles everything.
 * Warning only if user hasn't connected for 30+ days (vacation, etc.)
 */
export function printSyncStatus(config: SafeRunConfig): void {
  if (!config.sync?.last_sync_at) {
    // Never synced - but background sync will handle it automatically
    // No need to show warning - detached sync is triggered right after this
    return;
  }

  const lastSync = new Date(config.sync.last_sync_at).getTime();
  const ageMs = Date.now() - lastSync;

  // Banking Grade: Only warn if config is VERY stale (>30 days)
  // Everything else is handled silently by background sync
  if (ageMs > STALE_WARNING_MS) {
    const age = getConfigAge(config);
    console.log(chalk.yellow(`⚠️  SafeRun: Config outdated (synced ${age}). Run `) + chalk.white(`'saferun sync'`) + chalk.yellow(` to update.`));
  }
  // Otherwise - stay silent. Background sync handles freshness.
}
