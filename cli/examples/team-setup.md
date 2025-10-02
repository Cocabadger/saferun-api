# Team Setup Example

This guide shows how to set up SafeRun for a development team with multiple contributors.

## Scenario

Your team of 5-10 developers uses various AI tools (Cursor, Copilot, ChatGPT). You want:
- Protection for production branches
- Allow developers to force push to feature branches
- Whitelist CI/CD automation
- Track who does what

## Setup Steps

### 1. Repository Owner Setup

**Initialize SafeRun:**

```bash
cd your-team-repo
saferun init --mode strict
```

**Configure protected branches:**

```bash
saferun config set github.protected_branches main,staging,production
```

**Set repository info:**

```bash
saferun config set github.repo your-org/your-repo
```

### 2. Create Team Config Template

Create `.saferun/config.yml` to commit to the repository:

```yaml
mode: strict

api:
  url: https://api.saferun.dev
  # Each developer provides their own API key

github:
  repo: your-org/your-repo
  protected_branches:
    - main
    - staging
    - production

rules:
  force_push:
    action: require_approval
    risk_score: 9.0
    exclude_patterns:
      - "feature/*"
      - "dev/*"
      - "experiment/*"
  
  branch_delete:
    action: require_approval
    risk_score: 7.5
    exclude_patterns:
      - "feature/*"
      - "dev/*"
  
  commit_protected:
    action: block
    risk_score: 10.0

bypass:
  ci: true
  ci_environments:
    enabled: true
    detect_from_env:
      - CI
      - GITHUB_ACTIONS
      - GITLAB_CI
      - JENKINS_URL

telemetry:
  enabled: true
```

**Commit the config:**

```bash
git add .saferun/config.yml
git commit -m "Add SafeRun team configuration"
git push origin main
```

### 3. Developer Onboarding

Each team member runs:

```bash
cd your-team-repo
saferun init
```

This will:
- Use the committed `.saferun/config.yml`
- Install Git hooks locally
- Prompt for API key (optional)

**Optional: Set personal API key**

```bash
# Get API key from https://api.saferun.dev
saferun config set api.key sk-your-personal-key
```

Or set environment variable:

```bash
export SAFERUN_API_KEY=sk-your-personal-key
```

### 4. Whitelist CI/CD Bots

**Whitelist GitHub Actions bot:**

```bash
saferun allow bot "github-actions[bot]@users.noreply.github.com"
```

**Whitelist other automation:**

```bash
saferun allow bot "dependabot[bot]@users.noreply.github.com"
saferun allow ci "jenkins"
```

### 5. Test Team Workflow

**Scenario 1: Developer force pushes to feature branch (allowed)**

```bash
git checkout -b feature/new-ui
# ... make changes ...
git push --force origin feature/new-ui
```

✅ **Result:** Proceeds without approval (excluded by pattern)

**Scenario 2: Developer tries to force push to main (blocked)**

```bash
git push --force origin main
```

⛔ **Result:** Blocked, requires approval

**Scenario 3: CI/CD pushes to staging (allowed)**

```bash
# In CI environment (CI=true)
git push origin staging
```

✅ **Result:** Bypassed due to CI environment detection

## Team Guidelines

### For Developers

**1. Always use SafeRun**

Never disable SafeRun without team approval:
```bash
# DON'T DO THIS without permission:
SAFERUN_DISABLE=1 git push --force
```

**2. Request approval for protected branches**

If you need to force push to main:
```bash
git push --force origin main
# Follow approval URL provided by SafeRun
# Ask team lead for approval in Slack
```

**3. Check status regularly**

```bash
saferun status
```

**4. Report false positives**

If SafeRun blocks something that should be allowed:
```bash
saferun feedback <change-id> too-strict "Should allow X"
```

### For Team Leads

**1. Monitor team activity**

```bash
saferun history --since 7d
```

**2. Review AI operations**

```bash
saferun history --ai-only --export csv > ai-audit.csv
```

**3. Check pending approvals**

```bash
saferun status --pending
```

**4. Adjust rules as needed**

```bash
# Allow more patterns
saferun allow branch 'hotfix/*'

# View current whitelist
saferun allow list
```

## CI/CD Integration

### GitHub Actions Example

Add to `.github/workflows/deploy.yml`:

```yaml
name: Deploy

on:
  push:
    branches: [main]

env:
  SAFERUN_API_KEY: ${{ secrets.SAFERUN_API_KEY }}
  CI: true

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Install SafeRun
        run: npm install -g @saferun/cli
      
      - name: Initialize SafeRun
        run: saferun init --auto
      
      - name: Deploy
        run: |
          # Your deployment commands
          git push production main
```

**Note:** CI environment is automatically bypassed.

### GitLab CI Example

Add to `.gitlab-ci.yml`:

```yaml
deploy:
  stage: deploy
  variables:
    CI: "true"
  before_script:
    - npm install -g @saferun/cli
    - saferun init --auto
  script:
    - # Your deployment commands
  only:
    - main
```

## Monitoring and Reporting

### Weekly Team Report

```bash
#!/bin/bash
# weekly-report.sh

echo "SafeRun Weekly Report"
echo "====================="
echo ""

echo "Total Operations:"
saferun history --since 7d | wc -l

echo ""
echo "AI Operations:"
saferun history --since 7d --ai-only | wc -l

echo ""
echo "Blocked Operations:"
saferun history --since 7d --operation blocked | wc -l

echo ""
echo "Top 10 Operations:"
saferun history --since 7d -n 10
```

### Dashboard Integration

SafeRun metrics are available via API:

```bash
curl https://api.saferun.dev/v1/metrics \
  -H "Authorization: Bearer $SAFERUN_API_KEY"
```

## Troubleshooting

### Developer can't push

**Check if hooks are installed:**
```bash
saferun status
```

**Reinstall if needed:**
```bash
saferun init --force
```

### CI/CD is being blocked

**Verify CI environment detection:**
```bash
# In CI, check:
echo $CI
echo $GITHUB_ACTIONS
```

**Add custom CI flag:**
```yaml
# In config.yml
bypass:
  ci_environments:
    detect_from_env:
      - CI
      - YOUR_CUSTOM_CI_FLAG
```

### Too many false positives

**Adjust rules:**
```bash
# Switch from strict to balanced mode
saferun config set mode balanced
```

Or add more exclusions:
```yaml
rules:
  force_push:
    exclude_patterns:
      - "feature/*"
      - "dev/*"
      - "username/*"  # Add personal branches
```

## Best Practices

1. **Commit `.saferun/config.yml`** to repository
2. **Don't commit API keys** - use environment variables
3. **Review AI operations weekly** - understand AI patterns
4. **Adjust rules based on feedback** - SafeRun learns from your team
5. **Document exceptions** - if you whitelist something, document why
6. **Train new team members** - include SafeRun in onboarding

## Next Steps

- Read [CI/CD Setup](./ci-cd-setup.md) for advanced automation
- Set up [Slack notifications](../docs/notifications.md)
- Configure [custom policies](../docs/policies.md)

## Support

Team having issues? Contact:
- 💬 Team Slack channel: #saferun
- 📧 Support: support@saferun.dev
- 📖 Docs: https://docs.saferun.dev
