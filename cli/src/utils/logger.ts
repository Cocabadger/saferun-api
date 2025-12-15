import fs from 'fs';
import path from 'path';
import os from 'os';
import crypto from 'crypto';
import { detectAIAgent, getAIAgentType } from './ai-detection';

export interface LogEntry {
  event: string;
  ts?: string;
  
  // AI-specific fields
  is_ai_generated?: boolean;
  ai_agent_type?: string;
  ai_detection_method?: string;
  ai_confidence?: string;
  
  [key: string]: unknown;
}

/**
 * Get the global log directory for a specific repo
 * Logs are stored in ~/.saferun/logs/<hash>/ to survive git reset --hard
 */
function getLogDir(repoRoot: string): string {
  const hash = crypto.createHash('md5').update(repoRoot).digest('hex').slice(0, 12);
  return path.join(os.homedir(), '.saferun', 'logs', hash);
}

export async function logOperation(repoRoot: string, entry: LogEntry): Promise<void> {
  try {
    const logDir = getLogDir(repoRoot);
    await fs.promises.mkdir(logDir, { recursive: true });
    
    // Auto-detect AI agent if not explicitly provided
    let aiFields = {};
    if (entry.is_ai_generated === undefined) {
      const aiInfo = detectAIAgent();
      aiFields = {
        is_ai_generated: aiInfo.isAIAgent,
        ai_agent_type: getAIAgentType(aiInfo),
        ai_detection_method: aiInfo.detectionMethod,
        ai_confidence: aiInfo.confidence,
      };
    }
    
    const record = {
      ts: entry.ts ?? new Date().toISOString(),
      ...entry,
      ...aiFields,
    };
    await fs.promises.appendFile(
      path.join(logDir, 'operations.log'),
      `${JSON.stringify(record)}\n`,
      'utf-8',
    );
  } catch {
    /* ignore logging errors */
  }
}

export async function readLogEntries(repoRoot: string): Promise<LogEntry[]> {
  const logDir = getLogDir(repoRoot);
  const logFile = path.join(logDir, 'operations.log');
  if (!fs.existsSync(logFile)) {
    // Fallback: try reading from old location for migration
    const oldLogFile = path.join(repoRoot, '.saferun', 'logs', 'operations.log');
    if (fs.existsSync(oldLogFile)) {
      return readLogFile(oldLogFile);
    }
    return [];
  }
  return readLogFile(logFile);
}

async function readLogFile(logFile: string): Promise<LogEntry[]> {
  const lines = (await fs.promises.readFile(logFile, 'utf-8')).split(/\r?\n/);
  const entries: LogEntry[] = [];
  for (const line of lines) {
    if (!line.trim()) continue;
    try {
      const parsed = JSON.parse(line);
      entries.push(parsed);
    } catch {
      entries.push({ ts: new Date().toISOString(), event: 'raw', message: line });
    }
  }
  return entries;
}
