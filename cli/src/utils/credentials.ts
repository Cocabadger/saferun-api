/**
 * Global credentials management for SafeRun
 * Stores API key in ~/.saferun/credentials with secure permissions
 */

import fs from 'fs';
import path from 'path';
import os from 'os';

const GLOBAL_CONFIG_DIR = path.join(os.homedir(), '.saferun');
const CREDENTIALS_FILE = path.join(GLOBAL_CONFIG_DIR, 'credentials');
const GLOBAL_CONFIG_FILE = path.join(GLOBAL_CONFIG_DIR, 'config.yml');

export interface GlobalCredentials {
  api_key?: string;
  created_at?: string;
  updated_at?: string;
}

/**
 * Ensure global config directory exists with secure permissions
 */
export async function ensureGlobalConfigDir(): Promise<void> {
  if (!fs.existsSync(GLOBAL_CONFIG_DIR)) {
    await fs.promises.mkdir(GLOBAL_CONFIG_DIR, { mode: 0o700, recursive: true });
  }
}

/**
 * Load credentials from global config (sync version for use in api-client)
 */
export function loadGlobalCredentialsSync(): GlobalCredentials {
  try {
    if (!fs.existsSync(CREDENTIALS_FILE)) {
      return {};
    }
    
    const content = fs.readFileSync(CREDENTIALS_FILE, 'utf-8');
    const credentials: GlobalCredentials = {};
    
    for (const line of content.split('\n')) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith('#')) continue;
      
      const [key, ...valueParts] = trimmed.split('=');
      const value = valueParts.join('=').trim();
      
      if (key === 'api_key' || key === 'SAFERUN_API_KEY') {
        credentials.api_key = value;
      } else if (key === 'created_at') {
        credentials.created_at = value;
      } else if (key === 'updated_at') {
        credentials.updated_at = value;
      }
    }
    
    return credentials;
  } catch {
    return {};
  }
}

/**
 * Load credentials from global config
 */
export async function loadGlobalCredentials(): Promise<GlobalCredentials> {
  try {
    await ensureGlobalConfigDir();
    
    if (!fs.existsSync(CREDENTIALS_FILE)) {
      return {};
    }
    
    const content = await fs.promises.readFile(CREDENTIALS_FILE, 'utf-8');
    const credentials: GlobalCredentials = {};
    
    // Simple key=value format (not YAML to avoid dependencies)
    for (const line of content.split('\n')) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith('#')) continue;
      
      const [key, ...valueParts] = trimmed.split('=');
      const value = valueParts.join('=').trim();
      
      if (key === 'api_key' || key === 'SAFERUN_API_KEY') {
        credentials.api_key = value;
      } else if (key === 'created_at') {
        credentials.created_at = value;
      } else if (key === 'updated_at') {
        credentials.updated_at = value;
      }
    }
    
    return credentials;
  } catch {
    return {};
  }
}

/**
 * Save credentials to global config with secure permissions
 */
export async function saveGlobalCredentials(credentials: GlobalCredentials): Promise<void> {
  await ensureGlobalConfigDir();
  
  const now = new Date().toISOString();
  const existing = await loadGlobalCredentials();
  
  const content = [
    '# SafeRun Global Credentials',
    '# This file contains sensitive data - DO NOT COMMIT',
    `# Created: ${existing.created_at || now}`,
    `# Updated: ${now}`,
    '',
    `api_key=${credentials.api_key || ''}`,
    `created_at=${existing.created_at || now}`,
    `updated_at=${now}`,
    '',
  ].join('\n');
  
  await fs.promises.writeFile(CREDENTIALS_FILE, content, { mode: 0o600 });
}

/**
 * Get API key from (in order of priority):
 * 1. Environment variable SAFERUN_API_KEY
 * 2. Global credentials file ~/.saferun/credentials
 * 3. Local config file .saferun/config.yml
 */
export async function resolveApiKey(localApiKey?: string): Promise<string | undefined> {
  // 1. Environment variable has highest priority
  if (process.env.SAFERUN_API_KEY) {
    return process.env.SAFERUN_API_KEY;
  }
  
  // 2. Global credentials
  const globalCreds = await loadGlobalCredentials();
  if (globalCreds.api_key) {
    return globalCreds.api_key;
  }
  
  // 3. Local config (passed in)
  if (localApiKey) {
    return localApiKey;
  }
  
  return undefined;
}

/**
 * Check if API key is configured anywhere
 */
export async function hasApiKey(): Promise<boolean> {
  const key = await resolveApiKey();
  return !!key;
}

/**
 * Validate API key format
 */
export function isValidApiKeyFormat(key: string): boolean {
  // SafeRun API keys start with 'sr_' and are at least 20 chars
  return key.startsWith('sr_') && key.length >= 20;
}

/**
 * Mask API key for display (show first 8 and last 4 chars)
 */
export function maskApiKey(key: string): string {
  if (key.length < 16) return '***';
  return `${key.substring(0, 8)}...${key.substring(key.length - 4)}`;
}

/**
 * Get global config directory path
 */
export function getGlobalConfigDir(): string {
  return GLOBAL_CONFIG_DIR;
}

/**
 * Get credentials file path
 */
export function getCredentialsPath(): string {
  return CREDENTIALS_FILE;
}
