/**
 * .gitignore management for SafeRun
 * Ensures sensitive files are never committed
 */

import fs from 'fs';
import path from 'path';

const SAFERUN_GITIGNORE_ENTRIES = [
  '',
  '# SafeRun - security (never commit credentials)',
  '.saferun/credentials',
  '.saferun/secrets/',
  '',
  '# SafeRun - local cache and logs',
  '.saferun/cache/',
  '.saferun/*.log',
  '.saferun/logs/',
];

const REQUIRED_ENTRIES = [
  '.saferun/credentials',
  '.saferun/secrets/',
  '.saferun/cache/',
  '.saferun/*.log',
];

export interface GitignoreCheckResult {
  exists: boolean;
  hasSaferunEntries: boolean;
  missingEntries: string[];
  path: string;
}

/**
 * Check if .gitignore exists and has SafeRun entries
 */
export async function checkGitignore(repoRoot: string): Promise<GitignoreCheckResult> {
  const gitignorePath = path.join(repoRoot, '.gitignore');
  
  const result: GitignoreCheckResult = {
    exists: false,
    hasSaferunEntries: false,
    missingEntries: [],
    path: gitignorePath,
  };
  
  if (!fs.existsSync(gitignorePath)) {
    result.missingEntries = [...REQUIRED_ENTRIES];
    return result;
  }
  
  result.exists = true;
  
  try {
    const content = await fs.promises.readFile(gitignorePath, 'utf-8');
    const lines = content.split('\n').map(l => l.trim());
    
    // Check each required entry
    for (const entry of REQUIRED_ENTRIES) {
      const found = lines.some(line => {
        // Exact match or pattern match
        if (line === entry) return true;
        // Check if .saferun/ is ignored entirely
        if (line === '.saferun/' || line === '.saferun') return true;
        // Check glob patterns
        if (entry.includes('*') && line === entry) return true;
        return false;
      });
      
      if (!found) {
        result.missingEntries.push(entry);
      }
    }
    
    result.hasSaferunEntries = result.missingEntries.length === 0;
    
    // Also check if entire .saferun is ignored (that's fine too)
    if (lines.includes('.saferun/') || lines.includes('.saferun')) {
      result.hasSaferunEntries = true;
      result.missingEntries = [];
    }
    
  } catch {
    result.missingEntries = [...REQUIRED_ENTRIES];
  }
  
  return result;
}

/**
 * Add SafeRun entries to .gitignore
 */
export async function addToGitignore(repoRoot: string): Promise<void> {
  const gitignorePath = path.join(repoRoot, '.gitignore');
  
  let content = '';
  
  if (fs.existsSync(gitignorePath)) {
    content = await fs.promises.readFile(gitignorePath, 'utf-8');
    // Ensure file ends with newline
    if (!content.endsWith('\n')) {
      content += '\n';
    }
  }
  
  // Add SafeRun section
  content += SAFERUN_GITIGNORE_ENTRIES.join('\n');
  content += '\n';
  
  await fs.promises.writeFile(gitignorePath, content);
}

/**
 * Get the entries that would be added to .gitignore
 */
export function getSaferunGitignoreEntries(): string[] {
  return [...SAFERUN_GITIGNORE_ENTRIES];
}
