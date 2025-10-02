/**
 * Command: saferun feedback
 * View and manage detection feedback
 */

import chalk from 'chalk';
import { getGitInfo } from '../utils/git';
import { readFeedback, getFeedbackStats, syncFeedbackQueue } from '../utils/feedback';
import Table from 'cli-table3';

export class FeedbackCommand {
  async stats(): Promise<void> {
    const gitInfo = await getGitInfo();
    if (!gitInfo) {
      console.error(chalk.red('Error: Not a git repository'));
      process.exit(1);
    }

    const stats = await getFeedbackStats(gitInfo.repoRoot);

    console.log(chalk.bold('\n📊 AI Detection Feedback Statistics\n'));

    const table = new Table({
      head: ['Metric', 'Count', 'Percentage'],
      style: { head: ['cyan'] },
    });

    const total = stats.total || 1;
    table.push(
      ['Total feedback', stats.total.toString(), '100%'],
      [
        chalk.green('Correct detections'),
        stats.correct.toString(),
        `${((stats.correct / total) * 100).toFixed(1)}%`,
      ],
      [
        chalk.yellow('False positives'),
        stats.false_positives.toString(),
        `${((stats.false_positives / total) * 100).toFixed(1)}%`,
      ],
      [
        chalk.red('False negatives'),
        stats.false_negatives.toString(),
        `${((stats.false_negatives / total) * 100).toFixed(1)}%`,
      ]
    );

    console.log(table.toString());

    if (stats.total === 0) {
      console.log(chalk.gray('\nNo feedback collected yet'));
      console.log(chalk.gray('Feedback is requested after AI-detected operations'));
    } else {
      const accuracy = ((stats.correct / total) * 100).toFixed(1);
      console.log(chalk.bold(`\nDetection Accuracy: ${accuracy}%`));
    }
  }

  async list(): Promise<void> {
    const gitInfo = await getGitInfo();
    if (!gitInfo) {
      console.error(chalk.red('Error: Not a git repository'));
      process.exit(1);
    }

    const entries = await readFeedback(gitInfo.repoRoot);

    if (entries.length === 0) {
      console.log(chalk.yellow('No feedback entries'));
      return;
    }

    console.log(chalk.bold('\n📋 Feedback Entries\n'));

    const table = new Table({
      head: ['Date', 'Operation', 'Score', 'Action', 'Feedback'],
      style: { head: ['cyan'] },
    });

    entries.slice(-10).forEach((entry) => {
      const feedbackColor =
        entry.user_feedback === 'correct'
          ? chalk.green
          : entry.user_feedback === 'false_positive'
            ? chalk.yellow
            : chalk.red;

      table.push([
        new Date(entry.timestamp).toLocaleString(),
        entry.operation_type || 'unknown',
        entry.total_score.toFixed(2),
        entry.action_taken,
        feedbackColor(entry.user_feedback || 'pending'),
      ]);
    });

    console.log(table.toString());
    console.log(chalk.gray(`\nShowing last 10 of ${entries.length} entries`));
  }

  async sync(): Promise<void> {
    const gitInfo = await getGitInfo();
    if (!gitInfo) {
      console.error(chalk.red('Error: Not a git repository'));
      process.exit(1);
    }

    console.log(chalk.cyan('Syncing feedback to SafeRun backend...'));

    // TODO: Implement actual sync with API client
    console.log(chalk.yellow('⚠️  Sync not yet implemented'));
    console.log(chalk.gray('Feedback is stored locally in .saferun/feedback.queue'));
  }
}