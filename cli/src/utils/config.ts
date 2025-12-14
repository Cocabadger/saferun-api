import fs from 'fs';
import path from 'path';
import { load as loadYaml, dump as dumpYaml } from 'js-yaml';
import { getRepositoryRoot, ensureDir } from './git';

export const CONFIG_DIR_NAME = '.saferun';
export const CONFIG_FILE_NAME = 'config.yml';

export type ProtectionMode = 'monitor' | 'warn' | 'block' | 'enforce';

export interface ModeSettings {
  description?: string;
  block_operations?: boolean;
  show_warnings?: boolean;
  send_notifications?: boolean;
  collect_metrics?: boolean;
  require_approval?: boolean;
  // SECURITY: allow_bypass and bypass_methods removed.
  // Protection is now based ONLY on mode selection.
}

// SECURITY: OfflineModeConfig removed - offline mode is a security vulnerability
// AI agents can manipulate env vars/config to bypass protection

export type FailMode = 'strict' | 'graceful' | 'permissive';
export type ErrorAction = 'block' | 'warn' | 'allow';

export interface ErrorHandlingConfig {
  action: ErrorAction;
  message: string;
}

export interface ErrorHandlingSettings {
  '403_forbidden': ErrorHandlingConfig;
  '500_server_error': ErrorHandlingConfig;
  'network_error': ErrorHandlingConfig;
  'timeout': ErrorHandlingConfig;
}

export interface ApiConfig {
  url: string;
  key?: string;
  timeout?: number;
  retry_count?: number;
  // SECURITY: offline_mode removed - agents can manipulate it to bypass protection
  fail_mode?: FailMode;
  error_handling?: ErrorHandlingSettings;
}

export interface BranchRuleConfig {
  pattern: string;
  risk_level?: 'low' | 'medium' | 'high';
  require_approval?: boolean;
  allow_force_push?: boolean;
  skip_checks?: boolean;
}

export interface GithubConfig {
  repo: string;
  protected_branches: string[];
  branch_rules?: BranchRuleConfig[];
}

export interface OperationRuleConfig {
  action?: 'allow' | 'warn' | 'require_approval' | 'block';
  risk_score?: number;
  timeout_action?: 'reject' | 'allow' | 'ask';
  timeout_duration?: number;
  // bypass_roles removed - no bypass mechanism
  exclude_patterns?: string[];
  max_commits_back?: number;
}

// SECURITY: CIEnvironmentConfig and BypassConfig interfaces removed.
// Bypass functionality eliminated - protection based solely on mode selection.

export interface ApprovalTimeoutConfig {
  action: 'reject' | 'allow' | 'ask';
  duration: number;
  reminders: number;
  reminder_interval: number;
}

export interface TelemetryConfig {
  enabled?: boolean;
  anonymous?: boolean;
  events?: string[];
  local_logs?: {
    enabled?: boolean;
    path?: string;
    rotation?: 'daily' | 'weekly' | 'monthly';
    retention?: number;
  };
}

export interface SafeRunConfig {
  mode: ProtectionMode;
  modes: Record<string, ModeSettings>;
  api: ApiConfig;
  github: GithubConfig;
  approval_timeout?: ApprovalTimeoutConfig;
  rules: Record<string, OperationRuleConfig>;
  // SECURITY: bypass field removed
  notifications?: Record<string, unknown>;
  telemetry?: TelemetryConfig;
  commands?: Record<string, unknown>;
}

