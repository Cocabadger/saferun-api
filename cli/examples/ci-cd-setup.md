# CI/CD Setup Example

This guide shows how to integrate SafeRun with continuous integration and deployment pipelines.

## Scenario

Your team uses automated deployments and you want:
- SafeRun protection in development
- Automatic bypass for CI/CD
- Audit trail of automated operations
- Safety checks even in automation

## Overview

SafeRun automatically detects CI/CD environments and adjusts behavior:
- **Development:** Full protection with approvals
- **CI/CD:** Bypasses approvals but still logs operations
- **Emergency:** Can override even in CI

## GitHub Actions

### Basic Setup

```yaml
name: CI/CD Pipeline

on:
  push:
    branches: [main, staging]
  pull_request:
    branches: [main]

env:
  # CI env var enables automatic bypass
  CI: true
  SAFERUN_API_KEY: ${{ secrets.SAFERUN_API_KEY }}

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Setup Node
        uses: actions/setup-node@v3
        with:
          node-version: '18'
      
      - name: Install SafeRun
        run: npm install -g @saferun/cli
      
      - name: Initialize SafeRun
        run: saferun init --auto --mode balanced
      
      - name: Run tests
        run: npm test
  
  deploy:
    needs: test
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'
    steps:
      - uses: actions/checkout@v3
      
      - name: Setup Node
        uses: actions/setup-node@v3
        with:
          node-version: '18'
      
      - name: Install SafeRun
        run: npm install -g @saferun/cli
      
      - name: Initialize SafeRun
        run: saferun init --auto
      
      - name: Deploy to production
        run: |
          # SafeRun will log but not block
          git push production main --force
      
      - name: Check SafeRun status
        run: saferun status
      
      - name: Upload audit log
        run: |
          saferun history --since 1h --export json > saferun-audit.json
        
      - uses: actions/upload-artifact@v3
        with:
          name: saferun-audit
          path: saferun-audit.json
```

### Advanced: Conditional Protection

Enable SafeRun protection even in CI for critical operations:

```yaml
deploy-critical:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v3
    
    - name: Install SafeRun
      run: npm install -g @saferun/cli
    
    - name: Init SafeRun with strict mode
      run: |
        saferun init --auto --mode strict
        # Override CI bypass for this critical operation
        saferun config set bypass.ci false
    
    - name: Critical deployment (requires approval)
      run: |
        # This WILL require approval even in CI
        git push production main
```

## GitLab CI

### Basic Setup

```yaml
stages:
  - test
  - deploy

variables:
  CI: "true"
  SAFERUN_API_KEY: $SAFERUN_API_KEY

before_script:
  - npm install -g @saferun/cli
  - saferun init --auto

test:
  stage: test
  script:
    - npm test
  only:
    - branches

deploy:
  stage: deploy
  script:
    - saferun status
    - git push production main
    - saferun history --since 1h
  only:
    - main
  artifacts:
    paths:
      - .saferun/logs/
    expire_in: 30 days
```

### Multiple Environments

```yaml
.deploy_template: &deploy_config
  before_script:
    - npm install -g @saferun/cli
    - saferun init --auto
  after_script:
    - saferun history --export json > saferun-$CI_ENVIRONMENT_NAME.json
  artifacts:
    paths:
      - saferun-*.json

deploy_staging:
  <<: *deploy_config
  stage: deploy
  environment: staging
  script:
    - git push staging main
  only:
    - main

deploy_production:
  <<: *deploy_config
  stage: deploy
  environment: production
  script:
    - saferun config set mode strict
    - git push production main
  only:
    - main
  when: manual  # Requires manual trigger
```

## Jenkins

### Jenkinsfile

```groovy
pipeline {
    agent any
    
    environment {
        CI = 'true'
        JENKINS_URL = "${env.JENKINS_URL}"
        SAFERUN_API_KEY = credentials('saferun-api-key')
    }
    
    stages {
        stage('Setup') {
            steps {
                sh 'npm install -g @saferun/cli'
                sh 'saferun init --auto'
            }
        }
        
        stage('Test') {
            steps {
                sh 'npm test'
            }
        }
        
        stage('Deploy') {
            when {
                branch 'main'
            }
            steps {
                script {
                    // SafeRun will log but not block
                    sh 'saferun status'
                    sh 'git push production main'
                    
                    // Export audit log
                    sh 'saferun history --since 1h --export json > saferun-audit.json'
                    archiveArtifacts artifacts: 'saferun-audit.json'
                }
            }
        }
        
        stage('Audit') {
            steps {
                sh 'saferun history --ai-only'
            }
        }
    }
    
    post {
        always {
            sh 'saferun status'
        }
    }
}
```

## CircleCI

### .circleci/config.yml

```yaml
version: 2.1

executors:
  node-executor:
    docker:
      - image: cimg/node:18.0
    environment:
      CI: true

jobs:
  test:
    executor: node-executor
    steps:
      - checkout
      - run:
          name: Install SafeRun
          command: npm install -g @saferun/cli
      - run:
          name: Initialize SafeRun
          command: saferun init --auto
      - run:
          name: Run tests
          command: npm test
  
  deploy:
    executor: node-executor
    steps:
      - checkout
      - run:
          name: Install SafeRun
          command: npm install -g @saferun/cli
      - run:
          name: Initialize SafeRun
          command: saferun init --auto
      - run:
          name: Deploy
          command: |
            saferun status
            git push production main
      - run:
          name: Save audit log
          command: saferun history --since 1h --export json
      - store_artifacts:
          path: saferun-*.json

workflows:
  version: 2
  test-and-deploy:
    jobs:
      - test
      - deploy:
          requires:
            - test
          filters:
            branches:
              only: main
```

