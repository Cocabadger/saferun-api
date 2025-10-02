import chalk from 'chalk';
import fs from 'fs';
import { getGitInfo, isGitRepository } from '../utils/git';
import { readLogEntries, LogEntry } from '../utils/logger';

export interface HistoryOptions {
  limit: number;
  since?: string;
  until?: string;
  operation?: string;
  aiOnly?: boolean;
  export?: 'json' | 'csv';
}

export class HistoryCommand {
  async run(options: HistoryOptions): Promise<void> {
    const isRepo = await isGitRepository();
    if (!isRepo) {
      console.error(chalk.red('❌ Not inside a git repository.'));
      process.exitCode = 1;
      return;
    }

    const gitInfo = await getGitInfo();
    if (!gitInfo) {
      console.error(chalk.red('❌ Unable to determine git repository information.'));
      process.exitCode = 1;
      return;
    }

    const entries = await readLogEntries(gitInfo.repoRoot);
    if (entries.length === 0) {
      console.log(chalk.gray('No SafeRun activity has been recorded yet.'));
      return;
    }

    // Apply filters
    let filtered = this.filterEntries(entries, options);

    // Limit results
    const limited = filtered.slice(-options.limit);

    // Export if requested
    if (options.export) {
      await this.exportEntries(limited, options.export);
      console.log(chalk.green(`✓ Exported ${limited.length} entries to ${options.export} format`));
      return;
    }

    // Display results
    this.displayEntries(limited);
  }

  private filterEntries(entries: LogEntry[], options: HistoryOptions): LogEntry[] {
    let filtered = [...entries];

    // Filter by date range
    if (options.since) {
      const sinceDate = this.parseDate(options.since);
      filtered = filtered.filter((entry) => {
        const entryDate = new Date(entry.ts || 0);
        return entryDate >= sinceDate;
      });
    }

    if (options.until) {
      const untilDate = this.parseDate(options.until);
      filtered = filtered.filter((entry) => {
        const entryDate = new Date(entry.ts || 0);
        return entryDate <= untilDate;
      });
    }

    // Filter by operation type
    if (options.operation) {
      filtered = filtered.filter((entry) => {
        const op = entry.operation as string | undefined;
        return op && op.toLowerCase().includes(options.operation!.toLowerCase());
      });
    }

    // Filter AI-only
    if (options.aiOnly) {
      filtered = filtered.filter((entry) => entry.is_ai_generated === true);
    }

    return filtered;
  }

  private parseDate(dateStr: string): Date {
    // Handle relative dates like "7d", "2w", "1m"
    const match = dateStr.match(/^(\d+)([dwmy])$/);
    if (match) {
      const amount = parseInt(match[1], 10);
      const unit = match[2];
      const now = new Date();

      switch (unit) {
        case 'd':
          now.setDate(now.getDate() - amount);
          break;
        case 'w':
          now.setDate(now.getDate() - amount * 7);
          break;
        case 'm':
          now.setMonth(now.getMonth() - amount);
          break;
        case 'y':
          now.setFullYear(now.getFullYear() - amount);
          break;
      }

      return now;
    }

    // Handle absolute dates
    return new Date(dateStr);
  }

  private displayEntries(entries: LogEntry[]): void {
    if (entries.length === 0) {
      console.log(chalk.gray('No matching entries found.'));
      return;
    }

    console.log(chalk.cyan(`\nSafeRun history (${entries.length} events)\n`));

    for (const entry of entries) {
      const ts = typeof entry.ts === 'string' ? entry.ts : 'unknown';
      const event = typeof entry.event === 'string' ? entry.event : 'event';
      const outcome = typeof entry.outcome === 'string' ? entry.outcome : entry.reason ?? '';

      // Build summary
      const summaryParts: string[] = [];
      if (typeof entry.repo === 'string') summaryParts.push(`repo=${entry.repo}`);
      if (typeof entry.branch === 'string') summaryParts.push(`branch=${entry.branch}`);
      if (typeof entry.operation === 'string') summaryParts.push(`op=${entry.operation}`);
      if (typeof entry.target === 'string') summaryParts.push(`target=${entry.target}`);

      // Add AI indicator
      if (entry.is_ai_generated) {
        const aiType = entry.ai_agent_type || 'unknown';
        summaryParts.push(chalk.magenta(`🤖 ${aiType}`));
      }

      const summary = summaryParts.join(' ');
      const line = `${chalk.gray(ts)}  ${chalk.yellow(event)}${outcome ? ` ${chalk.green(outcome)}` : ''}${summary ? ` ${summary}` : ''}`;
      console.log(line);
    }
  }

  private async exportEntries(entries: LogEntry[], format: 'json' | 'csv'): Promise<void> {
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
    const filename = `saferun-history-${timestamp}.${format}`;

    if (format === 'json') {
      await fs.promises.writeFile(filename, JSON.stringify(entries, null, 2), 'utf-8');
    } else if (format === 'csv') {
      const csv = this.entriesToCSV(entries);
      await fs.promises.writeFile(filename, csv, 'utf-8');
    }

    console.log(chalk.gray(`Written to: ${filename}`));
  }

  private entriesToCSV(entries: LogEntry[]): string {
    if (entries.length === 0) return '';

    // Get all unique keys
    const keys = new Set<string>();
    entries.forEach((entry) => {
      Object.keys(entry).forEach((key) => keys.add(key));
    });

    const headers = Array.from(keys);
    const rows = entries.map((entry) =>
      headers.map((key) => {
        const value = entry[key];
        if (value === null || value === undefined) return '';
        const str = String(value);
        // Escape commas and quotes
        return str.includes(',') || str.includes('"') ? `"${str.replace(/"/g, '""')}"` : str;
      }),
    );

    const lines = [headers.join(','), ...rows.map((row) => row.join(','))];
    return lines.join('\n');
  }
}
