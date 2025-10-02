import fs from 'fs';
import path from 'path';
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

export async function logOperation(repoRoot: string, entry: LogEntry): Promise<void> {
  try {
    const logDir = path.join(repoRoot, '.saferun', 'logs');
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
  const logFile = path.join(repoRoot, '.saferun', 'logs', 'operations.log');
  if (!fs.existsSync(logFile)) {
    return [];
  }
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