const DEFAULT_CONFIG: SafeRunConfig = {
  mode: 'monitor',
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
    key: process.env.SAFERUN_API_KEY,
    timeout: 5000,
    retry_count: 3,
    // SECURITY: offline_mode removed - API unavailable = operations blocked
    // SECURITY: fail_mode changed to 'strict' - block on any API error
    fail_mode: 'strict',
    error_handling: {
      '403_forbidden': {
        action: 'block',
        message: '🚫 API limit exceeded - operations blocked for safety.\n\nOptions:\n  • Upgrade your plan at https://saferun-landing.vercel.app\n  • Wait for limit reset (resets monthly)\n  • Uninstall completely: npx saferun uninstall',
      },
      '500_server_error': {
        action: 'block',
        message: '🚫 API temporarily unavailable - operation blocked for safety',
      },
      'network_error': {
        action: 'block',
        message: '🚫 Network error - operation blocked for safety (API unreachable)',
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
    duration: 7200,
    reminders: 3,
    reminder_interval: 1800,
  },
  rules: {
    force_push: {
      action: (process.env.FORCE_PUSH_ACTION as OperationRuleConfig['action']) ?? 'require_approval',
      risk_score: 8,
      timeout_action: 'reject',
      timeout_duration: 7200,
      // bypass_roles removed
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
  // SECURITY: bypass config removed
  notifications: {
    slack: {
      enabled: true,
      webhook_url: process.env.SLACK_WEBHOOK_URL,
      channel: process.env.SLACK_CHANNEL ?? '#dev-safety',
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
      // 'bypass_used' - removed (bypass functionality eliminated)
      'installation',
      'uninstallation',
    ],
    local_logs: {
      enabled: true,
      path: '.saferun/logs',
      rotation: 'daily',
      retention: 30,
    },
  },
};

export interface ConfigPaths {
  repoRoot: string;
  configDir: string;
  configPath: string;
}

const configCache = new Map<string, SafeRunConfig>();

export async function resolveConfigPaths(cwd = process.cwd()): Promise<ConfigPaths | null> {
  const repoRoot = await getRepositoryRoot(cwd);
  if (!repoRoot) {
    return null;
  }

  const configDir = path.join(repoRoot, CONFIG_DIR_NAME);
  const configPath = path.join(configDir, CONFIG_FILE_NAME);
  return { repoRoot, configDir, configPath };
}

export async function loadConfig(cwd = process.cwd(), options: { allowCreate?: boolean } = {}): Promise<SafeRunConfig> {
  const paths = await resolveConfigPaths(cwd);
  if (!paths) {
    throw new Error('SafeRun CLI must be executed inside a git repository');
  }

  const cacheKey = paths.configPath;
  if (configCache.has(cacheKey)) {
    return configCache.get(cacheKey)!;
  }

  let fileConfig: SafeRunConfig | undefined;
  if (fs.existsSync(paths.configPath)) {
    const fileContents = await fs.promises.readFile(paths.configPath, 'utf-8');
    const parsed = loadYaml(fileContents) as SafeRunConfig | undefined;
    if (parsed) {
      fileConfig = parsed;
    }
  } else if (options.allowCreate) {
    await ensureDir(paths.configDir);
    await saveConfig(DEFAULT_CONFIG, paths.repoRoot);
    fileConfig = DEFAULT_CONFIG;
  }

  const merged = mergeDeep(copyConfig(DEFAULT_CONFIG), fileConfig ?? {});
  const resolved = resolveEnvPlaceholders(merged);
  configCache.set(cacheKey, resolved);
  return resolved;
}

export async function saveConfig(config: SafeRunConfig, repoRoot?: string): Promise<void> {
  const paths = repoRoot
    ? {
        repoRoot,
        configDir: path.join(repoRoot, CONFIG_DIR_NAME),
        configPath: path.join(repoRoot, CONFIG_DIR_NAME, CONFIG_FILE_NAME),
      }
    : await resolveConfigPaths();

  if (!paths) {
    throw new Error('Unable to locate repository root for SafeRun configuration');
  }

  await ensureDir(paths.configDir);
  const data = dumpYaml(config, { lineWidth: 120 });
  await fs.promises.writeFile(paths.configPath, data, 'utf-8');
  configCache.set(paths.configPath, config);
}

export function setConfigValue(config: SafeRunConfig, dotPath: string, value: unknown): SafeRunConfig {
  const segments = dotPath.split('.');
  let current: any = config;

  for (let i = 0; i < segments.length; i += 1) {
    const key = segments[i];
    if (i === segments.length - 1) {
      current[key] = value;
    } else {
      if (typeof current[key] !== 'object' || current[key] === null) {
        current[key] = {};
      }
      current = current[key];
    }
  }

  return config;
}

export function getConfigValue<T>(config: SafeRunConfig, dotPath: string): T | undefined {
  const segments = dotPath.split('.');
  let current: any = config;

  for (const segment of segments) {
    if (current == null || typeof current !== 'object') {
      return undefined;
    }
    current = current[segment];
  }

  return current as T | undefined;
}

function mergeDeep<T extends Record<string, any>>(target: T, source: Record<string, any>): T {
  for (const [key, value] of Object.entries(source)) {
    if (Array.isArray(value)) {
      (target as any)[key] = Array.isArray((target as any)[key]) ? value : [...value];
      continue;
    }

    if (value && typeof value === 'object') {
      (target as any)[key] = mergeDeep((target as any)[key] ?? {}, value);
      continue;
    }

    (target as any)[key] = value;
  }
  return target;
}

function copyConfig(config: SafeRunConfig): SafeRunConfig {
  return JSON.parse(JSON.stringify(config)) as SafeRunConfig;
}

function resolveEnvPlaceholders(config: SafeRunConfig): SafeRunConfig {
  const replacer = (value: unknown): unknown => {
    if (typeof value === 'string') {
      return value.replace(/\$\{([A-Z0-9_]+)(?::-(.*?))?}/g, (_, envVar: string, fallback?: string) => {
        const envValue = process.env[envVar];
        if (envValue && envValue.length > 0) {
          return envValue;
        }
        return fallback ?? '';
      });
    }

    if (Array.isArray(value)) {
      return value.map((item) => replacer(item));
    }

    if (value && typeof value === 'object') {
      for (const [key, child] of Object.entries(value)) {
        (value as any)[key] = replacer(child);
      }
    }

    return value;
  };

  return replacer(config) as SafeRunConfig;
}
