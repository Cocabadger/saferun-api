/**
 * Global configuration management for SafeRun
 * Stores all rules, modes, and settings in ~/.saferun/config.yml
 * This config is NOT affected by git operations in any repository
 */

import fs from 'fs';
import path from 'path';
import os from 'os';
import { load as loadYaml, dump as dumpYaml } from 'js-yaml';
import {
  SafeRunConfig,
  ProtectionMode,
  ModeSettings,
  ApiConfig,
  OperationRuleConfig,
  ApprovalTimeoutConfig,
  TelemetryConfig,
} from './config';

const GLOBAL_CONFIG_DIR = path.join(os.homedir(), '.saferun');
const GLOBAL_CONFIG_FILE = path.join(GLOBAL_CONFIG_DIR, 'config.yml');

/**
 * Default global configuration
 * These are the baseline security settings
 */
export const DEFAULT_GLOBAL_CONFIG: SafeRunConfig = {
  mode: 'block', // Default to block mode for security
  modes: {
    monitor: {
      description: 'Log only, no blocking',
      block_operations: false,
      show_warnings: false,
      send_notifications: false,
      collect_metrics: true,
    },
    warn: {
      description: 'Show warnings but allow operations',
      block_operations: false,
      show_warnings: true,
      send_notifications: true,
      collect_metrics: true,
    },
    block: {
      description: 'Require approval for risky actions',
      block_operations: true,
      require_approval: true,
      collect_metrics: true,
    },
    enforce: {
      description: 'Strict blocking, maximum security',
      block_operations: true,
      require_approval: true,
      collect_metrics: true,
    },
  },
  api: {
    url: process.env.SAFERUN_API_URL ?? 'https://saferun-api.up.railway.app',
    timeout: 5000,
    retry_count: 3,
    fail_mode: 'strict',
    error_handling: {
      '403_forbidden': {
        action: 'block',
        message: '🚫 API limit exceeded - operations blocked for safety.',
      },
      '500_server_error': {
        action: 'block',
        message: '🚫 API temporarily unavailable - operation blocked for safety',
      },
      'network_error': {
        action: 'block',
        message: '🚫 Network error - operation blocked for safety',
      },
      'timeout': {
        action: 'block',
        message: '🚫 API timeout - operation blocked for safety',
      },
    },
  },
  github: {
    repo: 'auto',
    protected_branches: ['main', 'master', 'release/*', 'production'],
    branch_rules: [
      { pattern: 'feature/*', risk_level: 'low', allow_force_push: true },
      { pattern: 'hotfix/*', risk_level: 'medium', require_approval: false },
      { pattern: 'experiment/*', risk_level: 'low', skip_checks: true },
    ],
  },
  approval_timeout: {
    action: 'reject',
    duration: 7200, // 2 hours
    reminders: 3,
    reminder_interval: 1800,
  },
  rules: {
    force_push: {
      action: 'require_approval',
      risk_score: 8,
      timeout_action: 'reject',
      timeout_duration: 7200,
    },
    branch_delete: {
      action: 'require_approval',
      risk_score: 6,
      timeout_action: 'reject',
      timeout_duration: 7200,
      exclude_patterns: ['tmp/*', 'test/*'],
    },
    reset_hard: {
      action: 'require_approval',
      risk_score: 8,
      timeout_action: 'reject',
      timeout_duration: 7200,
      max_commits_back: 5,
    },
    clean: {
      action: 'require_approval',
      risk_score: 6,
      timeout_action: 'reject',
      timeout_duration: 3600,
    },
  },
  notifications: {
    slack: {
      enabled: true,
      channel: '#dev-safety',
    },
  },
  telemetry: {
    enabled: true,
    anonymous: true,
    events: [
      'operation_blocked',
      'operation_allowed',
      'approval_requested',
      'approval_granted',
      'installation',
      'uninstallation',
    ],
  },
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
 * Load global config (sync for performance in shell wrapper)
 */
export function loadGlobalConfigSync(): SafeRunConfig {
  try {
    if (!fs.existsSync(GLOBAL_CONFIG_FILE)) {
      return { ...DEFAULT_GLOBAL_CONFIG };
    }
    
    const content = fs.readFileSync(GLOBAL_CONFIG_FILE, 'utf-8');
    const parsed = loadYaml(content) as Partial<SafeRunConfig>;
    
    // Deep merge with defaults
    return mergeConfig(DEFAULT_GLOBAL_CONFIG, parsed);
  } catch {
    return { ...DEFAULT_GLOBAL_CONFIG };
  }
}

/**
 * Load global config (async version)
 */
export async function loadGlobalConfig(): Promise<SafeRunConfig> {
  return loadGlobalConfigSync();
}

/**
 * Save global config
 */
export async function saveGlobalConfig(config: SafeRunConfig): Promise<void> {
  ensureGlobalConfigDir();
  
  // Only save non-default values to keep file clean
  const content = dumpYaml(config, { lineWidth: 120 });
  await fs.promises.writeFile(GLOBAL_CONFIG_FILE, content, { mode: 0o600 });
}

/**
 * Update specific config values
 */
export async function updateGlobalConfig(updates: Partial<SafeRunConfig>): Promise<SafeRunConfig> {
  const current = await loadGlobalConfig();
  const updated = mergeConfig(current, updates);
  await saveGlobalConfig(updated);
  return updated;
}

/**
 * Set protection mode globally
 */
export async function setGlobalMode(mode: ProtectionMode): Promise<void> {
  const config = await loadGlobalConfig();
  config.mode = mode;
  await saveGlobalConfig(config);
}

/**
 * Get current protection mode
 */
export function getGlobalModeSync(): ProtectionMode {
  const config = loadGlobalConfigSync();
  return config.mode;
}

/**
 * Get rule for an operation
 */
export function getRuleSync(operation: string): OperationRuleConfig | undefined {
  const config = loadGlobalConfigSync();
  return config.rules[operation];
}

/**
 * Get current mode settings
 */
export function getModeSettingsSync(): ModeSettings {
  const config = loadGlobalConfigSync();
  return config.modes[config.mode] || config.modes['block'];
}

/**
 * Check if global config exists
 */
export function globalConfigExists(): boolean {
  return fs.existsSync(GLOBAL_CONFIG_FILE);
}

/**
 * Initialize global config with defaults if it doesn't exist
 */
export async function initGlobalConfig(): Promise<boolean> {
  if (globalConfigExists()) {
    return false; // Already exists
  }
  
  await saveGlobalConfig(DEFAULT_GLOBAL_CONFIG);
  return true;
}

/**
 * Deep merge configs (source overrides target)
 */
function mergeConfig(target: SafeRunConfig, source: Partial<SafeRunConfig>): SafeRunConfig {
  const result = { ...target };
  
  for (const [key, value] of Object.entries(source)) {
    if (value === undefined || value === null) continue;
    
    if (Array.isArray(value)) {
      (result as any)[key] = [...value];
    } else if (typeof value === 'object') {
      (result as any)[key] = mergeDeep((result as any)[key] || {}, value as Record<string, unknown>);
    } else {
      (result as any)[key] = value;
    }
  }
  
  return result;
}

/**
 * Deep merge any objects
 */
function mergeDeep(target: Record<string, unknown>, source: Record<string, unknown>): Record<string, unknown> {
  const result = { ...target };
  
  for (const [key, value] of Object.entries(source)) {
    if (value === undefined || value === null) continue;
    
    if (Array.isArray(value)) {
      result[key] = [...value];
    } else if (typeof value === 'object') {
      result[key] = mergeDeep((result[key] as Record<string, unknown>) || {}, value as Record<string, unknown>);
    } else {
      result[key] = value;
    }
  }
  
  return result;
}
