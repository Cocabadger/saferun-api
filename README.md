# 🛡️ SafeRun

> ⚠️ **Disclaimer:** This is an experimental tool. It handles sensitive API tokens using AES-256-GCM encryption. Use at your own risk.

> **Stop AI agents from breaking production**

[![npm version](https://img.shields.io/npm/v/@saferun/cli.svg)](https://www.npmjs.com/package/@saferun/cli)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Problem:** AI agents (Cursor, Claude Code, Copilot, n8n, LangChain) execute Git commands autonomously. One `git push --force` or `git reset --hard` at 3 AM = lost work, corrupted history, deleted branches.

**Solution:** SafeRun acts as a middleware between your terminal and GitHub. It intercepts dangerous operations, blocks execution, and sends a Slack notification → you approve or reject from your phone.

> **v0.6.61** — Active Protection.

---

## 🔒 Three Layers of Protection

SafeRun protects at **every level** — whether the operation comes from terminal, API, or GitHub directly:

### Layer 1: Shell Wrapper (Local)
Intercepts dangerous Git commands **before** they execute in your terminal via shell integration:
- `git clean -fd`
- `git commit --no-verify`

### Layer 2: Core Git Hook (Kernel)
Uses the Git 2.29+ `reference-transaction` hook to catch operations at the core level. This catches agents that try to bypass shell aliases by calling `/usr/bin/git` directly:
- `git rebase` — rewrites branch history
- `git reset --hard` — changes branch ref
- `git push --force` — changes remote ref
- Direct commits to protected branches

### Layer 3: GitHub Webhooks (Recovery)
Real-time alerts & one-click recovery for remote accidents via Slack (requires GitHub App):
- Force pushes made directly on GitHub
- Branch deletions via GitHub UI
- Merges from other machines

---

## 🛡️ Security Architecture: Attack Surface Reduction

SafeRun adheres to the **Principle of Least Privilege (PoLP)**. We intentionally bypass GitHub's `Administration` scope to guarantee that the middleware itself can never become a destructive vector.

### The "Zero-Admin" Guarantee

While GitHub allows an App to request `Administration` rights to automate unarchiving, SafeRun explicitly rejects this permission.

**Technical Rationale:**
* **Non-Destructive by Design:** By omitting `Administration` scope, SafeRun is cryptographically and programmatically incapable of deleting repositories or modifying organization-level access.
* **Risk Mitigation:** Even in the event of a total compromise of the SafeRun instance, the attacker gains ZERO administrative control over your GitHub assets.
* **Audit-Only for High-Value Refs:** We prioritize **Observability over Mutation** for destructive operations.

### Reactive Governance Flow (Repository Archive)

When a high-risk event (e.g., `repository_archived`) is detected via webhook, SafeRun triggers a **Reactive Alarm** instead of an automated mutation:

1. **Alert:** Immediate High-Risk notification in Slack.
2. **Audit:** Records the identity of the actor and the timestamp.
3. **Guidance:** Provides a direct Deep Link to GitHub settings for manual recovery.

> [!IMPORTANT]  
> **SafeRun will NEVER ask for write access to your repository settings.** We provide the human-in-the-loop audit trail, leaving the final "Master Key" operations to your authorized administrators.

---

## ⚡ Quick Start

### Requirements
- **Node.js** 18+
- **Git** 2.29+ (critical for hooks)
- **Slack** workspace

### 1. Install CLI
```bash
npm install -g @saferun/cli
```

### 2. Run Setup Wizard

Navigate to your git repository:

```bash
saferun setup
```

The wizard will guide you through:

1. **API Key** — Linking your account.
2. **Slack** — Connecting notifications.
3. **GitHub App** — Installing recovery tools.
4. **Hooks** — Installing local protection.

---

## 💻 CLI Cheat Sheet

SafeRun works silently. Use these commands for configuration and audit:

* **`saferun setup`**
**Initialize.** Sets up SafeRun in the current repository.
* **`saferun settings branches`**
**Configure.** Interactively select branches to protect (e.g., `main`, `production`).
* **`saferun sync`**
**Update.** Manually pulls latest settings from the cloud.
* **`saferun history`**
**Audit.** Shows the log of recent intercepted operations.
* **`saferun doctor`**
**Diagnose.** Checks connection, hooks, and configuration status.
* **`saferun uninstall`**
**Remove.** Cleans up hooks and configuration.

---

## ↩️ One-Click Revert

If a dangerous operation happens remotely (bypassing local hooks), SafeRun offers instant recovery via Slack:

* ✅ **Force Push** — Restores branch to previous commit SHA
* ✅ **Delete Branch** — Recreates the deleted branch
* ✅ **Merge PR** — Creates a revert commit
* 🚨 **Archive Repo** — Immediate alert & recovery link (Zero-Admin Policy)

> ⚠️ **Note:** Revert works for **GitHub webhook events** (remote operations). Local operations are prevented *before* they happen by the CLI.

---

## 🔒 Protected Operations

SafeRun intercepts the following commands on protected branches:

* `git push --force`
* `git branch -D`
* `git reset --hard`
* `git clean -fd` (via shell integration)
* `git rebase`

**Bypass:**
If you strictly need to bypass SafeRun (e.g., for scripting), you can use standard git bypass flags if your policy allows, or disable protection via `saferun settings branches`.

---

## 🤖 Supported AI Agents

SafeRun has been tested with and protects against:

* Cursor
* Claude Code
* GitHub Copilot CLI
* Windsurf
* n8n / LangChain / AutoGPT (via API integration)

---

## 🤝 Contributing

Issues and PRs welcome! [Open an issue →](https://github.com/Cocabadger/saferun-api/issues)

---

## 🛡️ Don't let AI agents break your repo.

---

## 📄 License

MIT © SafeRun Team

<p align="center">
Built for developers who value sleep. 😴
</p>
