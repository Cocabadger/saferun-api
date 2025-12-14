# SafeRun CLI

> 🛡️ Human approval layer for AI agent Git operations

[![npm version](https://img.shields.io/npm/v/@saferun/cli.svg)](https://www.npmjs.com/package/@saferun/cli)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

SafeRun protects your Git repositories from dangerous operations executed by AI agents (Cursor, Claude Code, Copilot) and automation tools. It intercepts risky commands and requires human approval via Slack before execution.

## Installation

```bash
npm install -g @saferun/cli
```

## Quick Start

```bash
cd your-repo
saferun setup    # Complete setup wizard
```

The wizard guides you through:
1. **API Key** — Get from [saferun.dev](https://saferun.dev)
2. **Slack** — Bot token + webhook for notifications
3. **GitHub App** — Install [SafeRun GitHub App](https://github.com/apps/saferun-ai)
4. **Shell Wrapper** — Intercepts dangerous commands

## Protected Operations

- `git push --force` / `git push -f`
- `git reset --hard`
- `git branch -D` / `git branch --delete --force`
- `git clean -fd`
- `git commit --no-verify`
- Direct commits to `main` or `master`

## Commands

```bash
saferun setup              # Complete setup wizard
saferun init               # Initialize protection in current repo
saferun status             # Show protection status
saferun status -n 20       # Show last 20 operations
saferun doctor             # Health check
saferun uninstall          # Remove from current repo
saferun uninstall --global # Remove completely
```

## How It Works

1. Shell wrapper intercepts dangerous Git commands
2. SafeRun calculates risk score and detects AI agent
3. Slack notification sent with Approve/Reject buttons
4. You approve → command executes. You reject → command blocked.

Approval timeout: 2 hours.

## Documentation

Full documentation: [github.com/Cocabadger/saferun-api](https://github.com/Cocabadger/saferun-api)

## License

MIT © SafeRun Team
