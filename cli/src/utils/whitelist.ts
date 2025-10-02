/**
 * Self-training Whitelist
 * Allows users to whitelist known safe bots/agents to reduce noise
 */

import fs from 'fs';
import path from 'path';
import { load as loadYaml, dump as dumpYaml } from 'js-yaml';

export interface WhitelistEntry {
  type: 'ci' | 'bot' | 'automation' | 'agent';
  identifier: string; // e.g., "renovate[bot]", "jenkins", "n8n"
  scope?: string; // Optional scope (e.g., "branch:feature/*")
  reason?: string;
  added_at: string;
  added_by?: string;
}

export interface Whitelist {
  entries: WhitelistEntry[];
}

const WHITELIST_FILE = 'whitelist.yml';

/**
 * Load whitelist from .saferun/whitelist.yml
 */
export async function loadWhitelist(repoRoot: string): Promise<Whitelist> {
  const whitelistPath = path.join(repoRoot, '.saferun', WHITELIST_FILE);

  if (!fs.existsSync(whitelistPath)) {
    return { entries: [] };
  }

  try {
    const content = fs.readFileSync(whitelistPath, 'utf-8');
    const data = loadYaml(content) as Whitelist;
    return data || { entries: [] };
  } catch {
    return { entries: [] };
  }
}

/**
 * Save whitelist to .saferun/whitelist.yml
 */
export async function saveWhitelist(repoRoot: string, whitelist: Whitelist): Promise<void> {
  const whitelistPath = path.join(repoRoot, '.saferun', WHITELIST_FILE);
  const saferunDir = path.dirname(whitelistPath);

  if (!fs.existsSync(saferunDir)) {
    fs.mkdirSync(saferunDir, { recursive: true });
  }

  const content = dumpYaml(whitelist, { lineWidth: 120 });
  fs.writeFileSync(whitelistPath, content, 'utf-8');
}

/**
 * Add entry to whitelist
 */
export async function addToWhitelist(
  repoRoot: string,
  entry: Omit<WhitelistEntry, 'added_at' | 'added_by'>
): Promise<void> {
  const whitelist = await loadWhitelist(repoRoot);

  const fullEntry: WhitelistEntry = {
    ...entry,
    added_at: new Date().toISOString(),
    added_by: process.env.USER || process.env.USERNAME || 'unknown',
  };

  // Check if already exists
  const exists = whitelist.entries.some(
    (e) => e.type === fullEntry.type && e.identifier === fullEntry.identifier && e.scope === fullEntry.scope
  );

  if (!exists) {
    whitelist.entries.push(fullEntry);
    await saveWhitelist(repoRoot, whitelist);
  }
}

/**
 * Remove entry from whitelist
 */
export async function removeFromWhitelist(repoRoot: string, identifier: string): Promise<boolean> {
  const whitelist = await loadWhitelist(repoRoot);
  const initialLength = whitelist.entries.length;

  whitelist.entries = whitelist.entries.filter((e) => e.identifier !== identifier);

  if (whitelist.entries.length < initialLength) {
    await saveWhitelist(repoRoot, whitelist);
    return true;
  }

  return false;
}

/**
 * Check if identifier is whitelisted
 */
export async function isWhitelisted(
  repoRoot: string,
  type: WhitelistEntry['type'],
  identifier: string,
  scope?: string
): Promise<boolean> {
  const whitelist = await loadWhitelist(repoRoot);

  return whitelist.entries.some((entry) => {
    if (entry.type !== type) return false;
    if (entry.identifier !== identifier) return false;

    // If scope is specified, check it matches
    if (scope && entry.scope) {
      return matchScope(scope, entry.scope);
    }

    return true;
  });
}

/**
 * Match scope pattern (e.g., "branch:feature/*")
 */
function matchScope(actual: string, pattern: string): boolean {
  // Simple wildcard matching
  const regex = new RegExp('^' + pattern.replace(/\*/g, '.*') + '$');
  return regex.test(actual);
}

/**
 * List all whitelist entries
 */
export async function listWhitelist(repoRoot: string): Promise<WhitelistEntry[]> {
  const whitelist = await loadWhitelist(repoRoot);
  return whitelist.entries;
}

/**
 * Check if git author is whitelisted
 */
export async function isGitAuthorWhitelisted(repoRoot: string, name: string, email: string): Promise<boolean> {
  // Check bot whitelist
  if (await isWhitelisted(repoRoot, 'bot', name)) return true;
  if (await isWhitelisted(repoRoot, 'bot', email)) return true;

  // Check if name matches bot pattern but is whitelisted
  const nameLower = name.toLowerCase();
  const emailLower = email.toLowerCase();

  if (nameLower.includes('[bot]') || emailLower.includes('bot@')) {
    // Extract bot name (e.g., "renovate[bot]" -> "renovate")
    const botName = name.match(/(.+?)\[bot\]/)?.[1] || name;
    return await isWhitelisted(repoRoot, 'bot', botName);
  }

  return false;
}