/**
 * Command: saferun shell-init
 * Setup shell integration for AI session detection and git command interception
 */

import chalk from 'chalk';
import fs from 'fs';
import os from 'os';
import path from 'path';

export class ShellInitCommand {
  async run(options: { auto?: boolean; shell?: string; quiet?: boolean }): Promise<void> {
    const shell = options.shell || this.detectShell();
    const snippet = this.generateSnippet(shell);

    // If called as eval "$(saferun shell-init)" - just output the snippet
    // Detect by checking if stdout is not a TTY (piped)
    const isPiped = !process.stdout.isTTY;
    
    if (isPiped || options.quiet) {
      // Output only shell code for eval
      console.log(snippet);
      return;
    }

    console.log(chalk.cyan('\n🐚 SafeRun Shell Integration Setup\n'));
    console.log(chalk.gray(`Detected shell: ${shell}`));

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
    if (shell === 'fish') {
      return this.generateFishSnippet();
    }

    // Bash/Zsh snippet
    return `
# ============================================
# SafeRun Shell Integration
# Protects against dangerous git operations
# ============================================

# AI Session Detection
export SAFERUN_AI_SESSION="conversational"
export SAFERUN_AGENT_ID="\${USER}-\$(date +%s)"

# Git Command Interceptor
# Catches dangerous operations in SafeRun-protected repos
git() {
  # Check if we're in a SafeRun protected repo (using global registry)
  # This check is fast and cannot be bypassed by modifying repo files
  if saferun is-protected --quiet 2>/dev/null; then
    local cmd="\$1"
    local all_args="\$*"
    
    case "\$cmd" in
      commit)
        # Block --no-verify (bypasses pre-commit hooks)
        if [[ "\$all_args" == *"--no-verify"* ]] || [[ "\$all_args" == *" -n "* ]] || [[ "\$all_args" == *" -n\$"* ]]; then
          echo -e "\\033[33m⚠️  SafeRun: git commit --no-verify detected\\033[0m"
          echo -e "\\033[90m   This bypasses pre-commit security hooks.\\033[0m"
          saferun hook git-commit "\${@:2}"
          return \$?
        fi
        ;;
      push)
        # Intercept --force and --no-verify
        if [[ "\$all_args" == *"--force"* ]] || [[ "\$all_args" == *" -f "* ]] || [[ "\$all_args" == *" -f\$"* ]]; then
          saferun hook git-push "\${@:2}"
          return \$?
        fi
        if [[ "\$all_args" == *"--no-verify"* ]]; then
          echo -e "\\033[33m⚠️  SafeRun: git push --no-verify detected\\033[0m"
          saferun hook git-push "\${@:2}"
          return \$?
        fi
        ;;
      branch)
        # Intercept branch deletion
        if [[ "\$all_args" == *"-D"* ]] || [[ "\$all_args" == *"--delete"* ]]; then
          saferun hook git-branch "\${@:2}"
          return \$?
        fi
        ;;
      reset)
        # Intercept hard reset
        if [[ "\$all_args" == *"--hard"* ]]; then
          saferun hook git-reset "\${@:2}"
          return \$?
        fi
        ;;
      clean)
        # Intercept force clean
        if [[ "\$all_args" == *"-f"* ]]; then
          saferun hook git-clean "\${@:2}"
          return \$?
        fi
        ;;
      rebase)
        # Intercept all rebase operations (especially interactive)
        saferun hook git-rebase "\${@:2}"
        return \$?
        ;;
      config)
        # Block attempts to disable hooks
        if [[ "\$all_args" == *"core.hooksPath"* ]]; then
          echo -e "\\033[31m🛑 SafeRun: Blocked attempt to modify hooks path\\033[0m"
          echo -e "\\033[90m   Changing core.hooksPath can disable SafeRun protection.\\033[0m"
          return 1
        fi
        ;;
    esac
  fi
  
  # Pass through to real git
  command git "\$@"
}

# Protect against direct hook deletion
rm() {
  if [[ "\$*" == *".git/hooks"* ]]; then
    echo -e "\\033[31m🛑 SafeRun: Blocked deletion of git hooks\\033[0m"
    return 1
  fi
  command rm "\$@"
}

# End SafeRun Shell Integration
`;
  }

