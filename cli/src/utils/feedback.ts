/**
 * Local Feedback Queue
 * Collects user feedback on AI detection accuracy for continuous improvement
 */

import fs from 'fs';
import path from 'path';
import { DetectionSignal } from './ai-detection';

export interface FeedbackEntry {
  id: string;
  timestamp: string;
  detection_id: string;
  signals: DetectionSignal[];
  total_score: number;
  action_taken: string;
  operation_type?: string;
  user_feedback?: 'correct' | 'false_positive' | 'false_negative';
  user_comment?: string;
}

const FEEDBACK_FILE = 'feedback.queue';

/**
 * Save feedback entry to queue
 */
export async function saveFeedback(repoRoot: string, entry: Omit<FeedbackEntry, 'id' | 'timestamp'>): Promise<void> {
  const feedbackPath = path.join(repoRoot, '.saferun', FEEDBACK_FILE);
  const saferunDir = path.dirname(feedbackPath);

  if (!fs.existsSync(saferunDir)) {
    fs.mkdirSync(saferunDir, { recursive: true });
  }

  const fullEntry: FeedbackEntry = {
    ...entry,
    id: generateFeedbackId(),
    timestamp: new Date().toISOString(),
  };

  // Append to file (JSONL format)
  const line = JSON.stringify(fullEntry) + '\n';
  fs.appendFileSync(feedbackPath, line, 'utf-8');
}

/**
 * Read all feedback entries
 */
export async function readFeedback(repoRoot: string): Promise<FeedbackEntry[]> {
  const feedbackPath = path.join(repoRoot, '.saferun', FEEDBACK_FILE);

  if (!fs.existsSync(feedbackPath)) {
    return [];
  }

  try {
    const content = fs.readFileSync(feedbackPath, 'utf-8');
    const lines = content.trim().split('\n').filter(Boolean);

    return lines.map((line) => JSON.parse(line) as FeedbackEntry);
  } catch {
    return [];
  }
}

/**
 * Get pending feedback (not yet synced to backend)
 */
export async function getPendingFeedback(repoRoot: string): Promise<FeedbackEntry[]> {
  const entries = await readFeedback(repoRoot);
  // In future: filter by sync status
  return entries;
}

/**
 * Prompt user for feedback on detection
 */
export async function promptFeedback(
  repoRoot: string,
  detectionId: string,
  signals: DetectionSignal[],
  score: number,
  action: string,
  operationType?: string
): Promise<void> {
  // Only prompt if telemetry is enabled
  const { loadConfig } = await import('./config');
  const config = await loadConfig(repoRoot);

  if (!config.telemetry?.enabled) {
    return;
  }

  // Skip prompt in non-interactive mode
  if (!process.stdin.isTTY) {
    return;
  }

  console.log('\n' + require('chalk').gray('─'.repeat(50)));
  console.log(require('chalk').bold('📊 Help improve SafeRun AI detection'));
  console.log(require('chalk').gray('Was this AI detection correct?'));
  console.log('  y - Yes, correct detection');
  console.log('  n - No, false positive (detected AI but was human)');
  console.log('  f - False negative (was AI but not detected)');
  console.log('  s - Skip');

  const readline = require('readline');
  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
  });

  const answer = await new Promise<string>((resolve) => {
    rl.question('\nYour feedback (y/n/f/s): ', (answer: string) => {
      rl.close();
      resolve(answer.toLowerCase().trim());
    });
  });

  let userFeedback: FeedbackEntry['user_feedback'] | undefined;
  switch (answer) {
    case 'y':
    case 'yes':
      userFeedback = 'correct';
      break;
    case 'n':
    case 'no':
      userFeedback = 'false_positive';
      break;
    case 'f':
      userFeedback = 'false_negative';
      break;
    default:
      return; // Skip
  }

  await saveFeedback(repoRoot, {
    detection_id: detectionId,
    signals,
    total_score: score,
    action_taken: action,
    operation_type: operationType,
    user_feedback: userFeedback,
  });

  console.log(require('chalk').green('✓ Feedback saved. Thank you!'));
  console.log(require('chalk').gray('Disable feedback: saferun config set telemetry.enabled false'));
}

/**
 * Sync feedback queue to backend (when online)
 */
export async function syncFeedbackQueue(repoRoot: string, apiClient: any): Promise<number> {
  const pending = await getPendingFeedback(repoRoot);

  if (pending.length === 0) {
    return 0;
  }

  try {
    // Send to backend
    const response = await apiClient.post('/v1/feedback/batch', {
      feedback: pending,
    });

    if (response.ok) {
      // Clear synced entries (in future: mark as synced instead of delete)
      const feedbackPath = path.join(repoRoot, '.saferun', FEEDBACK_FILE);
      fs.writeFileSync(feedbackPath, '', 'utf-8');
      return pending.length;
    }
  } catch {
    // Silently fail - keep in queue for next sync
  }

  return 0;
}

/**
 * Generate unique feedback ID
 */
function generateFeedbackId(): string {
  return `fb_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`;
}

/**
 * Get feedback statistics
 */
export async function getFeedbackStats(repoRoot: string): Promise<{
  total: number;
  correct: number;
  false_positives: number;
  false_negatives: number;
}> {
  const entries = await readFeedback(repoRoot);

  return {
    total: entries.length,
    correct: entries.filter((e) => e.user_feedback === 'correct').length,
    false_positives: entries.filter((e) => e.user_feedback === 'false_positive').length,
    false_negatives: entries.filter((e) => e.user_feedback === 'false_negative').length,
  };
}