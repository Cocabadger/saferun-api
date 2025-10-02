import { SafeRunClient } from '@saferun/sdk';
import { SafeRunConfig } from './config';
import { OperationCache } from './cache';

export interface SafeRunClientContext {
  config: SafeRunConfig;
  cache?: OperationCache;
}

export function createSafeRunClient(context: SafeRunClientContext): any {
  const { config, cache } = context;

  const apiKey = resolveApiKey(config);
  const offlineMode = config.api.offline_mode;

  // If no API key and offline mode enabled, use offline client
  if (!apiKey && offlineMode?.enabled) {
    return new OfflineClient({
      cache,
      defaultAction: offlineMode.default_action ?? 'allow',
      cacheDuration: offlineMode.cache_duration ?? 3600,
    });
  }

  if (!apiKey) {
    throw new Error('SafeRun API key is not configured. Set SAFERUN_API_KEY env or update .saferun/config.yml');
  }

  const timeout = config.api.timeout ?? 2000;
  const retries = config.api.retry_count ?? 3;

  // Create online client, it will handle failures internally
  const client = new SafeRunClient({
    apiKey,
    apiUrl: config.api.url,
    timeout,
    maxRetries: retries,
  });

  // Wrap with offline fallback if enabled
  if (offlineMode?.enabled) {
    return new OnlineClientWithFallback(client, {
      cache,
      defaultAction: offlineMode.default_action ?? 'allow',
      cacheDuration: offlineMode.cache_duration ?? 3600,
    });
  }

  return client;
}

export function resolveApiKey(config: SafeRunConfig): string | undefined {
  if (config.api.key && config.api.key.length > 0 && !isEnvPlaceholder(config.api.key)) {
    return config.api.key;
  }

  if (process.env.SAFERUN_API_KEY && process.env.SAFERUN_API_KEY.length > 0) {
    return process.env.SAFERUN_API_KEY;
  }

  return undefined;
}

function isEnvPlaceholder(value: string): boolean {
  return value.includes('${') && value.includes('}');
}

/**
 * Online client with offline fallback
 */
class OnlineClientWithFallback {
  private onlineClient: SafeRunClient;
  private cache?: OperationCache;
  private defaultAction: 'allow' | 'deny' | 'cache';
  private cacheDuration: number;

  constructor(
    onlineClient: SafeRunClient,
    options: { cache?: OperationCache; defaultAction: 'allow' | 'deny' | 'cache'; cacheDuration: number }
  ) {
    this.onlineClient = onlineClient;
    this.cache = options.cache;
    this.defaultAction = options.defaultAction;
    this.cacheDuration = options.cacheDuration;
  }

  async gitOperation(params: any): Promise<any> {
    try {
      // Try online client first
      return await this.onlineClient.gitOperation(params);
    } catch (error) {
      // Fallback to offline mode
      console.warn('SafeRun API unavailable, using offline fallback');
      return this.handleOffline(params);
    }
  }

  async waitForApproval(changeId: string, options?: any): Promise<any> {
    try {
      return await this.onlineClient.waitForApproval(changeId, options);
    } catch (error) {
      throw new Error('Approval not available - API is offline');
    }
  }

  private async handleOffline(params: any): Promise<any> {
    // Try cache first
    if (this.cache && this.defaultAction === 'cache') {
      const cacheKey = this.cache.getOperationHash(params.operationType, [params.target], params.metadata);
      const cached = await this.cache.get(cacheKey);

      if (cached) {
        return {
          needsApproval: cached.result === 'dangerous',
          changeId: 'offline-cached',
          status: 'offline_cache',
        };
      }
    }

    // Use default action
    switch (this.defaultAction) {
      case 'allow':
        return {
          needsApproval: false,
          changeId: 'offline-allow',
          status: 'offline_allow',
        };
      case 'deny':
        return {
          needsApproval: true,
          changeId: 'offline-deny',
          status: 'offline_deny',
          humanPreview: 'Operation blocked - API unavailable and offline mode set to deny',
        };
      case 'cache':
        // Cache miss, default to deny for safety
        return {
          needsApproval: true,
          changeId: 'offline-cache-miss',
          status: 'offline_cache_miss',
          humanPreview: 'Operation requires approval - API unavailable and no cached decision',
        };
      default:
        return {
          needsApproval: false,
          changeId: 'offline-fallback',
          status: 'offline_fallback',
        };
    }
  }
}

/**
 * Offline client that uses cache and default policies
 */
export class OfflineClient {
  private cache?: OperationCache;
  private defaultAction: 'allow' | 'deny' | 'cache';
  private cacheDuration: number;

  constructor(options: { cache?: OperationCache; defaultAction: 'allow' | 'deny' | 'cache'; cacheDuration: number }) {
    this.cache = options.cache;
    this.defaultAction = options.defaultAction;
    this.cacheDuration = options.cacheDuration;
  }

  async gitOperation(params: any): Promise<any> {
    // Try to use cache first
    if (this.cache && this.defaultAction === 'cache') {
      const cacheKey = this.cache.getOperationHash(params.operationType, [params.target], params.metadata);
      const cached = await this.cache.get(cacheKey);

      if (cached) {
        return {
          needsApproval: cached.result === 'dangerous',
          changeId: 'offline-cached',
          status: 'offline_cache',
        };
      }
    }

    // Use default action
    switch (this.defaultAction) {
      case 'allow':
        return {
          needsApproval: false,
          changeId: 'offline-allow',
          status: 'offline_allow',
        };
      case 'deny':
        return {
          needsApproval: true,
          changeId: 'offline-deny',
          status: 'offline_deny',
          humanPreview: 'Operation blocked - API unavailable and offline mode set to deny',
        };
      case 'cache':
        // Cache miss, default to deny for safety
        return {
          needsApproval: true,
          changeId: 'offline-cache-miss',
          status: 'offline_cache_miss',
          humanPreview: 'Operation requires approval - API unavailable and no cached decision',
        };
      default:
        return {
          needsApproval: false,
          changeId: 'offline-fallback',
          status: 'offline_fallback',
        };
    }
  }

  async waitForApproval(): Promise<any> {
    throw new Error('Approval not available in offline mode');
  }
}
