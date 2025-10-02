# SafeRun CLI

> 🛡️ Safety middleware for AI agents and automated workflows

SafeRun protects your Git repositories from dangerous operations by AI assistants (Cursor, Copilot, ChatGPT) and automation tools. It intercepts risky commands like force pushes, branch deletions, and hard resets, requiring human approval before execution.

## Why SafeRun?

**AI agents are powerful but can be dangerous:**
- Cursor might force push during an automated refactor at 3 AM
- ChatGPT could delete the wrong branch while "helping" with cleanup
- Copilot might suggest a hard reset that loses important work

**SafeRun provides a safety net:**
- ✅ Intercepts dangerous Git operations
- ✅ Detects AI agents automatically
- ✅ Requires human approval for risky actions
- ✅ Works offline with intelligent caching
- ✅ Tracks all operations for audit

---

## Installation

### Option 1: NPM (Recommended)

```bash
npm install -g @saferun/cli
```

### Option 2: From Source

```bash
git clone https://github.com/Cocabadger/saferun-api.git
cd saferun-api/cli
npm install
npm run build
npm link
```

### Option 3: Binary Download

Download the latest binary from [Releases](https://github.com/Cocabadger/saferun-api/releases)

---

## Quick Start

### 1. Initialize SafeRun in your repository

```bash
cd your-repo
saferun init
```

This will:
- Create `.saferun/config.yml`
- Install Git hooks (pre-push, pre-commit, post-checkout)
- Set up local cache
- Register with SafeRun API (optional)

### 2. Try a protected operation

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

### 3. Check status

```bash
saferun status
```

Shows:
- Current protection mode
- Installed hooks
- API connection status
- Recent activity
- AI agent detection status

---

## AI Agent Detection

SafeRun automatically detects when operations come from AI agents:

### Supported AI Agents

**IDE Assistants:**
- Cursor
- GitHub Copilot
- Windsurf
- Codeium
- Tabnine
- Continue

**Conversational AI:**
- Claude (via API)
- ChatGPT (via API)
- Gemini

**Automation:**
- n8n
- Zapier
- Make
- Notion AI

### Detection Methods

SafeRun uses multiple signals:
1. **Environment variables** - High confidence (e.g., `CURSOR_AI=1`)
2. **Process patterns** - Medium confidence (e.g., parent process name)
3. **Git config** - Low confidence (e.g., user.name contains "bot")
4. **Network monitoring** - Medium confidence (e.g., proxy to AI API)
5. **Agent handshake** - Highest confidence (explicit registration)

### Check AI Detection

```bash
saferun status --agents
```

Output:
```
🤖 AI Agent Detection
━━━━━━━━━━━━━━━━━━━━━━━━━━━
Status: AI Agent Detected
Type: cursor
Confidence: high
Method: environment variable
━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## Commands

### `saferun init`

Initialize SafeRun in current repository.

```bash
saferun init [options]

Options:
  --mode <mode>      Protection mode: strict, balanced, lenient (default: balanced)
  --api-url <url>    SafeRun API URL (default: https://api.saferun.dev)
  --api-key <key>    API key for SafeRun backend
  --offline          Run in offline-only mode
```

**Example:**
```bash
saferun init --mode strict --offline
```

---

### `saferun status`

Show current SafeRun status and recent activity.

```bash
saferun status [options]

Options:
  --agents           Show AI agent detection details
  --pending          Show pending approvals
  --verbose          Show detailed information
```

**Example:**
```bash
saferun status --agents
```

---

### `saferun config`

View or modify SafeRun configuration.

```bash
saferun config <action> [options]

Actions:
  get <key>          Get configuration value
  set <key> <value>  Set configuration value
  show               Show all configuration
  edit               Open config in editor
  reset              Reset to defaults

Options:
  --global           Use global config (~/.saferun/config.yml)
```

**Examples:**
```bash
# View current mode
saferun config get mode

# Change to strict mode
saferun config set mode strict

# Edit config file
saferun config edit

# Show all settings
saferun config show
```

---

### `saferun history`

View operation history and audit log.

```bash
saferun history [options]

Options:
  --since <date>      Show operations since date (e.g., "2024-01-01", "7d")
  --until <date>      Show operations until date
  --operation <type>  Filter by operation (force_push, branch_delete, etc.)
  --ai-only           Show only AI agent operations
  --export <format>   Export to file (json, csv)
  -n <number>         Limit results (default: 20)
```

**Examples:**
```bash
# Last 10 operations
saferun history -n 10

# Operations from last week
saferun history --since 7d

# AI agent operations only
saferun history --ai-only

# Export to CSV
saferun history --export csv > audit.csv
```

---

### `saferun allow`

Whitelist specific operations or patterns.

```bash
saferun allow <type> <value>

Types:
  branch <pattern>   Allow operations on branches matching pattern
  author <email>     Allow operations from specific author
  operation <type>   Allow specific operation type
  
Options:
  --remove           Remove from whitelist
  --list             List all whitelist entries
```

**Examples:**
```bash
# Allow force push to dev branches
saferun allow branch 'dev/*'

# Allow specific bot
saferun allow author 'bot@company.com'

# Remove whitelist entry
saferun allow branch 'dev/*' --remove

# List all whitelisted items
saferun allow --list
```

---

### `saferun agent`

Register AI agent for explicit detection.

```bash
saferun agent <action> [options]

Actions:
  register           Register current agent
  unregister         Unregister agent
  status             Show agent registration status

Options:
  --type <type>      Agent type (cursor, claude, custom)
  --name <name>      Agent name/identifier
```

**Examples:**
```bash
# Register Claude Desktop
saferun agent register --type claude --name "Claude Desktop"

# Check registration
saferun agent status

# Unregister
saferun agent unregister
```

---

### `saferun shell-init`

Initialize SafeRun for AI shell integration (ChatGPT, Claude).

```bash
saferun shell-init [options]

Options:
  --shell <shell>    Shell type (bash, zsh, fish)
  --install          Install shell integration
  --uninstall        Remove shell integration
```

**Example:**
```bash
# Setup for zsh
saferun shell-init --shell zsh --install
```

---

### `saferun feedback`

Submit feedback about SafeRun decisions.

```bash
saferun feedback <change-id> <type> [message]

Types:
  correct            SafeRun made the right decision
  incorrect          SafeRun was wrong
  too-strict         SafeRun was too restrictive
  suggestion         General suggestion
```

**Example:**
```bash
saferun feedback abc123 too-strict "Should allow force push to dev/*"
```

---

### `saferun uninstall`

Uninstall SafeRun from repository.

```bash
saferun uninstall [options]

Options:
  --keep-config      Keep .saferun/config.yml
  --purge            Remove all SafeRun data including logs
```

**Example:**
```bash
saferun uninstall --keep-config
```

---

## Configuration

SafeRun uses `.saferun/config.yml`:

```yaml
# Protection mode
mode: balanced  # strict | balanced | lenient

# API settings
api:
  url: https://api.saferun.dev
  key: your-api-key-here
  timeout: 5000

# Offline mode
offline_mode: false
cache_ttl: 300000  # 5 minutes

# GitHub settings
github:
  repo: auto  # or "owner/repo"
  protected_branches:
    - main
    - master
    - production

# Bypass settings
bypass:
  ci: true
  ci_environments:
    enabled: true
    detect_from_env:
      - CI
      - GITHUB_ACTIONS
      - GITLAB_CI

# Operation rules
rules:
  force_push:
    action: require_approval
    risk_score: 9.0
  
  branch_delete:
    action: require_approval
    risk_score: 7.5
    exclude_patterns:
      - "feature/*"
      - "dev/*"

# Telemetry
telemetry:
  enabled: true
```

---

## Protection Modes

### Strict Mode
- All dangerous operations require approval
- No bypasses except explicit whitelist
- Maximum safety, may slow down workflow

### Balanced Mode (Default)
- Common patterns allowed (e.g., force push to feature branches)
- Protected branches require approval
- Good balance of safety and productivity

### Lenient Mode
- Warnings only, no blocking
- Good for learning or low-risk repositories
- Minimal interruption

---

## Examples

### Example 1: Team Setup

```bash
# Initialize with strict mode
saferun init --mode strict

# Protect main branches
saferun config set github.protected_branches main,production

# Allow dev branches
saferun allow branch 'dev/*'

# Whitelist CI bot
saferun allow author 'github-actions[bot]@users.noreply.github.com'
```

### Example 2: AI Development Setup

```bash
# Initialize with AI agent detection
saferun init --mode balanced

# Register Cursor as AI agent
saferun agent register --type cursor --name "Cursor IDE"

# View AI operations
saferun history --ai-only

# Check AI detection
saferun status --agents
```

### Example 3: Offline Mode

```bash
# Initialize in offline mode
saferun init --offline --mode balanced

# Configure longer cache
saferun config set cache_ttl 900000  # 15 minutes

# Operations work without API
git push --force origin dev/feature
```

---

## Troubleshooting

### SafeRun not intercepting operations

**Check hooks are installed:**
```bash
ls -la .git/hooks/
```

You should see:
- `pre-push` (SafeRun wrapper)
- `pre-commit` (SafeRun wrapper)
- `post-checkout` (SafeRun wrapper)

**Reinstall hooks:**
```bash
saferun init --force
```

---

### AI agent not detected

**Check environment:**
```bash
saferun status --agents
```

**Manually register agent:**
```bash
saferun agent register --type cursor
```

**Check detection signals:**
```bash
# Enable debug mode
export SAFERUN_DEBUG=1
git push --force origin dev
```

---

### API connection issues

**Test API connection:**
```bash
saferun status
```

Look for "SafeRun API: reachable"

**Switch to offline mode:**
```bash
saferun config set offline_mode true
```

**Change API URL:**
```bash
saferun config set api.url https://your-server.com
```

---

### Bypass SafeRun temporarily

**Disable for single operation:**
```bash
SAFERUN_DISABLE=1 git push --force origin main
```

**Disable globally:**
```bash
saferun config set mode lenient
```

**Uninstall:**
```bash
saferun uninstall
```

---

## Architecture

```
┌─────────────────┐
│   Git Command   │
│  (force push)   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   Git Hook      │
│  (pre-push)     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  SafeRun CLI    │
│  - AI Detection │
│  - Cache Check  │
│  - Risk Assess  │
└────────┬────────┘
         │
    ┌────┴────┐
    ▼         ▼
┌────────┐ ┌──────────┐
│ Cache  │ │ SafeRun  │
│        │ │   API    │
└────────┘ └─────┬────┘
                 │
                 ▼
         ┌───────────────┐
         │  Approval UI  │
         │  (Web/CLI)    │
         └───────┬───────┘
                 │
                 ▼
         ┌───────────────┐
         │   Approve?    │
         │   ├─ Yes → ✓  │
         │   └─ No  → ✗  │
         └───────────────┘
```

---

## Contributing

We welcome contributions! Please see [CONTRIBUTING.md](../CONTRIBUTING.md)

---

## License

MIT License - see [LICENSE](../LICENSE)

---

## Support

- 📖 Documentation: https://saferun-landing.vercel.app
- 🐛 Issues: https://github.com/Cocabadger/saferun-api/issues
- 📧 Email: support@saferun.dev

---

## Roadmap

- [ ] VS Code extension
- [ ] Slack notifications
- [ ] Team dashboards
- [ ] ML-based risk scoring
- [ ] More AI agent integrations
- [ ] Policy templates
- [ ] Compliance reports

---

**Built with ❤️ by the SafeRun team**
