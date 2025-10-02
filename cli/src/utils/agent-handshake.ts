/**
 * Agent Handshake API
 * Allows AI agents to explicitly register themselves for better detection
 */

import fs from 'fs';
import path from 'path';

export interface AgentHandshake {
  agent_id: string;
  agent_type: string;
  agent_version?: string;
  session_start: string;
  metadata?: Record<string, any>;
}

/**
 * Register an AI agent (called by agents that integrate with SafeRun)
 */
export function registerAgent(handshake: AgentHandshake, repoRoot?: string): void {
  const basePath = repoRoot || process.cwd();
  const saferunDir = path.join(basePath, '.saferun');
  const handshakePath = path.join(saferunDir, '.agent_session');

  // Create .saferun directory if needed
  if (!fs.existsSync(saferunDir)) {
    fs.mkdirSync(saferunDir, { recursive: true });
  }

  // Write handshake file
  fs.writeFileSync(handshakePath, JSON.stringify(handshake, null, 2), 'utf-8');

  // Also set environment variable for current session
  process.env.SAFERUN_AGENT_ID = handshake.agent_id;
  process.env.SAFERUN_AGENT_TYPE = handshake.agent_type;
}

/**
 * Unregister agent (cleanup session)
 */
export function unregisterAgent(repoRoot?: string): void {
  const basePath = repoRoot || process.cwd();
  const handshakePath = path.join(basePath, '.saferun', '.agent_session');

  if (fs.existsSync(handshakePath)) {
    fs.unlinkSync(handshakePath);
  }

  delete process.env.SAFERUN_AGENT_ID;
  delete process.env.SAFERUN_AGENT_TYPE;
}

/**
 * Get current agent handshake if registered
 */
export function getAgentHandshake(repoRoot?: string): AgentHandshake | null {
  const basePath = repoRoot || process.cwd();
  const handshakePath = path.join(basePath, '.saferun', '.agent_session');

  if (!fs.existsSync(handshakePath)) {
    return null;
  }

  try {
    const content = fs.readFileSync(handshakePath, 'utf-8');
    return JSON.parse(content) as AgentHandshake;
  } catch {
    return null;
  }
}

/**
 * Check if agent is currently registered
 */
export function isAgentRegistered(repoRoot?: string): boolean {
  return getAgentHandshake(repoRoot) !== null;
}

/**
 * Create handshake for command-line use
 */
export function createHandshake(
  agentType: string,
  options?: { agentId?: string; version?: string; metadata?: Record<string, any> }
): AgentHandshake {
  return {
    agent_id: options?.agentId || `${agentType}-${Date.now()}`,
    agent_type: agentType,
    agent_version: options?.version,
    session_start: new Date().toISOString(),
    metadata: options?.metadata,
  };
}