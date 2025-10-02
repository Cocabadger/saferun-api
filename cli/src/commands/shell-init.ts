/**
 * Command: saferun shell-init
 * Setup shell integration for AI session detection
 */

import chalk from 'chalk';
import fs from 'fs';
import os from 'os';
import path from 'path';

export class ShellInitCommand {
  async run(options: { auto?: boolean; shell?: string }): Promise<void> {
    const shell = options.shell || this.detectShell();

    console.log(chalk.cyan('\n🐚 SafeRun Shell Integration Setup\n'));
    console.log(chalk.gray(`Detected shell: ${shell}`));

    const snippet = this.generateSnippet(shell);

    if (options.auto) {
      await this.autoInstall(shell, snippet);
    } else {
      this.showManualInstructions(shell, snippet);
    }
  }

  private detectShell(): string {
    const shellPath = process.env.SHELL || '';

    if (shellPath.includes('zsh')) return 'zsh';
    if (shellPath.includes('bash')) return 'bash';
    if (shellPath.includes('fish')) return 'fish';

    return 'bash'; // Default
  }

  private generateSnippet(shell: string): string {
    const baseSnippet = `
# SafeRun AI Session Detection
export SAFERUN_AI_SESSION="conversational"
export SAFERUN_AGENT_ID="\${USER}-\$(date +%s)"

# Optional: Auto-detect AI prompts
if [[ "\$PS1" =~ "ChatGPT" ]] || [[ "\$PS1" =~ "Claude" ]]; then
  export SAFERUN_DETECTED_AI="true"
fi
`;

    if (shell === 'fish') {
      return `
# SafeRun AI Session Detection
set -x SAFERUN_AI_SESSION "conversational"
set -x SAFERUN_AGENT_ID "$USER-"(date +%s)
`;
    }

    return baseSnippet;
  }

  private async autoInstall(shell: string, snippet: string): Promise<void> {
    const rcFile = this.getRCFile(shell);

    if (!rcFile) {
      console.error(chalk.red(`Unable to detect ${shell} config file`));
      this.showManualInstructions(shell, snippet);
      return;
    }

    console.log(chalk.gray(`\nAdding SafeRun integration to ${rcFile}...\n`));

    // Check if already installed
    if (fs.existsSync(rcFile)) {
      const content = fs.readFileSync(rcFile, 'utf-8');
      if (content.includes('SafeRun AI Session Detection')) {
        console.log(chalk.yellow('⚠️  SafeRun shell integration already installed'));
        return;
      }
    }

    // Append snippet
    fs.appendFileSync(rcFile, '\n' + snippet, 'utf-8');

    console.log(chalk.green('✅ SafeRun shell integration installed'));
    console.log(chalk.bold('\n📝 Next steps:'));
    console.log(chalk.gray(`  1. Restart your terminal, or run:`));
    console.log(chalk.cyan(`     source ${rcFile}`));
    console.log(chalk.gray(`  2. Your AI sessions will now be detected automatically`));
    console.log(chalk.gray(`  3. Test it: saferun status --agents`));
  }

  private showManualInstructions(shell: string, snippet: string): void {
    const rcFile = this.getRCFile(shell) || `~/.${shell}rc`;

    console.log(chalk.bold('\n📋 Manual Installation\n'));
    console.log(chalk.gray(`Add the following to ${rcFile}:`));
    console.log(chalk.cyan(snippet));
    console.log(chalk.gray('\nThen restart your terminal or run:'));
    console.log(chalk.cyan(`  source ${rcFile}`));
  }

  private getRCFile(shell: string): string | null {
    const home = os.homedir();

    const files: Record<string, string[]> = {
      zsh: ['.zshrc', '.zprofile'],
      bash: ['.bashrc', '.bash_profile', '.profile'],
      fish: ['.config/fish/config.fish'],
    };

    const candidates = files[shell] || files.bash;

    for (const file of candidates) {
      const fullPath = path.join(home, file);
      if (fs.existsSync(fullPath)) {
        return fullPath;
      }
    }

    // Return default even if doesn't exist
    return path.join(home, candidates[0]);
  }
}