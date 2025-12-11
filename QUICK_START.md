# SafeRun Quick Start (60 seconds)

## 🚀 Installation

```bash
npm install -g @saferun/cli
saferun init
```

## ✅ What SafeRun Protects

SafeRun catches **85% of dangerous Git operations** before they happen:

### ✅ Fully Protected (100%)
- ✅ `git push --force` → Requires approval
- ✅ `git push --delete` → Requires approval
- ✅ `git commit` with secrets (.env, API keys) → **BLOCKED**
- ✅ Repository deletion → Requires approval

### ⚠️ Partially Protected (Webhooks)
- ⚠️ `curl` GitHub API calls → Detected post-facto, can revert
- ⚠️ PR merges → Branch Protection recommended

### ❌ Not Protected (Out of Scope)
- ❌ `npm uninstall` / `pip uninstall` → Not Git operations
- ❌ `rm -rf` file operations → OS-level permissions

## 🛡️ Defense Layers

1. **CLI Hooks** → Intercepts git commands (70% coverage)
2. **GitHub Webhooks** → Catches everything post-facto (100% coverage)
3. **Revert System** → Undoes 80% of operations

## ⚙️ Configuration

Edit `.saferun/config.json`:

```json
{
  "mode": "ai-assisted",
  "github": {
    "protected_branches": ["main", "production"],
    "repo": "auto"
  },
  "bypass": {
    "ci": true  // Bypass in CI/CD only
  }
}
```

## 🔐 Security Best Practices

1. **Token Permissions:** DO NOT grant `delete_repo` scope
2. **Branch Protection:** Enable GitHub Branch Protection Rules
3. **Secrets:** Use `.env` files (SafeRun blocks commits with secrets)

## 🎯 What SafeRun Does NOT Do

- ❌ Not an anti-virus (doesn't scan for malicious code)
- ❌ Not a complete AI sandbox (focus on Git operations)
- ❌ Not a replacement for access controls (use GitHub permissions)

**SafeRun prevents accidental AI mistakes, not malicious attacks.**

## 📚 Learn More

- Full docs: https://saferun.dev/docs
- API reference: https://saferun.dev/api
- GitHub: https://github.com/saferun-ai

---

**Install in 60 seconds. Protect your repos from AI mistakes.**
