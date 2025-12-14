import { SafeRunClient } from '@saferun/sdk';
import { SafeRunConfig } from './config';
import { loadGlobalCredentialsSync } from './credentials';

export interface SafeRunClientContext {
  config: SafeRunConfig;
}

/**
 * Creates a SafeRun API client.
 * 
 * SECURITY: No offline mode - if API is unavailable, operations are blocked.
 * This prevents AI agents from bypassing protection by manipulating
 * environment variables or config files to enable offline "allow" mode.
 */
export function createSafeRunClient(context: SafeRunClientContext): SafeRunClient {
  const { config } = context;

  const apiKey = resolveApiKey(config);

  if (!apiKey) {
    throw new Error('SafeRun API key is not configured. Set SAFERUN_API_KEY env or update .saferun/config.yml');
  }

  const timeout = config.api.timeout ?? 5000;
  const retries = config.api.retry_count ?? 3;

  return new SafeRunClient({
    apiKey,
    apiUrl: config.api.url,
    timeout,
    maxRetries: retries,
  });
}

export function resolveApiKey(config: SafeRunConfig): string | undefined {
  // 1. Check global credentials (~/.saferun/credentials) - HIGHEST PRIORITY
  //    This is set by the wizard and is the source of truth
  const globalCreds = loadGlobalCredentialsSync();
  if (globalCreds.api_key) {
    return globalCreds.api_key;
  }

  // 2. Check environment variable
  if (process.env.SAFERUN_API_KEY && process.env.SAFERUN_API_KEY.length > 0) {
    return process.env.SAFERUN_API_KEY;
  }

  // 3. Fall back to local config (may be outdated)
  if (config.api.key && config.api.key.length > 0 && !isEnvPlaceholder(config.api.key)) {
    return config.api.key;
  }

  return undefined;
}

function isEnvPlaceholder(value: string): boolean {
  return value.includes('${') && value.includes('}');
}