## Docker Integration

### Dockerfile with SafeRun

```dockerfile
FROM node:18-alpine

# Install SafeRun
RUN npm install -g @saferun/cli

# Copy repository
WORKDIR /app
COPY . .

# Initialize SafeRun
RUN saferun init --auto --offline

# Your application
RUN npm install
CMD ["npm", "start"]
```

### Docker Compose for CI

```yaml
version: '3.8'

services:
  ci-runner:
    build: .
    environment:
      - CI=true
      - SAFERUN_API_KEY=${SAFERUN_API_KEY}
    volumes:
      - ./.saferun:/app/.saferun
    command: |
      sh -c "
        saferun init --auto &&
        npm test &&
        git push production main &&
        saferun history --export json
      "
```

## Configuration for CI/CD

### Recommended CI Config

Create `.saferun/ci-config.yml`:

```yaml
mode: balanced

api:
  url: https://api.saferun.dev
  # Use environment variable for API key
  timeout: 10000

github:
  repo: auto

bypass:
  ci: true
  ci_environments:
    enabled: true
    detect_from_env:
      - CI
      - GITHUB_ACTIONS
      - GITLAB_CI
      - JENKINS_URL
      - CIRCLECI
      - TRAVIS
      - BUILDKITE

rules:
  force_push:
    action: warn  # Log but don't block in CI
    risk_score: 7.0
  
  branch_delete:
    action: warn
    risk_score: 6.0

telemetry:
  enabled: true
  # Send to custom endpoint for CI metrics
  endpoint: https://metrics.yourcompany.com/saferun
```

Use in CI:

```bash
saferun init --auto
cp .saferun/ci-config.yml .saferun/config.yml
```

## Monitoring CI Operations

### Collect CI Metrics

```bash
#!/bin/bash
# collect-ci-metrics.sh

echo "SafeRun CI Metrics Report"
echo "========================="

# Get all CI operations from last 24h
saferun history --since 1d --export json > ci-ops.json

# Parse with jq
total=$(jq 'length' ci-ops.json)
ai_ops=$(jq '[.[] | select(.is_ai_generated == true)] | length' ci-ops.json)
blocked=$(jq '[.[] | select(.outcome == "blocked")] | length' ci-ops.json)

echo "Total Operations: $total"
echo "AI-generated: $ai_ops"
echo "Blocked: $blocked"

# Send to monitoring system
curl -X POST https://your-monitoring.com/api/metrics \
  -H "Content-Type: application/json" \
  -d "{
    \"service\": \"saferun-ci\",
    \"total_operations\": $total,
    \"ai_operations\": $ai_ops,
    \"blocked_operations\": $blocked
  }"
```

### Alert on Suspicious Activity

```bash
#!/bin/bash
# check-suspicious.sh

# Check for unusual AI activity in CI
ai_count=$(saferun history --since 1h --ai-only | wc -l)

if [ "$ai_count" -gt 10 ]; then
  echo "⚠️ ALERT: Unusual AI activity detected in CI"
  echo "AI operations in last hour: $ai_count"
  
  # Send to Slack
  curl -X POST "$SLACK_WEBHOOK_URL" \
    -H "Content-Type: application/json" \
    -d "{
      \"text\": \"SafeRun Alert: $ai_count AI operations in CI (last hour)\",
      \"channel\": \"#security\"
    }"
fi
```

## Best Practices

### 1. Always Initialize SafeRun

Even in CI/CD, initialize SafeRun to get audit logs:

```yaml
- run: saferun init --auto
```

### 2. Use Offline Mode for Speed

If your CI doesn't need API calls:

```yaml
- run: saferun init --auto --offline
```

### 3. Archive Audit Logs

Always save SafeRun logs as artifacts:

```yaml
- uses: actions/upload-artifact@v3
  with:
    name: saferun-logs
    path: .saferun/logs/
```

### 4. Separate CI and Dev Configs

Use different configs for CI vs development:

```bash
# Development
saferun init --mode strict

# CI
saferun init --mode balanced --offline
```

### 5. Monitor AI Activity

Track AI operations even in CI:

```bash
saferun history --ai-only --since 1d
```

### 6. Emergency Override

If you need to bypass SafeRun completely in emergency:

```yaml
env:
  SAFERUN_DISABLE: "1"  # Only for emergencies!
```

## Troubleshooting

### CI is being blocked

**Check CI detection:**
```bash
echo $CI
echo $GITHUB_ACTIONS
```

**Force CI bypass:**
```bash
saferun config set bypass.ci true
```

### API timeouts in CI

**Increase timeout:**
```bash
saferun config set api.timeout 15000
```

**Or use offline mode:**
```bash
saferun init --offline
```

### Missing audit logs

**Check log directory:**
```bash
ls -la .saferun/logs/
cat .saferun/logs/operations.log
```

**Enable verbose logging:**
```bash
export SAFERUN_DEBUG=1
```

## Security Considerations

1. **Never commit API keys** - use secrets management
2. **Rotate keys regularly** - especially for CI
3. **Audit CI operations** - review weekly
4. **Limit CI bypass scope** - don't disable all protection
5. **Monitor for abuse** - alert on unusual patterns

## Next Steps

- Set up [monitoring dashboard](../docs/monitoring.md)
- Configure [Slack notifications](../docs/notifications.md)
- Review [security best practices](../docs/security.md)

## Resources

- GitHub Actions: https://docs.github.com/actions
- GitLab CI: https://docs.gitlab.com/ee/ci/
- Jenkins: https://www.jenkins.io/doc/
- SafeRun API: https://docs.saferun.dev/api
