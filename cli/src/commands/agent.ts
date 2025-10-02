/**
 * Command: saferun agent
 * Manage AI agent registration
 */

import chalk from 'chalk';
import { getGitInfo } from '../utils/git';
import { registerAgent, unregisterAgent, getAgentHandshake, createHandshake } from '../utils/agent-handshake';

export class AgentCommand {
  async register(type: string, options: { id?: string; version?: string }): Promise<void> {
    const gitInfo = await getGitInfo();
    if (!gitInfo) {
      console.error(chalk.red('Error: Not a git repository'));
      process.exit(1);
    }

    const handshake = createHandshake(type, {
      agentId: options.id,
      version: options.version,
    });

    registerAgent(handshake, gitInfo.repoRoot);

    console.log(chalk.green('✅ Agent registered successfully'));
    console.log(chalk.gray(`\nAgent ID: ${handshake.agent_id}`));
    console.log(chalk.gray(`Agent Type: ${handshake.agent_type}`));
    console.log(chalk.gray(`Session Start: ${handshake.session_start}`));
    console.log(chalk.bold('\n💡 This agent will now be detected with 100% confidence'));
  }

  async unregister(): Promise<void> {
    const gitInfo = await getGitInfo();
    if (!gitInfo) {
      console.error(chalk.red('Error: Not a git repository'));
      process.exit(1);
    }

    unregisterAgent(gitInfo.repoRoot);
    console.log(chalk.green('✅ Agent unregistered'));
  }

  async status(): Promise<void> {
    const gitInfo = await getGitInfo();
    if (!gitInfo) {
      console.error(chalk.red('Error: Not a git repository'));
      process.exit(1);
    }

    const handshake = getAgentHandshake(gitInfo.repoRoot);

    if (!handshake) {
      console.log(chalk.yellow('No agent registered'));
      console.log(chalk.gray('\nRegister an agent with:'));
      console.log(chalk.gray('  saferun agent register <type>'));
      console.log(chalk.gray('\nSupported types: chatgpt, claude, n8n, zapier, custom'));
      return;
    }

    console.log(chalk.bold('\n🤖 Registered Agent\n'));
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