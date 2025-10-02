/**
 * AI Agent Detection
 * Detects if operations are being performed by AI agents (Cursor, Copilot, etc.)
 */

export interface AIAgentInfo {
  isAIAgent: boolean;
  agentType?:
    // IDE Assistants
    | 'cursor' | 'copilot' | 'windsurf' | 'codeium' | 'tabnine' | 'continue'
    // Conversational AI
    | 'claude' | 'chatgpt' | 'gemini' | 'anthropic-api' | 'openai-api'
    // Automation Platforms
    | 'n8n' | 'zapier' | 'make' | 'notion-ai'
    // CI/CD & Actions
    | 'github-actions' | 'gitlab-ci' | 'jenkins'
    // Generic
    | 'webhook' | 'api-client' | 'unknown';
  confidence: 'high' | 'medium' | 'low';
  detectionMethod: 'env' | 'pattern' | 'heuristic';
}

// Known AI agent environment variables
const AI_ENV_VARS: Record<string, string> = {
  // IDE Assistants
  CURSOR_AI: 'cursor',
  CURSOR_AI_AGENT: 'cursor',
  GITHUB_COPILOT_ACTIVE: 'copilot',
  COPILOT_AGENT: 'copilot',
  WINDSURF_AI: 'windsurf',
  CODEIUM_ACTIVE: 'codeium',
  TABNINE_ACTIVE: 'tabnine',
  CONTINUE_DEV: 'continue',

  // Conversational AI APIs
  ANTHROPIC_API_KEY: 'anthropic-api',
  OPENAI_API_KEY: 'openai-api',
  CLAUDE_API_KEY: 'claude',
  CHATGPT_API_KEY: 'chatgpt',

  // Automation Platforms
  N8N_USER_ID: 'n8n',
  N8N_WORKFLOW_ID: 'n8n',
  ZAPIER_DEPLOY_KEY: 'zapier',
  ZAPIER_HOOK_URL: 'zapier',
  MAKE_WEBHOOK_ID: 'make',
  NOTION_INTEGRATION_TOKEN: 'notion-ai',

  // Generic markers
  AI_AGENT: 'unknown',
  BOT_NAME: 'unknown',
  AUTOMATION_PLATFORM: 'unknown',
};

/**
 * Detect if current operation is from an AI agent
 */
export function detectAIAgent(): AIAgentInfo {
  // 1. Check environment variables (highest confidence)
  for (const [envVar, agentType] of Object.entries(AI_ENV_VARS)) {
    if (process.env[envVar]) {
      return {
        isAIAgent: true,
        agentType: agentType as AIAgentInfo['agentType'],
        confidence: 'high',
        detectionMethod: 'env',
      };
    }
  }

  // 2. Check for AI-specific patterns in environment
  const termProgram = process.env.TERM_PROGRAM;
  const editorName = process.env.EDITOR || process.env.VISUAL;
  const userAgent = process.env.HTTP_USER_AGENT || process.env.USER_AGENT;

  // IDE patterns
  if (termProgram?.toLowerCase().includes('cursor')) {
    return {
      isAIAgent: true,
      agentType: 'cursor',
      confidence: 'medium',
      detectionMethod: 'pattern',
    };
  }

  if (editorName?.toLowerCase().includes('cursor')) {
    return {
      isAIAgent: true,
      agentType: 'cursor',
      confidence: 'medium',
      detectionMethod: 'pattern',
    };
  }

  // Automation platform patterns
  if (userAgent) {
    const ua = userAgent.toLowerCase();
    if (ua.includes('n8n')) {
      return { isAIAgent: true, agentType: 'n8n', confidence: 'high', detectionMethod: 'pattern' };
    }
    if (ua.includes('zapier')) {
      return { isAIAgent: true, agentType: 'zapier', confidence: 'high', detectionMethod: 'pattern' };
    }
    if (ua.includes('notion')) {
      return { isAIAgent: true, agentType: 'notion-ai', confidence: 'medium', detectionMethod: 'pattern' };
    }
    if (ua.includes('webhook') || ua.includes('bot')) {
      return { isAIAgent: true, agentType: 'webhook', confidence: 'medium', detectionMethod: 'pattern' };
    }
  }

  // 3. Check git config for automation markers
  const gitUser = process.env.GIT_AUTHOR_NAME || process.env.GIT_COMMITTER_NAME;
  if (gitUser) {
    const user = gitUser.toLowerCase();
    if (user.includes('bot') || user.includes('[bot]') || user.includes('automation')) {
      return { isAIAgent: true, agentType: 'api-client', confidence: 'medium', detectionMethod: 'pattern' };
    }
    if (user.includes('claude') || user.includes('chatgpt') || user.includes('ai')) {
      return { isAIAgent: true, agentType: 'unknown', confidence: 'low', detectionMethod: 'heuristic' };
    }
  }

  // 4. Heuristic detection - check for non-interactive session
  if (!process.stdin.isTTY && !process.env.CI) {
    // Non-TTY session that's not CI might be automation
    return { isAIAgent: true, agentType: 'api-client', confidence: 'low', detectionMethod: 'heuristic' };
  }

  return {
    isAIAgent: false,
    confidence: 'high',
    detectionMethod: 'env',
  };
}

