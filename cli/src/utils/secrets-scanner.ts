import { execSync } from 'child_process';
import { existsSync, readFileSync } from 'fs';
import { join } from 'path';

export interface SecretMatch {
  file: string;
  pattern: string;
  line?: number;
  snippet?: string;
}

const SECRET_PATTERNS = [
  // AWS
  { name: 'AWS Access Key', regex: /AKIA[0-9A-Z]{16}/g },
  { name: 'AWS Secret Key', regex: /aws.{0,20}?['\"][0-9a-zA-Z/+]{40}['\"]/ },
  
  // GitHub
  { name: 'GitHub Personal Access Token', regex: /ghp_[a-zA-Z0-9]{36}/g },
  { name: 'GitHub OAuth Token', regex: /gho_[a-zA-Z0-9]{36}/g },
  { name: 'GitHub App Token', regex: /ghs_[a-zA-Z0-9]{36}/g },
  
  // OpenAI
  { name: 'OpenAI API Key', regex: /sk-[a-zA-Z0-9]{48}/g },
  { name: 'OpenAI Project Key', regex: /sk-proj-[a-zA-Z0-9-]{48}/g },
  
  // Stripe
  { name: 'Stripe Secret Key', regex: /sk_live_[0-9a-zA-Z]{24}/g },
  { name: 'Stripe Restricted Key', regex: /rk_live_[0-9a-zA-Z]{24}/g },
  
  // Slack
  { name: 'Slack Token', regex: /xox[baprs]-[0-9]{10,13}-[0-9]{10,13}-[a-zA-Z0-9]{24,32}/g },
  { name: 'Slack Webhook', regex: /https:\/\/hooks\.slack\.com\/services\/T[a-zA-Z0-9_]+\/B[a-zA-Z0-9_]+\/[a-zA-Z0-9_]+/g },
  
  // Google
  { name: 'Google API Key', regex: /AIza[0-9A-Za-z-_]{35}/g },
  { name: 'Google OAuth', regex: /[0-9]+-[0-9A-Za-z_]{32}\.apps\.googleusercontent\.com/g },
  
  // Generic patterns
  { name: 'Generic API Key', regex: /api[_-]?key[_-]?[=:]\s*['\"][a-zA-Z0-9]{32,}['\"]/gi },
  { name: 'Generic Secret', regex: /secret[_-]?[=:]\s*['\"][a-zA-Z0-9]{32,}['\"]/gi },
  { name: 'Private Key Header', regex: /-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----/g },
];

const SENSITIVE_FILES = [
  '.env',
  '.env.local',
  '.env.production',
  '.env.development',
  '.env.test',
  'credentials',
  'secrets',
  'secrets.json',
  'secrets.yaml',
  'secrets.yml',
  'private-key',
  'privatekey',
  'id_rsa',
  'id_ed25519',
  '.npmrc',
  '.pypirc',
  'config.json',
  'settings.json',
];

/**
 * Get list of staged files for commit
 */
export function getStagedFiles(repoRoot: string): string[] {
  try {
    const output = execSync('git diff --cached --name-only', {
      cwd: repoRoot,
      encoding: 'utf-8',
    });
    return output
      .trim()
      .split('\n')
      .filter((f) => f.length > 0);
  } catch (err) {
    return [];
  }
}

/**
 * Check if filename is sensitive (e.g., .env, credentials)
 */
export function isSensitiveFile(filename: string): boolean {
  const basename = filename.split('/').pop()?.toLowerCase() || '';
  return SENSITIVE_FILES.some((pattern) => basename.includes(pattern.toLowerCase()));
}

/**
 * Scan file content for secret patterns
 */
export function scanFileForSecrets(filepath: string, repoRoot: string): SecretMatch[] {
  const matches: SecretMatch[] = [];
  const fullPath = join(repoRoot, filepath);

  if (!existsSync(fullPath)) {
    return matches;
  }

  try {
    const content = readFileSync(fullPath, 'utf-8');
    const lines = content.split('\n');

    for (const pattern of SECRET_PATTERNS) {
      for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        const regex = new RegExp(pattern.regex.source, pattern.regex.flags);
        const found = line.match(regex);

        if (found) {
          matches.push({
            file: filepath,
            pattern: pattern.name,
            line: i + 1,
            snippet: line.trim().substring(0, 80),
          });
        }
      }
    }
  } catch (err) {
    // Ignore binary files or read errors
  }

  return matches;
}

/**
 * Scan all staged files for secrets
 */
export function scanStagedFilesForSecrets(repoRoot: string): {
  secrets: SecretMatch[];
  sensitiveFiles: string[];
} {
  const stagedFiles = getStagedFiles(repoRoot);
  const secrets: SecretMatch[] = [];
  const sensitiveFiles: string[] = [];

  for (const file of stagedFiles) {
    // Check if filename itself is sensitive
    if (isSensitiveFile(file)) {
      sensitiveFiles.push(file);
    }

    // Scan file content for secret patterns
    const fileSecrets = scanFileForSecrets(file, repoRoot);
    secrets.push(...fileSecrets);
  }

  return { secrets, sensitiveFiles };
}
