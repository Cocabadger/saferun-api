/**
 * Command: saferun agent
 * View AI agent detection status (read-only)
 * 
 * NOTE: register/unregister commands were removed for security.
 * Agents should not be able to self-register to bypass protection.
 */

import chalk from 'chalk';
import { getGitInfo } from '../utils/git';
import { getAgentHandshake } from '../utils/agent-handshake';

export class AgentCommand {
  async status(): Promise<void> {
    const gitInfo = await getGitInfo();
    if (!gitInfo) {
      console.error(chalk.red('Error: Not a git repository'));
      process.exit(1);
    }

    const handshake = getAgentHandshake(gitInfo.repoRoot);

    if (!handshake) {
      console.log(chalk.green('✅ No AI agent currently detected'));
      console.log(chalk.gray('\nSafeRun automatically detects AI agents based on:'));
      console.log(chalk.gray('  • Environment variables (CURSOR_*, CLAUDE_*, etc.)'));
      console.log(chalk.gray('  • Process tree analysis'));
      console.log(chalk.gray('  • Terminal session context'));
      return;
    }

    console.log(chalk.bold('\n🤖 Detected Agent\n'));
    console.log(chalk.gray('Agent ID:     ') + chalk.white(handshake.agent_id));
    console.log(chalk.gray('Agent Type:   ') + chalk.white(handshake.agent_type));
    console.log(chalk.gray('Session Start:') + chalk.white(new Date(handshake.session_start).toLocaleString()));

    if (handshake.agent_version) {
      console.log(chalk.gray('Version:      ') + chalk.white(handshake.agent_version));
    }

    if (handshake.metadata) {
      console.log(chalk.gray('\nMetadata:'));
      console.log(chalk.gray(JSON.stringify(handshake.metadata, null, 2)));
    }
  }
}