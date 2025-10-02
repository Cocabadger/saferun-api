import fs from 'fs';
import path from 'path';
import os from 'os';
import https from 'https';
import { v4 as uuidv4 } from 'uuid';
import { SafeRunConfig } from './config';
import { detectAIAgent, getAIAgentType } from './ai-detection';

export interface MetricEvent {
  event: string;
  properties?: Record<string, unknown>;
}

interface MetricPayload extends MetricEvent {
  timestamp: string;
  installation_id: string;
  session_id: string;
}

const METRICS_ENDPOINT = process.env.SAFERUN_METRICS_URL ?? 'https://metrics.saferun.dev/v1/events';

export class MetricsCollector {
  private readonly installationIdPath: string;
  private installationId: string;
  private readonly sessionId: string;
  private readonly enabled: boolean;
  private readonly queue: MetricPayload[] = [];
  private flushTimer: NodeJS.Timeout | null = null;

  constructor(private readonly repoRoot: string, private readonly config: SafeRunConfig) {
    this.installationIdPath = path.join(repoRoot, '.saferun', '.installation_id');
    this.installationId = this.loadOrCreateInstallationId();
    this.sessionId = uuidv4();
    this.enabled = config.telemetry?.enabled !== false;
  }

  async track(event: string, properties: Record<string, unknown> = {}): Promise<void> {
    if (!this.enabled) {
      return;
    }

    // Detect AI agent
    const aiInfo = detectAIAgent();

    const payload: MetricPayload = {
      event,
      properties: {
        ...properties,
        node_version: process.version,
        platform: os.platform(),
        cli_version: getCliVersion(),
        mode: this.config.mode,
        // AI-specific metrics
        ai_agent_detected: aiInfo.isAIAgent,
        ai_agent_type: getAIAgentType(aiInfo),
        ai_detection_method: aiInfo.detectionMethod,
        ai_confidence: aiInfo.confidence,
      },
      timestamp: new Date().toISOString(),
      installation_id: this.installationId,
      session_id: this.sessionId,
    };

    this.queue.push(payload);
    if (this.queue.length >= 10) {
      await this.flush();
      return;
    }

    if (!this.flushTimer) {
      this.flushTimer = setTimeout(() => {
        this.flush().catch(() => {
          /* swallow */
        });
      }, 30_000).unref();
    }
  }

  async flush(): Promise<void> {
    if (!this.enabled || this.queue.length === 0) {
      return;
    }

    const batch = this.queue.splice(0, this.queue.length);
    if (this.flushTimer) {
      clearTimeout(this.flushTimer);
      this.flushTimer = null;
    }

    try {
      await postJson(METRICS_ENDPOINT, { events: batch });
    } catch (error) {
      // If metrics fail we silently ignore to avoid impacting hooks
      this.queue.unshift(...batch);
    }
  }

  async dispose(): Promise<void> {
    if (this.flushTimer) {
      clearTimeout(this.flushTimer);
      this.flushTimer = null;
    }
    await this.flush();
  }

  private loadOrCreateInstallationId(): string {
    if (fs.existsSync(this.installationIdPath)) {
      try {
        const value = fs.readFileSync(this.installationIdPath, 'utf-8').trim();
        if (value) {
          return value;
        }
      } catch {
        // ignore and re-create
      }
    }

    const id = uuidv4();
    try {
      fs.mkdirSync(path.dirname(this.installationIdPath), { recursive: true });
      fs.writeFileSync(this.installationIdPath, id, 'utf-8');
    } catch {
      // ignore failures, still use id in memory
    }
    return id;
  }
}

function getCliVersion(): string {
  try {
    const pkgPath = path.resolve(__dirname, '../../package.json');
    const pkg = JSON.parse(fs.readFileSync(pkgPath, 'utf-8')) as { version?: string };
    return pkg.version ?? '0.0.0';
  } catch {
    return '0.0.0';
  }
}

function postJson(url: string, body: Record<string, unknown>): Promise<void> {
  return new Promise((resolve, reject) => {
    try {
      const { hostname, pathname, port, protocol } = new URL(url);
      const data = JSON.stringify(body);

      const options: https.RequestOptions = {
        hostname,
        port: port ? Number(port) : protocol === 'https:' ? 443 : 80,
        path: pathname,
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Content-Length': Buffer.byteLength(data),
        },
      };

      const req = https.request(options, (res) => {
        // consume response data to free up memory
        res.on('data', () => undefined);
        res.on('end', () => {
          if (res.statusCode && res.statusCode >= 200 && res.statusCode < 300) {
            resolve();
          } else {
            reject(new Error(`Metrics server responded with status ${res.statusCode}`));
          }
        });
      });

      req.on('error', reject);
      req.write(data);
      req.end();
    } catch (error) {
      reject(error instanceof Error ? error : new Error('Unknown metrics error'));
    }
  });
}