/**
 * Get AI agent type as string for logging
 */
export function getAIAgentType(info: AIAgentInfo): string {
  if (!info.isAIAgent) return 'human';
  return info.agentType || 'unknown-ai';
}

/**
 * Check if AI agents should have stricter policies
 */
export function shouldApplyStrictPolicyForAI(info: AIAgentInfo): boolean {
  // Apply strict policy for high confidence AI detection
  return info.isAIAgent && info.confidence === 'high';
}

/**
 * Detection signal from various sources
 */
export interface DetectionSignal {
  source: 'env' | 'process' | 'git' | 'network' | 'handshake';
  confidence: number; // 0.0-1.0
  agentType?: string;
  reason?: string;
}

/**
 * Signal weights for scoring
 */
const SIGNAL_WEIGHTS = {
  env: 0.6,        // Environment variables (highest trust)
  handshake: 0.7,  // Explicit agent registration (highest trust)
  process: 0.3,    // Process monitoring (medium trust)
  git: 0.2,        // Git config/commits (lower trust)
  network: 0.4,    // Network monitoring (medium trust)
};

/**
 * Calculate total AI detection score from multiple signals
 */
export function calculateDetectionScore(signals: DetectionSignal[]): number {
  if (signals.length === 0) return 0;

  let weightedSum = 0;
  let totalWeight = 0;

  for (const signal of signals) {
    const weight = SIGNAL_WEIGHTS[signal.source] || 0.1;
    weightedSum += signal.confidence * weight;
    totalWeight += weight;
  }

  return totalWeight > 0 ? Math.min(weightedSum / totalWeight, 1.0) : 0;
}

/**
 * Get enforcement action based on detection score
 */
export function getEnforcementAction(score: number): 'allow' | 'warn' | 'require_approval' | 'block' {
  if (score >= 0.8) return 'block';
  if (score >= 0.5) return 'require_approval';
  if (score >= 0.3) return 'warn';
  return 'allow';
}

/**
 * Collect all detection signals
 */
export async function collectAllSignals(repoRoot?: string): Promise<DetectionSignal[]> {
  const signals: DetectionSignal[] = [];

  // 1. Basic detection (current implementation)
  const basicInfo = detectAIAgent();
  if (basicInfo.isAIAgent) {
    const confidence = basicInfo.confidence === 'high' ? 0.9 : basicInfo.confidence === 'medium' ? 0.6 : 0.3;
    signals.push({
      source: basicInfo.detectionMethod === 'env' ? 'env' : 'git',
      confidence,
      agentType: getAIAgentType(basicInfo),
      reason: `Detected via ${basicInfo.detectionMethod}`,
    });
  }

  // 2. Check commit authors
  const commitSignals = await checkCommitAuthors(repoRoot);
  signals.push(...commitSignals);

  // 3. Check git config
  const gitConfigSignal = await checkGitConfig(repoRoot);
  if (gitConfigSignal) signals.push(gitConfigSignal);

  // 4. Check HTTP proxy
  const proxySignal = checkHTTPProxy();
  if (proxySignal) signals.push(proxySignal);

  // 5. Check handshake file
  const handshakeSignal = await checkHandshake(repoRoot);
  if (handshakeSignal) signals.push(handshakeSignal);

  return signals;
}

/**
 * Check recent commits for AI/bot authors
 */
