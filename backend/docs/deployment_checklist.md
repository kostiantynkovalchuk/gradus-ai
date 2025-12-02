# Gradus Media AI Agent - Deployment Checklist

## Overview

This checklist covers deploying the Gradus AI Agent to Render.com with a Neon PostgreSQL database.

## Prerequisites

- GitHub repository with latest code
- Render.com account
- Neon PostgreSQL database (or Render PostgreSQL)
- API keys for external services

## Environment Variables

### Required Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://user:pass@host/db` |
| `ANTHROPIC_API_KEY` | Claude AI API key | `sk-ant-...` |
| `OPENAI_API_KEY` | OpenAI/DALL-E API key | `sk-...` |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token | `123456:ABC...` |
| `TELEGRAM_CHAT_ID` | Telegram chat/group ID | `-1001234567890` |

### Optional Variables (for posting)

| Variable | Description |
|----------|-------------|
| `FACEBOOK_PAGE_ACCESS_TOKEN` | Facebook Page access token |
| `FACEBOOK_PAGE_ID` | Facebook Page ID |
| `LINKEDIN_ACCESS_TOKEN` | LinkedIn OAuth access token |
| `LINKEDIN_ORGANIZATION_URN` | LinkedIn organization URN |
| `APP_URL` | Public URL of the app |

## Deployment Steps

### 1. Push Code to GitHub

```bash
git add .
git commit -m "Your commit message"
git push origin main
```

### 2. Create Render Web Service

1. Go to [Render Dashboard](https://dashboard.render.com)
2. Click "New +" → "Web Service"
3. Connect your GitHub repository
4. Configure:
   - **Name**: gradus-ai
   - **Environment**: Docker
   - **Branch**: main
   - **Plan**: Free or Starter

### 3. Set Environment Variables

In Render dashboard → Your Service → Environment:

1. Add all required environment variables
2. Ensure `DATABASE_URL` points to your production database

### 4. Initialize Database Schema

After first deployment, open Render Shell and run:

```bash
# Option 1: Use init_db.py (recommended)
cd /app
python init_db.py

# Option 2: Manual verification
python init_db.py --verify-only
python init_db.py --show-schema
```

### 5. Verify Schema

Check that all required columns exist:

```bash
python init_db.py --show-schema
```

Expected tables:
- `content_queue` (with `image_data` BYTEA column)
- `approval_log`

### 6. Add Missing Columns (if needed)

If `init_db.py` doesn't work, add columns manually:

```bash
python -c "import os, psycopg2; conn = psycopg2.connect(os.environ['DATABASE_URL']); cur = conn.cursor(); cur.execute('ALTER TABLE content_queue ADD COLUMN IF NOT EXISTS image_data BYTEA'); conn.commit(); print('Done'); conn.close()"
```

### 7. Verify Deployment

1. Check Render logs for startup messages
2. Look for: "GRADUS MEDIA AI AGENT - FULLY OPERATIONAL"
3. Visit your app URL to confirm frontend loads
4. Check scheduler jobs are registered

## Troubleshooting

### "Column does not exist" Error

```
psycopg2.errors.UndefinedColumn: column "xxx" does not exist
```

**Solution**: Run `python init_db.py` in Render Shell to add missing columns.

### Database Connection Failed

```
could not connect to server
```

**Solutions**:
1. Verify `DATABASE_URL` is set correctly
2. Check if database is accessible from Render
3. For Neon: Ensure connection pooling is configured

### Scheduler Not Running

Check logs for:
```
INFO:apscheduler.scheduler:Scheduler started
```

If missing, the app may have crashed during startup.

### Images Not Posting

If posts fail with image errors:
1. Check if `image_data` column exists
2. Verify new images are being stored in database
3. Old images without `image_data` will fallback to expired URLs

## Health Checks

### API Health
```
curl https://your-app.onrender.com/api/health
```

### Database Connectivity
```bash
# In Render Shell
python -c "import os, psycopg2; conn = psycopg2.connect(os.environ['DATABASE_URL']); print('Connected'); conn.close()"
```

### Schema Verification
```bash
python init_db.py --verify-only
```

## Rollback Procedure

If deployment breaks the app:

1. Go to Render Dashboard → Your Service → Deploys
2. Find the last working deployment
3. Click "Redeploy" on that version

For database issues:
1. Render supports automatic database backups
2. Neon supports point-in-time recovery

## Monitoring

### Key Metrics to Watch

1. **Scheduler jobs executing** - Check logs for job completion
2. **Database size** - Monitor if using image_data storage
3. **API response times** - Frontend should load quickly
4. **Error rates** - Check for recurring errors in logs

### Log Patterns to Monitor

Good signs:
```
✅ GRADUS MEDIA AI AGENT - FULLY OPERATIONAL
✅ Scheduler started
✅ [SCHEDULER] Posted to Facebook
✅ [SCHEDULER] Posted to LinkedIn
```

Warning signs:
```
❌ [SCHEDULER] ... failed
ERROR: column "..." does not exist
Facebook access token is invalid
LinkedIn access token invalid
```

## Regular Maintenance

1. **Weekly**: Check posting success rate
2. **Monthly**: Verify API tokens are valid
3. **Quarterly**: Review database size, clean old rejected content
4. **As needed**: Refresh LinkedIn/Facebook tokens before expiry
