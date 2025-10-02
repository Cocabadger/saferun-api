import crypto from 'crypto';
import fs from 'fs';
import path from 'path';

export type CacheResult = 'safe' | 'dangerous' | 'unknown';

export interface CacheEntry {
  result: CacheResult;
  timestamp: number;
  ttl: number;
}

const SAFE_OPERATIONS = [
  'git status',
  'git log',
  'git diff',
  'git fetch',
  'git pull --ff-only',
  'git branch',
  'git rev-parse',
  'git describe',
  'git show',
];

const DANGEROUS_FLAGS = new Set(['--force', '-f', '--hard', '-D', '--mirror', '--force-with-lease', '--force-if-includes']);

export class OperationCache {
  private readonly cacheDir: string;
  private readonly memoryCache = new Map<string, CacheEntry>();

  constructor(private readonly repoRoot: string) {
    this.cacheDir = path.join(this.repoRoot, '.saferun', '.cache');
    this.ensureCacheDir();
  }

  isDefinitelySafe(command: string, args?: string[]): boolean {
    // Handle single string command or command + args array
    const commandLine = args && args.length > 0
      ? `${command} ${args.join(' ')}`
      : command;

    const tokens = commandLine.split(/\s+/);

    // Check for dangerous flags FIRST (before whitelist)
    if (tokens.some((token) => DANGEROUS_FLAGS.has(token))) {
      return false;
    }

    // Check for dangerous refspec patterns
    // +refs/heads/* - force push pattern
    if (tokens.some((token) => token.startsWith('+') && token.length > 1)) {
      return false;
    }

    // :branch - branch deletion pattern
    if (tokens.some((token) => token.startsWith(':') && token.length > 1)) {
      return false;
    }

    // Check if it's a known safe operation (after dangerous checks)
    if (SAFE_OPERATIONS.some((safe) => commandLine.startsWith(safe))) {
      return true;
    }

    // Default to safe if no dangerous patterns found
    return true;
  }

  getOperationHash(command: string, args: string[], context: Record<string, unknown> = {}): string {
    const payload = JSON.stringify({ command, args, context });
    return crypto.createHash('md5').update(payload).digest('hex');
  }

  async get(hash: string): Promise<CacheEntry | null> {
    const memoryEntry = this.memoryCache.get(hash);
    if (memoryEntry && !this.isExpired(memoryEntry)) {
      return memoryEntry;
    }

    const filePath = this.getCacheFilePath(hash);
    if (!fs.existsSync(filePath)) {
      return null;
    }

    try {
      const data = JSON.parse(fs.readFileSync(filePath, 'utf-8')) as CacheEntry;
      if (this.isExpired(data)) {
        fs.unlinkSync(filePath);
        this.memoryCache.delete(hash);
        return null;
      }
      this.memoryCache.set(hash, data);
      return data;
    } catch (error) {
      this.memoryCache.delete(hash);
      try {
        fs.unlinkSync(filePath);
      } catch (unlinkError) {
        // noop
      }
      return null;
    }
  }

  async set(hash: string, result: CacheResult, ttl = 60_000): Promise<void> {
    const entry: CacheEntry = {
      result,
      timestamp: Date.now(),
      ttl,
    };

    this.memoryCache.set(hash, entry);
    const filePath = this.getCacheFilePath(hash);
    fs.writeFileSync(filePath, JSON.stringify(entry));
  }

  cleanup(): void {
    if (!fs.existsSync(this.cacheDir)) {
      return;
    }

    for (const file of fs.readdirSync(this.cacheDir)) {
      const filePath = path.join(this.cacheDir, file);
      try {
        const data = JSON.parse(fs.readFileSync(filePath, 'utf-8')) as CacheEntry;
        if (this.isExpired(data)) {
          fs.unlinkSync(filePath);
          this.memoryCache.delete(path.basename(file, '.json'));
        }
      } catch {
        try {
          fs.unlinkSync(filePath);
        } catch {
          // ignore
        }
      }
    }
  }

  private ensureCacheDir(): void {
    if (!fs.existsSync(this.cacheDir)) {
      fs.mkdirSync(this.cacheDir, { recursive: true });
    }
  }

  private isExpired(entry: CacheEntry): boolean {
    return Date.now() - entry.timestamp > entry.ttl;
  }

  private getCacheFilePath(hash: string): string {
    return path.join(this.cacheDir, `${hash}.json`);
  }
}
