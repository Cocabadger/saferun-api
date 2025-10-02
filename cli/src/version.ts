import fs from 'fs';
import path from 'path';

let cachedVersion: string | null = null;

export function getCliVersion(): string {
  if (cachedVersion) {
    return cachedVersion;
  }
  try {
    const pkgPath = path.resolve(__dirname, '../package.json');
    const pkg = JSON.parse(fs.readFileSync(pkgPath, 'utf-8')) as { version?: string };
    cachedVersion = pkg.version ?? '0.0.0';
  } catch {
    cachedVersion = '0.0.0';
  }
  return cachedVersion;
}
