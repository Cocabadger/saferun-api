# 🛡️ SafeRun

> ⚠️ **Disclaimer:** This is an experimental tool built by a non-engineer to solve a non-engineer's fears. It handles sensitive API tokens using AES-256-GCM encryption. Use at your own risk.

> **Stop AI agents from breaking production**

[![npm version](https://img.shields.io/npm/v/@saferun/cli.svg)](https://www.npmjs.com/package/@saferun/cli)
[![Public Beta](https://img.shields.io/badge/Status-Public%20Beta-blue.svg)](https://github.com/Cocabadger/saferun-api)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Problem:** AI agents (Cursor, Claude Code, Copilot, n8n, LangChain) execute Git commands autonomously. One `git push --force` or `git reset --hard` at 3 AM = lost work, corrupted history, deleted branches.

**Solution:** SafeRun intercepts dangerous operations, blocks execution, sends Slack notification with context → you approve or reject from your phone.

> **v0.6.19 Public Beta** — Actively maintained. Core functionality stable. [Report issues →](https://github.com/Cocabadger/saferun-api/issues)

---

## 🔒 Three Layers of Protection

SafeRun protects at **every level** — whether the operation comes from terminal, API, or GitHub directly:

### Layer 1: CLI Shell Wrapper
Intercepts dangerous Git commands **before** they execute in your terminal:
- `git push --force` / `git push -f` / `--force-with-lease`
- `git reset --hard`
- `git branch -D` / `git branch --delete --force`
- `git clean -fd` (via CLI wrapper only — see Known Limitations)
- `git commit --no-verify` (skips hooks)
- Direct commits to `main` or `master` (protected branches)

### Layer 2: REST API (for automation tools)
Requires approval before executing via API:
- **Repository:** Archive, Unarchive, Delete (permanent!), Transfer ownership, Change visibility (private↔public)
- **Branch:** Delete, Force push
- **Pull Request:** Merge (especially to main/master)
- **GitHub Actions:** Create/delete secrets, Update workflow files
- **Security:** Update/delete branch protection rules

### Layer 3: GitHub Webhooks (catches everything else)
Monitors GitHub events even if CLI is bypassed:
- Force pushes made directly on GitHub
- Branch deletions via GitHub UI
- Merges from other machines/tools
- Any operation that bypasses CLI protection

---

## ⚡ Quick Start (5 minutes)

### Requirements

- **Node.js** 18+
- **Git** 2.29+ (for `reference-transaction` hook — critical for AI agent protection)
- **Slack** workspace (for approval notifications)

### Step 1: Install CLI

```bash
npm install -g @saferun/cli
```

### Step 2: Run Setup Wizard

```bash
cd ~/your-project    # Go to repo you want to protect
saferun setup        # Run wizard from here
```

The wizard guides you through **4 steps**:

#### Step 2.1: API Key
- Go to [saferun.dev](https://saferun.dev) (or saferun-landing.vercel.app)
- Sign up with GitHub or email
- Copy your API key (starts with `sr_...`)
- Paste it in the wizard

#### Step 2.2: Slack Notifications (Required!)
You need **three things** from Slack:

1. **Bot User OAuth Token** (`xoxb-...`):
   - Go to [api.slack.com/apps](https://api.slack.com/apps) → Create New App → From scratch
   - Name it "SafeRun", select your workspace
   - OAuth & Permissions → Add Bot Token Scopes: `chat:write`, `chat:write.public`
   - Install to Workspace → Copy **Bot User OAuth Token**

2. **Webhook URL** (for interactive buttons):
   - Go to Incoming Webhooks → Toggle ON
   - Add New Webhook to Workspace → Select channel
   - Copy the **Webhook URL** (`https://hooks.slack.com/services/...`)

3. **Channel name** (e.g., `#saferun-alerts`):
   - Create a channel in Slack or use existing one
   - Bot will post approval requests there

> ⚠️ **No Slack = No notifications!** You won't see approval requests without Slack configured.

#### Step 2.3: GitHub App
Install the SafeRun GitHub App to enable webhook protection:

👉 **[Install SafeRun GitHub App](https://github.com/apps/saferun-ai)**

- Click Install → Select your account/org → Choose repositories → Install
- This catches operations that bypass CLI (web UI, other machines)

#### Step 2.4: Shell Wrapper
The wizard adds a git wrapper to your `.zshrc` or `.bashrc` that intercepts dangerous commands.

### Step 3: Verify Installation

```bash
saferun doctor    # Check everything is configured
saferun status    # See protection status
```

### Step 4: Test It!

```bash
git reset --hard HEAD~1
```

Expected: SafeRun blocks the command, sends Slack notification, waits for your approval (timeout: 2 hours).

---

## 🔧 How It Works

```
Agent runs: git push --force origin main
                    │
                    ▼
┌───────────────────────────────────────┐
│  Shell Wrapper (Layer 1)              │
│  Detects dangerous command            │
│  Identifies AI agent (Cursor, etc.)   │
└───────────────────────────────────────┘
                    │
                    ▼
┌───────────────────────────────────────┐
│  SafeRun CLI                          │
│  • Calculates risk score (0-10)       │
│  • Extracts context (repo, branch)    │
│  • Sends request to SafeRun API       │
└───────────────────────────────────────┘
                    │
                    ▼
┌───────────────────────────────────────┐
│  SafeRun API                          │
│  • Creates approval record (24h TTL)  │
│  • Sends Slack notification           │
│  • Waits for human decision           │
└───────────────────────────────────────┘
                    │
                    ▼
┌───────────────────────────────────────┐
│  Slack                                │
│  Shows: repo, branch, command,        │
│         risk score, agent name        │
│  Buttons: [Approve] [Reject]          │
└───────────────────────────────────────┘
                    │
        ┌───────────┴───────────┐
        ▼                       ▼
   ✅ Approved            ❌ Rejected
   CLI executes           CLI blocks
   the command            returns error
```

## 🔥 Comprehensive Capability Matrix

### 💻 Layer 1: CLI (Local Protection)
*Intercepts git commands on your machine.*

- `git push --force` / `git push -f` / `--force-with-lease`
- `git reset --hard`
- `git branch -D` / `git branch --delete --force`
- `git clean -fd` (via CLI wrapper only)
- `git commit` with secrets (`.env`, `sk-`, `ghp_`)
- Direct commits to `main` / `master`

### 🤖 Layer 2: API (Autonomous Agents)
*Endpoints for your bots (n8n, LangChain) to execute safely.*

**Operational Endpoints (Execute after Approval):**
*   `POST /v1/github/repos/{owner}/{repo}/archive`
*   `POST /v1/github/repos/{owner}/{repo}/unarchive`
*   `DELETE /v1/github/repos/{owner}/{repo}` (Delete Repo)
*   `DELETE /v1/github/repos/{owner}/{repo}/branches/{branch}`
*   `POST /v1/github/repos/{owner}/{repo}/git/force-push`
*   `PUT /v1/github/repos/{owner}/{repo}/pulls/{pr}/merge`

**Analysis-Only Endpoints (Dry-Run Only):**
*   *Check risk without execution support yet:*
*   `POST /v1/dry-run/github.repo.transfer`
*   `POST /v1/dry-run/github.actions.secret.create`
*   `POST /v1/dry-run/github.workflow.update`

### 🚨 Layer 3: Webhooks (Recovery)
*Watches GitHub events to revert accidents.*

*   **Revert Force Push:** Detects forced updates and allows restoring previous SHA.
*   **Restore Deleted Branch:** Detects deletion and offers "Restore" button.
*   **Secret Leak Revert:** Detects if a secret was pushed and offers instant revert.

### Where Data is Stored

```
~/.saferun/
├── config.yml              # Mode, rules, API URL
├── credentials             # API key (chmod 600)
└── protected-repos.json    # List of protected repos

{repo}/.saferun/
└── logs/
    └── operations.log      # Local activity history
```

> **Privacy:** Only approval requests are sent to the API. Config and logs never leave your machine.

---

## 🤖 Supported AI Agents

SafeRun auto-detects these agents:
- Cursor
- Claude Code  
- Windsurf
- GitHub Copilot
- n8n / LangChain / AutoGPT (via API)

---

## 🔌 API for Automation (n8n, LangChain, AutoGPT)

For autonomous agents, use the REST API directly instead of shell commands.

### Example: Force Push with Approval

**Step 1: Create approval request**
```bash
curl -X POST https://saferun-api.up.railway.app/v1/github/repos/owner/repo/git/force-push \
  -H "X-API-Key: sr_your_api_key" \
  -H "Content-Type: application/json" \
  -d '{
    "token": "ghp_your_github_token",
    "ref": "refs/heads/main",
    "sha": "abc123def456789...",
    "reason": "Fixing commit history after accidental push"
  }'
```

Response:
```json
{
  "change_id": "uuid-xxx",
  "status": "pending",
  "requires_approval": true,
  "risk_score": 9.0,
  "message": "Force push request created. Check Slack for approval."
}
```

**Step 2: Poll for approval (or wait for webhook)**
```bash
curl https://saferun-api.up.railway.app/v1/changes/{change_id} \
  -H "X-API-Key: sr_your_api_key"
```

**Step 3: Execute only if approved**
```bash
# status == "approved" → safe to execute
git push --force origin main
```

### Available API Endpoints

**Repository Operations:**
- `POST /v1/github/repos/{owner}/{repo}/archive` — Archive repository
- `POST /v1/github/repos/{owner}/{repo}/unarchive` — Unarchive repository
- `DELETE /v1/github/repos/{owner}/{repo}` — Delete repository (requires confirmation)

**Branch Operations:**
- `DELETE /v1/github/repos/{owner}/{repo}/branches/{branch}` — Delete branch
- `POST /v1/github/repos/{owner}/{repo}/git/force-push` — Force push

**Pull Request:**
- `PUT /v1/github/repos/{owner}/{repo}/pulls/{pr}/merge` — Merge PR

**Dry-Run Endpoints (legacy):**
- `POST /v1/dry-run/github.repo.archive`
- `POST /v1/dry-run/github.branch.delete`
- `POST /v1/dry-run/github.bulk.close_prs`
- `POST /v1/dry-run/github.force-push`
- `POST /v1/dry-run/github.merge`
- `POST /v1/dry-run/github.repo.delete`
- `POST /v1/dry-run/github.repo.transfer`
- `POST /v1/dry-run/github.actions.secret.create`
- `POST /v1/dry-run/github.actions.secret.delete`
- `POST /v1/dry-run/github.workflow.update`
- `POST /v1/dry-run/github.branch_protection.update`
- `POST /v1/dry-run/github.branch_protection.delete`
- `POST /v1/dry-run/github.repo.visibility.change`

---

## 📋 CLI Commands

```bash
# Setup & Installation
saferun setup              # Complete setup wizard
saferun init               # Initialize protection in current repo
saferun doctor             # Health check and troubleshooting
saferun uninstall          # Remove from current repo
saferun uninstall --global # Remove SafeRun completely

# Monitoring
saferun status             # Show protection status + recent activity
saferun status -n 20       # Show last 20 operations

# Configuration (read-only)
saferun config show        # View current configuration
saferun config slack       # Reconfigure Slack settings
```

> **Security:** There is no `saferun config set` command. Configuration cannot be changed via CLI to prevent AI agents from disabling their own protection.

---

## 🆘 Troubleshooting

**SafeRun not intercepting commands?**
```bash
saferun doctor  # Check shell wrapper status
```

**No Slack notifications?**
- Verify bot token is correct (`xoxb-...`)
- Check channel exists and bot has access
- Re-run `saferun setup` → Slack step

**View activity log:**
```bash
saferun status -n 50  # Last 50 operations
```

---

## ⚠️ Known Limitations (Help Wanted!)

SafeRun protects **Git ref-changing operations** using Git's `reference-transaction` hook (Git 2.29+). Some operations are outside our current scope:

### ✅ Protected Operations

- `git reset --hard` — changes branch ref
- `git branch -D` — deletes branch ref
- `git push --force` — changes remote ref
- `git rebase` — rewrites branch history
- `git checkout <branch>` — updates HEAD ref

### ⚠️ Partial Protection

- ✅ `git clean -fd` — caught by CLI wrapper, but ❌ missed by the core `reference-transaction` hook if the wrapper is bypassed

### ❌ Not Protected

- `rm -rf .git` — filesystem operation → *use Docker/sandbox*
- Deleting hooks — filesystem operation → *use Docker/sandbox*

**Why is `git clean -fd` only partially protected?**

Git's `reference-transaction` hook only fires when refs (branches, tags, HEAD) change. `git clean` removes untracked files without touching any refs — Git simply doesn't call any hook. Our CLI wrapper catches it, but if an agent calls `/usr/bin/git clean` directly, the hook won't fire.

**Adversarial AI agents:**

During testing, we observed AI agents attempting to bypass protection by:
- Calling `/usr/bin/git` directly (✅ now blocked via `reference-transaction`)
- Suggesting to delete hooks (❌ requires OS-level sandboxing)

**Community contributions welcome!** If you know how to intercept these edge cases, please [open an issue](https://github.com/Cocabadger/saferun-api/issues) or PR.

---

## 🔒 Security

- **API keys** stored with `chmod 600` (owner-only read)
- **GitHub tokens** encrypted with AES-256-GCM before storage
- **Logs** stay local, never uploaded
- **Config** stored in `~/.saferun/` — immune to `git reset --hard`
- **No CLI bypass** — agents cannot disable protection via commands

---

## 📄 License

MIT © SafeRun Team

---

## 🤝 Contributing

Issues and PRs welcome! [Open an issue →](https://github.com/Cocabadger/saferun-api/issues)

---

## 🛡️ Don't let AI agents break your repo.

**[Get Started →](#-quick-start-5-minutes)**
