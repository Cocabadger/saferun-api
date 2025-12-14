import { describe, it, expect } from 'vitest';
import { GitCommandParser } from '../../src/utils/git-parser';

describe('GitCommandParser', () => {
  const parser = new GitCommandParser();

  describe('parsePush - force variants', () => {
    it('should detect --force flag', () => {
      const result = parser.parse('push', ['--force', 'origin', 'main']);

      expect(result.type).toBe('push');
      expect(result.flags).toContain('force');
      expect(result.risk).toBe('high');
      expect(result.remote).toBe('origin');
      expect(result.branch).toBe('main');
    });

    it('should detect -f flag', () => {
      const result = parser.parse('push', ['-f', 'origin', 'feature']);

      expect(result.type).toBe('push');
      expect(result.flags).toContain('force');
      expect(result.risk).toBe('high');
    });

    it('should detect --force-with-lease', () => {
      const result = parser.parse('push', ['--force-with-lease', 'origin', 'main']);

      expect(result.type).toBe('push');
      expect(result.flags).toContain('force');
      expect(result.risk).toBe('high');
    });

    it('should not flag normal push as force', () => {
      const result = parser.parse('push', ['origin', 'main']);

      expect(result.type).toBe('push');
      expect(result.flags).not.toContain('force');
      expect(result.risk).toBe('low');
    });
  });

  describe('parsePush - refspec patterns', () => {
    it('should detect force push with + prefix', () => {
      const result = parser.parse('push', ['origin', '+refs/heads/main']);

      expect(result.type).toBe('push');
      expect(result.flags).toContain('force-refspec');
      expect(result.risk).toBe('high');
      expect(result.branch).toBe('+refs/heads/main');
    });

    it('should detect branch deletion with :branch', () => {
      const result = parser.parse('push', ['origin', ':feature/old']);

      expect(result.type).toBe('push');
      expect(result.action).toBe('delete-remote-branch');
      expect(result.risk).toBe('high');
      expect(result.branch).toBe(':feature/old');
    });

    it('should parse origin/branch format', () => {
      const result = parser.parse('push', ['origin', 'main']);

      expect(result.type).toBe('push');
      expect(result.remote).toBe('origin');
      expect(result.branch).toBe('main');
    });
  });

  describe('parseBranch - delete variants', () => {
    it('should detect -D flag (force delete)', () => {
      const result = parser.parse('branch', ['-D', 'feature/old']);

      expect(result.type).toBe('branch');
      expect(result.action).toBe('delete');
      expect(result.flags).toContain('force');
      expect(result.risk).toBe('high');
      expect(result.targets).toContain('feature/old');
    });

    it('should detect -d flag (safe delete)', () => {
      const result = parser.parse('branch', ['-d', 'feature/merged']);

      expect(result.type).toBe('branch');
      expect(result.action).toBe('delete');
      expect(result.risk).toBe('medium');
      expect(result.targets).toContain('feature/merged');
    });

    it('should detect --delete flag', () => {
      const result = parser.parse('branch', ['--delete', 'old-branch']);

      expect(result.type).toBe('branch');
      expect(result.action).toBe('delete');
      expect(result.targets).toContain('old-branch');
    });
  });

  describe('parseReset - hard mode', () => {
    it('should detect --hard flag', () => {
      const result = parser.parse('reset', ['--hard', 'HEAD~1']);

      expect(result.type).toBe('reset');
      expect(result.flags).toContain('hard');
      expect(result.risk).toBe('high');
      expect(result.targets).toContain('HEAD~1');
    });

    it('should detect HEAD~n syntax', () => {
      const result = parser.parse('reset', ['--hard', 'HEAD~5']);

      expect(result.type).toBe('reset');
      expect(result.targets).toContain('HEAD~5');
      expect(result.risk).toBe('high');
    });

    it('should not flag soft reset as dangerous', () => {
      const result = parser.parse('reset', ['--soft', 'HEAD~1']);

      expect(result.type).toBe('reset');
      expect(result.flags).not.toContain('hard');
      expect(result.risk).toBe('medium');
    });
  });

  describe('resolveAlias', () => {
    it('should return null for non-existent alias', async () => {
      const result = await parser.resolveAlias('nonexistent-alias-xyz');
      expect(result).toBeNull();
    });

    it('should handle empty alias result', async () => {
      const result = await parser.resolveAlias('');
      expect(result).toBeNull();
    });
  });

  describe('edge cases', () => {
    it('should handle empty args array', () => {
      const result = parser.parse('push', []);

      expect(result.type).toBe('push');
      expect(result.risk).toBe('low');
    });

    it('should handle unknown commands', () => {
      const result = parser.parse('unknown-command', ['arg1', 'arg2']);

      expect(result.type).toBe('unknown');
      expect(result.action).toBe('unknown-command');
    });

    it('should handle clean command', () => {
      const result = parser.parse('clean', ['-fd']);

      expect(result.type).toBe('clean');
      expect(result.risk).toBe('medium');
    });

    it('should handle combined branch flags', () => {
      const result = parser.parse('branch', ['-D', 'feature']);

      expect(result.type).toBe('branch');
      expect(result.action).toBe('delete');
      expect(result.flags).toContain('force');
    });
  });
});
