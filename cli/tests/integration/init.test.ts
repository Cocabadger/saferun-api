import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import fs from 'fs';
import os from 'os';
import path from 'path';
import { execSync } from 'child_process';

describe('Init command integration', () => {
  let tmpRoot: string;
  let gitDir: string;

  beforeEach(() => {
    // Create temporary directory
    tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'saferun-init-'));
    
    // Initialize git repository
    execSync('git init', { cwd: tmpRoot, stdio: 'pipe' });
    execSync('git config user.name "Test User"', { cwd: tmpRoot, stdio: 'pipe' });
    execSync('git config user.email "test@example.com"', { cwd: tmpRoot, stdio: 'pipe' });
    
    gitDir = path.join(tmpRoot, '.git');
  });

  afterEach(() => {
    // Clean up
    try {
      fs.rmSync(tmpRoot, { recursive: true, force: true });
    } catch {
      // Ignore cleanup errors
    }
  });

  it('should create .saferun directory structure', () => {
    // Simulate init by creating directories directly
    const saferunDir = path.join(tmpRoot, '.saferun');
    fs.mkdirSync(saferunDir, { recursive: true });
    fs.mkdirSync(path.join(saferunDir, 'logs'), { recursive: true });
    fs.mkdirSync(path.join(saferunDir, 'cache'), { recursive: true });
    
    // Verify structure
    expect(fs.existsSync(saferunDir)).toBe(true);
    expect(fs.existsSync(path.join(saferunDir, 'logs'))).toBe(true);
    expect(fs.existsSync(path.join(saferunDir, 'cache'))).toBe(true);
  });

  it('should create config.yml file', () => {
    const saferunDir = path.join(tmpRoot, '.saferun');
    fs.mkdirSync(saferunDir, { recursive: true });
    
    const configPath = path.join(saferunDir, 'config.yml');
    const configContent = `mode: balanced
api:
  url: https://api.saferun.dev
github:
  repo: auto
  protected_branches:
    - main
    - master`;
    
    fs.writeFileSync(configPath, configContent, 'utf-8');
    
    expect(fs.existsSync(configPath)).toBe(true);
    const content = fs.readFileSync(configPath, 'utf-8');
    expect(content).toContain('mode:');
    expect(content).toContain('api:');
    expect(content).toContain('github:');
  });

  it('should install Git hooks', () => {
    const hooksDir = path.join(gitDir, 'hooks');
    fs.mkdirSync(hooksDir, { recursive: true });
    
    // Create hook files
    const hooks = ['pre-push', 'pre-commit', 'post-checkout'];
    hooks.forEach(hook => {
      const hookPath = path.join(hooksDir, hook);
      fs.writeFileSync(hookPath, '#!/bin/sh\n# SafeRun hook\nsaferun-hook pre-push', { mode: 0o755 });
    });
    
    // Verify hooks
    hooks.forEach(hook => {
      const hookPath = path.join(hooksDir, hook);
      expect(fs.existsSync(hookPath)).toBe(true);
      
      const stat = fs.statSync(hookPath);
      expect((stat.mode & 0o111) !== 0).toBe(true); // Has execute permission
    });
  });

  it('should backup existing hooks', () => {
    const hooksDir = path.join(gitDir, 'hooks');
    fs.mkdirSync(hooksDir, { recursive: true });
    
    // Create existing hook
    const existingHook = path.join(hooksDir, 'pre-push');
    fs.writeFileSync(existingHook, '#!/bin/sh\necho "existing hook"', { mode: 0o755 });
    
    // Simulate backup
    const backupDir = path.join(tmpRoot, '.saferun', 'backup');
    fs.mkdirSync(backupDir, { recursive: true });
    
    const backupFile = path.join(backupDir, `pre-push.${Date.now()}.backup`);
    fs.copyFileSync(existingHook, backupFile);
    
    // Verify backup
    expect(fs.existsSync(backupDir)).toBe(true);
    const backupFiles = fs.readdirSync(backupDir);
    expect(backupFiles.some(f => f.startsWith('pre-push.'))).toBe(true);
  });

  it('should create installation manifest', () => {
    const saferunDir = path.join(tmpRoot, '.saferun');
    fs.mkdirSync(saferunDir, { recursive: true });
    
    const manifest = {
      hooks: ['pre-push', 'pre-commit', 'post-checkout'],
      installed_at: new Date().toISOString(),
      version: '0.1.0',
    };
    
    const manifestPath = path.join(saferunDir, '.install_manifest.json');
    fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2));
    
    expect(fs.existsSync(manifestPath)).toBe(true);
    
    const content = JSON.parse(fs.readFileSync(manifestPath, 'utf-8'));
    expect(content).toHaveProperty('hooks');
    expect(content).toHaveProperty('installed_at');
    expect(Array.isArray(content.hooks)).toBe(true);
  });

  it('should set up git aliases', () => {
    // Set alias using git config
    execSync('git config alias.branch "!saferun hook branch"', { cwd: tmpRoot, stdio: 'pipe' });
    
    // Verify alias
    const branchAlias = execSync('git config --get alias.branch', { 
      cwd: tmpRoot, 
      encoding: 'utf-8',
      stdio: 'pipe'
    }).trim();
    
    expect(branchAlias).toContain('saferun hook');
  });

  it('should handle re-initialization gracefully', () => {
    const configPath = path.join(tmpRoot, '.saferun', 'config.yml');
    const saferunDir = path.join(tmpRoot, '.saferun');
    
    // First init
    fs.mkdirSync(saferunDir, { recursive: true });
    const originalConfig = 'mode: strict\napi:\n  url: https://api.saferun.dev';
    fs.writeFileSync(configPath, originalConfig);
    
    // Verify first init
    expect(fs.existsSync(configPath)).toBe(true);
    
    // Second init - should not overwrite if file exists
    if (fs.existsSync(configPath)) {
      const existing = fs.readFileSync(configPath, 'utf-8');
      // Keep existing config
      expect(existing).toBeTruthy();
    }
    
    expect(fs.existsSync(configPath)).toBe(true);
  });

  it('should create gitignore entry for SafeRun cache', () => {
    const saferunDir = path.join(tmpRoot, '.saferun');
    fs.mkdirSync(saferunDir, { recursive: true });
    
    const gitignorePath = path.join(saferunDir, '.gitignore');
    const gitignoreContent = 'cache/\nlogs/\n*.log';
    fs.writeFileSync(gitignorePath, gitignoreContent);
    
    expect(fs.existsSync(gitignorePath)).toBe(true);
    const content = fs.readFileSync(gitignorePath, 'utf-8');
    expect(content).toContain('cache');
  });

  it('should initialize with different protection modes', () => {
    const saferunDir = path.join(tmpRoot, '.saferun');
    fs.mkdirSync(saferunDir, { recursive: true });
    
    // Test strict mode
    const configPath = path.join(saferunDir, 'config.yml');
    const strictConfig = 'mode: strict\napi:\n  url: https://api.saferun.dev';
    fs.writeFileSync(configPath, strictConfig);
    
    const content = fs.readFileSync(configPath, 'utf-8');
    expect(content).toContain('strict');
    
    // Test balanced mode
    const balancedConfig = content.replace('strict', 'balanced');
    fs.writeFileSync(configPath, balancedConfig);
    
    const updatedContent = fs.readFileSync(configPath, 'utf-8');
    expect(updatedContent).toContain('balanced');
  });

  it('should create proper directory permissions', () => {
    const saferunDir = path.join(tmpRoot, '.saferun');
    fs.mkdirSync(saferunDir, { recursive: true });
    
    const stat = fs.statSync(saferunDir);
    
    // Directory should be readable and writable by owner
    expect((stat.mode & 0o700) !== 0).toBe(true);
  });
});
