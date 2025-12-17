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

SafeRun uses **multiple layers** of protection:

1. **Shell Wrapper** — Intercepts `git` commands in interactive shells
2. **Git Hooks** — `pre-commit`, `pre-push`, `post-checkout`
3. **reference-transaction Hook** — Intercepts ALL ref changes at Git core level (Git 2.29+)

The `reference-transaction` hook is the **most reliable** layer — it catches operations even when AI agents call `/usr/bin/git` directly, bypassing shell aliases and PATH wrappers.

```
AI Agent → /usr/bin/git reset --hard → Git internals → reference-transaction hook → SafeRun blocks!
```

When a dangerous operation is detected:
1. SafeRun calculates risk score and detects AI agent
2. Slack notification sent with Approve/Reject buttons
3. You approve → command executes. You reject → command blocked.

Approval timeout: 2 hours.

## Requirements

- **Node.js** 18+
- **Git** 2.29+ (for `reference-transaction` hook)
- **Slack** workspace with bot token

## Known Limitations (Help Wanted! 🙏)

SafeRun protects **Git ref-changing operations**. Some operations are outside our scope:

**✅ Protected Operations** (ref-changing):
- `git reset --hard` — changes branch ref
- `git branch -D` — deletes branch ref  
- `git push --force` — changes remote ref
- `git rebase` — rewrites branch ref
- `git checkout` to different branch — updates HEAD ref

**❌ Not Protected** (no ref change):
- `git clean -fd` — deletes untracked files only → *use `.gitignore`*
- `rm -rf .git` — filesystem operation → *use Docker/sandbox*
- Deleting `.git/hooks/` — filesystem operation → *use Docker/sandbox*

**Why can't we protect `git clean`?**
Git's `reference-transaction` hook only fires when refs change. `git clean` deletes untracked files without touching refs.

**Community contributions welcome!** If you know how to intercept these operations, please open an issue or PR.

## Documentation

Full documentation: [github.com/Cocabadger/saferun-api](https://github.com/Cocabadger/saferun-api)

## License

MIT © SafeRun Team