  private generateFishSnippet(): string {
    return `
# ============================================
# SafeRun Shell Integration (Fish)
# Protects against dangerous git operations
# ============================================

set -x SAFERUN_AI_SESSION "conversational"
set -x SAFERUN_AGENT_ID "$USER-"(date +%s)

function git --wraps git
  # Check if we're in a SafeRun protected repo (using global registry)
  if saferun is-protected --quiet 2>/dev/null
    set -l cmd $argv[1]
    set -l all_args "$argv"
    
    switch $cmd
      case commit
        if string match -q "*--no-verify*" $all_args; or string match -q "* -n *" $all_args
          echo "⚠️  SafeRun: git commit --no-verify detected"
          saferun hook git-commit $argv[2..-1]
          return $status
        end
      case push
        if string match -q "*--force*" $all_args; or string match -q "* -f *" $all_args
          saferun hook git-push $argv[2..-1]
          return $status
        end
      case branch
        if string match -q "*-D*" $all_args; or string match -q "*--delete*" $all_args
          saferun hook git-branch $argv[2..-1]
          return $status
        end
      case reset
        if string match -q "*--hard*" $all_args
          saferun hook git-reset $argv[2..-1]
          return $status
        end
      case clean
        if string match -q "*-f*" $all_args
          saferun hook git-clean $argv[2..-1]
          return $status
        end
      case rebase
        # Intercept all rebase operations
        saferun hook git-rebase $argv[2..-1]
        return $status
      case config
        if string match -q "*core.hooksPath*" $all_args
          echo "🛑 SafeRun: Blocked attempt to modify hooks path"
          return 1
        end
    end
  end
  
  command git $argv
end

# End SafeRun Shell Integration
`;
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
      if (content.includes('SafeRun Shell Integration')) {
        console.log(chalk.yellow('⚠️  SafeRun shell integration already installed'));
        console.log(chalk.gray('   To reinstall, remove the SafeRun section from ' + rcFile));
        return;
      }
    }

    // Append snippet
    fs.appendFileSync(rcFile, '\n' + snippet, 'utf-8');

    console.log(chalk.green('✅ SafeRun shell integration installed'));
    console.log(chalk.bold('\n📝 What was added:'));
    console.log(chalk.gray('  • Git command interceptor (catches --no-verify, --force, -D)'));
    console.log(chalk.gray('  • Hook deletion protection'));
    console.log(chalk.gray('  • AI session detection'));
    console.log(chalk.bold('\n🔄 Next steps:'));
    console.log(chalk.gray(`  1. Restart your terminal, or run:`));
    console.log(chalk.cyan(`     source ${rcFile}`));
    console.log(chalk.gray(`  2. Test it:`));
    console.log(chalk.cyan(`     cd <your-saferun-repo> && git commit --no-verify -m "test"`));
    console.log(chalk.gray(`  3. SafeRun should intercept the command`));
  }

  private showManualInstructions(shell: string, snippet: string): void {
    const rcFile = this.getRCFile(shell) || `~/.${shell}rc`;

    console.log(chalk.bold('\n📋 Manual Installation\n'));
    console.log(chalk.gray(`Add the following to ${rcFile}:`));
    console.log(chalk.cyan('─'.repeat(50)));
    console.log(snippet);
    console.log(chalk.cyan('─'.repeat(50)));
    console.log(chalk.gray('\nThen restart your terminal or run:'));
    console.log(chalk.cyan(`  source ${rcFile}`));
    console.log(chalk.bold('\n💡 Or install automatically:'));
    console.log(chalk.cyan('  saferun shell-init --auto'));
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