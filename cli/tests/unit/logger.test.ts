import { describe, it, expect, afterEach } from 'vitest';
import fs from 'fs';
import os from 'os';
import path from 'path';
import { logOperation, readLogEntries } from '../../src/utils/logger';

describe('logger utilities', () => {
  const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'saferun-cli-'));

  afterEach(() => {
    fs.rmSync(tmpRoot, { recursive: true, force: true });
  });

  it('writes and reads log entries', async () => {
    const repo = path.join(tmpRoot, 'repo');
    fs.mkdirSync(repo);

    await logOperation(repo, { event: 'test', detail: 'one' });
    await logOperation(repo, { event: 'test', detail: 'two' });

    const entries = await readLogEntries(repo);
    expect(entries).toHaveLength(2);
    expect(entries[0].event).toBe('test');
    expect(entries[1].detail).toBe('two');
  });
});
