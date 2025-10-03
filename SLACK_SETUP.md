# Slack Integration Setup Guide

This guide shows how to set up Slack notifications for SafeRun approval workflows.

## Overview

SafeRun sends Slack notifications when:
- High-risk actions require approval (dry_run)
- Actions are applied/executed
- Actions are reverted

Slack integration supports **interactive buttons** for approve/reject directly in Slack!

## Prerequisites

- SafeRun API key (get from `/v1/auth/register`)
- Slack workspace admin access

## Step-by-Step Setup

### 1. Create Slack App

1. Go to https://api.slack.com/apps
2. Click **"Create New App"** → **"From scratch"**
3. App Name: `SafeRun Alerts` (or your choice)
4. Pick your workspace
5. Click **"Create App"**

### 2. Configure OAuth & Permissions

1. In the left sidebar, click **"OAuth & Permissions"**
2. Scroll to **"Scopes"** → **"Bot Token Scopes"**
3. Add these scopes:
   - `chat:write` - Send messages as bot
   - `chat:write.public` - Send messages to public channels without joining

### 3. Install App to Workspace

1. Scroll to top of **"OAuth & Permissions"** page
2. Click **"Install to Workspace"**
3. Review permissions and click **"Allow"**
4. Copy the **"Bot User OAuth Token"** (starts with `xoxb-`)
   - **IMPORTANT:** Save this token securely!

### 4. (Optional) Set Up Interactive Components

If you want approve/reject buttons in Slack:

1. In left sidebar, click **"Interactivity & Shortcuts"**
2. Toggle **"Interactivity"** to **ON**
3. Set **Request URL** to:
   ```
   https://your-saferun-api.up.railway.app/slack/interactions
   ```
4. Click **"Save Changes"**

### 5. Configure SafeRun

Now configure SafeRun to use your Slack app:

```bash
curl -X PUT https://saferun.up.railway.app/v1/settings/notifications \
  -H "X-API-Key: YOUR_SAFERUN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "slack_bot_token": "xoxb-YOUR-SLACK-BOT-TOKEN",
    "slack_channel": "#saferun-alerts",
    "slack_enabled": true
  }'
```

**Response:**
```json
{
  "success": true,
  "message": "Notification settings updated successfully",
  "enabled_channels": ["slack"]
}
```

### 6. Test Integration

Send a test notification:

```bash
curl -X POST https://saferun.up.railway.app/v1/settings/notifications/test/slack \
  -H "X-API-Key: YOUR_SAFERUN_API_KEY"
```

**Expected result:** You should see a test message in your Slack channel!

## Verification

Check your current settings:

```bash
curl -X GET https://saferun.up.railway.app/v1/settings/notifications \
  -H "X-API-Key: YOUR_SAFERUN_API_KEY"
```

## Slack Message Features

### With Bot Token (Recommended)
- ✅ Interactive approve/reject buttons
- ✅ Rich formatted messages
- ✅ Direct feedback in Slack

### With Webhook URL (Alternative)
- ✅ Simple integration
- ❌ No interactive buttons (URL buttons only)

## Troubleshooting

### Test notification fails

**Error: "Slack notifications are not enabled"**
- Check that `slack_enabled: true` in your settings
- Verify you have a valid `slack_bot_token` or `slack_webhook_url`

**Error: "channel_not_found"**
- Make sure the channel exists
- Bot must be invited to private channels: `/invite @SafeRun Alerts`

**Error: "not_in_channel"**
- For private channels, invite the bot: `/invite @SafeRun Alerts`

### Messages not appearing

1. Check bot permissions include `chat:write`
2. Verify channel name is correct (must start with `#`)
3. For private channels, invite bot to channel

### Interactive buttons not working

1. Verify Interactive Components are enabled
2. Check Request URL is correct and publicly accessible
3. Ensure `/slack/interactions` endpoint is deployed

## Security Notes

- **Bot tokens are sensitive!** Never commit them to git
- Use environment variables or secure storage
- SafeRun stores tokens encrypted in database
- Webhook signatures are validated automatically

## Next Steps

After setup:
1. Test with a real dry-run operation
2. Configure approval timeout in SafeRun config
3. Set up multiple notification channels (email, webhooks)

## Example Slack Message

When a high-risk action is detected:

```
🛡️ SafeRun Approval Required

Operation: Archive repository owner/repo
Risk Score: 8.5/10
Provider: github
Change ID: chg_xyz123

🌐 View in Dashboard

[✅ Approve]  [❌ Reject]
```

## Support

- API Docs: https://saferun.up.railway.app/docs
- GitHub: https://github.com/Cocabadger/saferun-api/issues
- Email: support@saferun.dev
