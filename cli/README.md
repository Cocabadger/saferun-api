# SafeRun

**Strict policy enforcement for your git workflow.**
SafeRun acts as a middleware between your terminal and GitHub, preventing accidental data loss and enforcing development policies.

## Features

### Layer 1: Local Protection (Zero Latency)
SafeRun installs git hooks (`pre-push`, `pre-commit`) that intercept dangerous commands **before** they execute.
* **Blocks accidental destruction:** Prevents `force-push`, `branch -D`, `reset --hard` on protected branches.
* **Context-Aware:** Settings are isolated per repository. Protecting `develop` in Project A won't affect Project B.
* **Smart Caching:** Rules are checked locally (0ms latency).

### Layer 2: Approval Workflow
Risky operations trigger an interactive approval request in **Slack**.
1.  You run `git push --force origin main`.
2.  SafeRun blocks the command and sends a notification.
3.  You (or a team lead) click **Approve** in Slack.
4.  The command executes automatically.

### Layer 3: One-Click Revert (Webhooks)
If a dangerous operation bypasses local checks (e.g., via GitHub UI or another machine), SafeRun's GitHub App detects it and offers instant recovery.

*   **Force Push:** Restores branch to previous commit SHA.
*   **Delete Branch:** Recreates the deleted branch.
*   **Merge PR:** Creates a revert commit.
*   **Archive Repo:** Unarchives the repository.

> ⚠️ **Note:** Revert capabilities require the **SafeRun GitHub App** to be installed. CLI-intercepted operations are prevented *before* they happen, so they don't need reverting.

---

## Installation

```bash
npm install -g @saferun/cli
```

## Setup

Navigate to your git repository and run the interactive wizard:

```bash
saferun setup
```

This command will:

1. Link your API Key.
2. Connect Slack & GitHub App.
3. Install necessary Git Hooks (`pre-push`, `reference-transaction`).
4. Register the repository in your global config.

---

## CLI Cheat Sheet

SafeRun works silently in the background. Use these commands for configuration and audit:

### Essentials

*   **`saferun setup`**
    **Initialize.** Sets up SafeRun in the current repository.

*   **`saferun settings branches`**
    **Configure.** Interactively select branches to protect (e.g., `main`, `production`).

### Maintenance

*   **`saferun sync`**
    **Update.** Manually pulls latest settings from the cloud (Auto-sync runs in background).

*   **`saferun doctor`**
    **Diagnose.** Checks connection, hooks, and configuration status.

### Audit

*   **`saferun history`**
    **Audit.** Shows the log of recent intercepted operations and their status.

*   **`saferun config show`**
    **Inspect.** View the current active configuration.

*   **`saferun uninstall`**
    **Remove.** Cleans up hooks and configuration.

---

## Protected Operations

SafeRun intercepts the following commands on protected branches:

* `git push --force`
* `git branch -D`
* `git reset --hard` (via hook)
* `git clean -fd` (via hook - *requires shell integration*)
* `git rebase` (via hook)

**Bypass:**
If you strictly need to bypass SafeRun (e.g., for scripting), you can disable protection temporarily via `saferun settings branches` or use standard git bypass flags if your policy allows.

---

## Troubleshooting

**"Config outdated" message**
SafeRun automatically syncs settings in the background. If you see this, run `saferun sync` to force an update.

**Uninstalling**
To completely remove SafeRun:

1. Run `saferun uninstall --global` (removes configs and hooks).
2. Run `npm uninstall -g @saferun/cli` (removes the binary).

---

<p align="center">
Built for developers who value sleep. 😴
</p>
