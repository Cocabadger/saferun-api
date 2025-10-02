import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import fs from 'fs';
import os from 'os';
import path from 'path';
import { OperationCache } from '../../src/utils/cache';

describe('OperationCache', () => {
  let tmpRoot: string;
  let cache: OperationCache;

  beforeEach(() => {
    tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'saferun-cache-'));
    cache = new OperationCache(tmpRoot);
  });

  afterEach(() => {
    fs.rmSync(tmpRoot, { recursive: true, force: true });
  });

  describe('isDefinitelySafe - safe operations', () => {
    it('should identify git status as safe', () => {
      const result = cache.isDefinitelySafe('git status');
      expect(result).toBe(true);
    });

    it('should identify git log as safe', () => {
      const result = cache.isDefinitelySafe('git log');
      expect(result).toBe(true);
    });

    it('should identify git diff as safe', () => {
      const result = cache.isDefinitelySafe('git diff');
      expect(result).toBe(true);
    });

    it('should identify normal git push as safe', () => {
      const result = cache.isDefinitelySafe('git push origin main');
      expect(result).toBe(true);
    });

    it('should identify git pull as safe', () => {
      const result = cache.isDefinitelySafe('git pull');
      expect(result).toBe(true);
    });
  });

  describe('isDefinitelySafe - dangerous flags', () => {
    it('should detect --force as dangerous', () => {
      const result = cache.isDefinitelySafe('git push --force origin main');
      expect(result).toBe(false);
    });

    it('should detect -f as dangerous', () => {
      const result = cache.isDefinitelySafe('git push -f origin main');
      expect(result).toBe(false);
    });

    it('should detect -D (force delete) as dangerous', () => {
      const result = cache.isDefinitelySafe('git branch -D feature');
      expect(result).toBe(false);
    });

    it('should detect --hard as dangerous', () => {
      const result = cache.isDefinitelySafe('git reset --hard HEAD~5');
      expect(result).toBe(false);
    });

    it('should detect --force-with-lease as dangerous', () => {
      const result = cache.isDefinitelySafe('git push --force-with-lease origin main');
      expect(result).toBe(false);
    });

    it('should detect + prefix (force) as dangerous', () => {
      const result = cache.isDefinitelySafe('git push origin +refs/heads/main');
      expect(result).toBe(false);
    });

    it('should detect :branch (deletion) as dangerous', () => {
      const result = cache.isDefinitelySafe('git push origin :feature');
      expect(result).toBe(false);
    });
  });

  describe('memory + disk cache', () => {
    it('should cache operation results in memory', async () => {
      const key = 'test-key-1';
      await cache.set(key, 'safe', 60000);

      const result = await cache.get(key);
      expect(result).toMatchObject({ result: 'safe' });
      expect(result?.timestamp).toBeDefined();
      expect(result?.ttl).toBe(60000);
    });

    it('should persist cache to disk', async () => {
      const key = 'test-key-2';
      await cache.set(key, 'dangerous', 60000);

      // Create new cache instance (simulates restart)
      const newCache = new OperationCache(tmpRoot);
      const result = await newCache.get(key);

      expect(result).toMatchObject({ result: 'dangerous' });
      expect(result?.timestamp).toBeDefined();
      expect(result?.ttl).toBe(60000);
    });

    it('should return null for non-existent keys', async () => {
      const result = await cache.get('non-existent-key');
      expect(result).toBeNull();
    });
  });

  describe('TTL expiration', () => {
    it('should expire entries after TTL', async () => {
      const key = 'expire-test';
      
      // Set with 100ms TTL
      await cache.set(key, 'safe', 100);
      
      // Should exist immediately
      let result = await cache.get(key);
      expect(result).not.toBeNull();
      
      // Wait for expiration
      await new Promise(resolve => setTimeout(resolve, 150));
      
      // Should be expired
      result = await cache.get(key);
      expect(result).toBeNull();
    });

    it('should not expire entries before TTL', async () => {
      const key = 'no-expire-test';
      
      // Set with 10 second TTL
      await cache.set(key, 'safe', 10000);
      
      // Should still exist after 100ms
      await new Promise(resolve => setTimeout(resolve, 100));
      
      const result = await cache.get(key);
      expect(result).not.toBeNull();
    });
  });

  describe('cleanup old entries', () => {
    it('should clean up expired entries', async () => {
      // Create multiple entries with different TTLs
      await cache.set('short-1', 'safe', 50);
      await cache.set('short-2', 'safe', 50);
      await cache.set('long', 'safe', 10000);
      
      // Wait for short TTL entries to expire
      await new Promise(resolve => setTimeout(resolve, 100));
      
      // Trigger cleanup
      await cache.cleanup();
      
      // Short TTL entries should be gone
      expect(await cache.get('short-1')).toBeNull();
      expect(await cache.get('short-2')).toBeNull();
      
      // Long TTL entry should still exist
      expect(await cache.get('long')).not.toBeNull();
    });

    it('should not remove non-expired entries during cleanup', async () => {
      await cache.set('keep-1', 'safe', 10000);
      await cache.set('keep-2', 'dangerous', 10000);
      
      await cache.cleanup();
      
      expect(await cache.get('keep-1')).not.toBeNull();
      expect(await cache.get('keep-2')).not.toBeNull();
    });
  });

  describe('getOperationHash', () => {
    it('should generate consistent hashes for same input', () => {
      const hash1 = cache.getOperationHash('push', ['--force', 'origin', 'main'], { branch: 'main' });
      const hash2 = cache.getOperationHash('push', ['--force', 'origin', 'main'], { branch: 'main' });
      
      expect(hash1).toBe(hash2);
    });

    it('should generate different hashes for different inputs', () => {
      const hash1 = cache.getOperationHash('push', ['--force', 'origin', 'main'], {});
      const hash2 = cache.getOperationHash('push', ['--force', 'origin', 'dev'], {});
      
      expect(hash1).not.toBe(hash2);
    });

    it('should include metadata in hash', () => {
      const hash1 = cache.getOperationHash('push', ['origin', 'main'], { risk: 0.5 });
      const hash2 = cache.getOperationHash('push', ['origin', 'main'], { risk: 0.9 });
      
      expect(hash1).not.toBe(hash2);
    });
  });
});