async function checkCommitAuthors(repoRoot?: string): Promise<DetectionSignal[]> {
  const signals: DetectionSignal[] = [];

  try {
    const { execFile } = require('child_process');
    const { promisify } = require('util');
    const execFileAsync = promisify(execFile);

    const execOptions = repoRoot ? { cwd: repoRoot } : {};
    const { stdout } = await execFileAsync('git', ['log', '-10', '--format=%an|%ae'], execOptions);
    const commits = stdout.trim().split('\n');

    // Check whitelist if available
    let isWhitelistedFn: ((name: string, email: string) => Promise<boolean>) | null = null;
    if (repoRoot) {
      const { isGitAuthorWhitelisted } = await import('./whitelist');
      isWhitelistedFn = (name: string, email: string) => isGitAuthorWhitelisted(repoRoot, name, email);
    }

    for (const commit of commits) {
      const [name, email] = commit.split('|');
      if (!name || !email) continue;

      // Skip if whitelisted
      if (isWhitelistedFn && (await isWhitelistedFn(name, email))) {
        continue;
      }

      const nameLower = name.toLowerCase();
      const emailLower = email.toLowerCase();

      // Check for bot patterns
      if (nameLower.includes('[bot]') || emailLower.includes('bot@') || nameLower.includes('bot')) {
        signals.push({
          source: 'git',
          confidence: 0.8,
          agentType: 'api-client',
          reason: `Bot author: ${name}`,
        });
        break; // One signal is enough
      }

      // Check for AI keywords
      const aiKeywords = ['chatgpt', 'claude', 'ai assistant', 'copilot', 'ai'];
      if (aiKeywords.some((kw) => nameLower.includes(kw) || emailLower.includes(kw))) {
        signals.push({
          source: 'git',
          confidence: 0.6,
          agentType: 'unknown',
          reason: `AI keyword in author: ${name}`,
        });
        break;
      }
    }
  } catch {
    // Ignore errors (not in git repo, etc.)
  }

  return signals;
}

/**
 * Check git config for bot/AI markers
 */
async function checkGitConfig(repoRoot?: string): Promise<DetectionSignal | null> {
  try {
    const { execFile } = require('child_process');
    const { promisify } = require('util');
    const execFileAsync = promisify(execFile);

    const execOptions = repoRoot ? { cwd: repoRoot } : {};
    const userName = (await execFileAsync('git', ['config', 'user.name'], execOptions)).stdout.trim();
    const userEmail = (await execFileAsync('git', ['config', 'user.email'], execOptions)).stdout.trim();

    const nameLower = userName.toLowerCase();
    const emailLower = userEmail.toLowerCase();

    // Bot patterns
    if (emailLower.includes('bot@') || nameLower.includes('[bot]')) {
      return {
        source: 'git',
        confidence: 0.7,
        agentType: 'api-client',
        reason: `Git config: ${userName} <${userEmail}>`,
      };
    }

    // AI patterns
    if (nameLower.includes('ai') || nameLower.includes('chatgpt') || nameLower.includes('claude')) {
      return {
        source: 'git',
        confidence: 0.5,
        agentType: 'unknown',
        reason: `AI pattern in git config: ${userName}`,
      };
    }
  } catch {
    // Ignore errors
  }

  return null;
}

/**
 * Check HTTP_PROXY for AI API endpoints
 */
function checkHTTPProxy(): DetectionSignal | null {
  const proxy = process.env.HTTP_PROXY || process.env.HTTPS_PROXY || process.env.http_proxy || process.env.https_proxy;

  if (proxy) {
    const proxyLower = proxy.toLowerCase();
    const aiEndpoints = [
      { domain: 'api.openai.com', agent: 'openai-api' },
      { domain: 'api.anthropic.com', agent: 'anthropic-api' },
      { domain: 'generativelanguage.googleapis.com', agent: 'gemini' },
    ];

    for (const endpoint of aiEndpoints) {
      if (proxyLower.includes(endpoint.domain)) {
        return {
          source: 'network',
          confidence: 0.6,
          agentType: endpoint.agent,
          reason: `HTTP proxy points to ${endpoint.domain}`,
        };
      }
    }
  }

  return null;
}

/**
 * Check for agent handshake file
 */
async function checkHandshake(repoRoot?: string): Promise<DetectionSignal | null> {
  try {
    const fs = require('fs');
    const path = require('path');
    const basePath = repoRoot || process.cwd();
    const handshakePath = path.join(basePath, '.saferun', '.agent_session');

    if (fs.existsSync(handshakePath)) {
      const data = JSON.parse(fs.readFileSync(handshakePath, 'utf-8'));

      return {
        source: 'handshake',
        confidence: 1.0, // Explicit registration = 100% confidence
        agentType: data.agent_type || 'unknown',
        reason: `Agent registered: ${data.agent_id}`,
      };
    }
  } catch {
    // Ignore errors
  }

  return null;
}
