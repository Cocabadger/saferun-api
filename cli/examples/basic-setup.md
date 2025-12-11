# Basic Setup Example

This guide shows how to set up SafeRun for a single developer protecting their personal repository.

## Scenario

You're a developer using Cursor AI to help with coding. You want protection against accidental force pushes and branch deletions, especially when AI is making suggestions.

## Setup Steps

### 1. Install SafeRun

```bash
npm install -g @saferun/cli
```

### 2. Initialize in Your Repository

```bash
cd your-project
saferun init
```

**What this does:**
- Creates `.saferun/config.yml`
- Installs Git hooks (pre-push, pre-commit, post-checkout)
- Sets up local cache
- Registers with SafeRun API

### 3. Configure Protection Mode

For personal projects, use **balanced** mode (default):

```bash
saferun config set mode balanced
```

**Modes explained:**
- `strict`: Maximum protection, all dangerous ops require approval
- `balanced`: Common patterns allowed, protected branches require approval (recommended)
- `lenient`: Warnings only, minimal interruption

### 4. Protect Your Main Branches

```bash
saferun config set github.protected_branches main,production
```

### 5. Test the Protection

Try a force push:

```bash
git push --force origin main
```

SafeRun will intercept this and ask for approval:

```
🛡️ SafeRun Protection Active
━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠️ Force push to main

This will overwrite 5 commits on origin/main

Options:
  [a] Approve once
  [d] Deny
  [b] Bypass with code
  [h] View details

Your choice: 
```

## Configuration File

Your `.saferun/config.yml` should look like:

```yaml
mode: balanced
api:
  url: https://api.saferun.dev
  key: your-api-key
github:
  repo: auto
  protected_branches:
    - main
    - production
telemetry:
  enabled: true
```

## Daily Workflow

### Check Status

```bash
saferun status
```

Shows:
- Current protection mode
- Installed hooks
- API status
- Recent activity

### View History

```bash
saferun history -n 10
```

Shows last 10 SafeRun operations.

### Check AI Detection

If using Cursor/Copilot:

```bash
saferun status --agents
```

Shows if AI agent is detected and confidence level.

## Troubleshooting

### SafeRun not intercepting operations

```bash
# Reinstall hooks
saferun init --force
```

## Next Steps

- Read [Team Setup](./team-setup.md) for multi-developer workflows
- Read [CI/CD Setup](./ci-cd-setup.md) for automation integration
- Check the [full documentation](../README.md)

## Tips

**Allow feature branches:**
```bash
saferun allow branch 'feature/*'
```

**View AI-only operations:**
```bash
saferun history --ai-only
```

**Export audit log:**
```bash
saferun history --export csv > audit.csv
```
