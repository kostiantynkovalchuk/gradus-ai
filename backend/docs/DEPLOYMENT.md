# Best Brands Video Feature - Render Deployment

## Overview
This feature sends a vertical 9:16 video presentation when Maya bot users ask about Best Brands company on Telegram.

## Pre-Deployment Checklist
- [x] Identity questions ("who are you") removed from triggers
- [x] Telegram-only implementation confirmed
- [x] All tests pass (23 trigger tests + caching + fallback)
- [x] Video file excluded from Git (22MB too large)

---

## Step 1: Deploy Code

```bash
git pull origin main
python init_db.py  # Creates media_files table if not exists
```

---

## Step 2: Upload Video to Render

Since the video file (22MB) is too large for Git, deploy it separately:

### Option A: Render Shell Upload
1. Go to Render dashboard → Your Service → Shell
2. Navigate to assets directory:
   ```bash
   cd /opt/render/project/src/backend/assets/
   ```
3. Upload `bestbrands-presentation.mp4` via Render's file upload interface

### Option B: Download from External URL
```bash
cd /opt/render/project/src/backend/assets/
curl -L -o bestbrands-presentation.mp4 "YOUR_TEMPORARY_DOWNLOAD_LINK"
```

### Option C: Use Render Disk (Persistent Storage)
For permanent storage, attach a Render Disk and configure the path in environment variables.

---

## Step 3: Verify Installation

```bash
# Check video exists
ls -lh backend/assets/bestbrands-presentation.mp4

# Expected output:
# -rw------- 1 user user 22M Jan  6 01:20 bestbrands-presentation.mp4

# Run tests
python backend/scripts/test_bestbrands_video.py
```

---

## Step 4: Initialize Database

```bash
python init_db.py
```

This creates the `media_files` table for Telegram file_id caching.

---

## Step 5: Restart Service

Restart the FastAPI backend through Render dashboard or:
```bash
# Trigger redeploy
git commit --allow-empty -m "Trigger redeploy" && git push
```

---

## Verification

1. **Test in Telegram:**
   - Message Maya: "розкажи про best brands"
   - Expected: Video plays inline

2. **Check logs:**
   ```bash
   # Look for these log entries
   grep "Best Brands" /var/log/render/*.log
   ```

3. **File_id Caching:**
   - First request: Video uploads (may take ~30s)
   - Second request: Instant delivery via cached file_id

---

## Troubleshooting

### Video Not Playing
1. Check video file exists: `ls -la backend/assets/`
2. Verify file size: Should be ~22MB
3. Check Telegram bot token: `echo $TELEGRAM_MAYA_BOT_TOKEN`

### Text Fallback Shown Instead
1. Video file missing or corrupted
2. Telegram API rate limited
3. File_id expired (rare) - delete from `media_files` table and retry

### Trigger Not Working
Run: `python backend/scripts/test_bestbrands_video.py`

---

## Environment Variables

| Variable | Description |
|----------|-------------|
| `TELEGRAM_MAYA_BOT_TOKEN` | Maya bot token for Telegram API |
| `DATABASE_URL` | PostgreSQL connection for file_id caching |

---

## Database Schema

```sql
CREATE TABLE media_files (
    id SERIAL PRIMARY KEY,
    media_type VARCHAR(50) NOT NULL,
    media_key VARCHAR(100) NOT NULL UNIQUE,
    file_id VARCHAR(255) NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## Files Modified

| File | Purpose |
|------|---------|
| `backend/services/bestbrands_video.py` | Trigger detection + video sending |
| `backend/routes/telegram_webhook.py` | Integration with Maya bot |
| `backend/models/content.py` | MediaFile model |
| `backend/scripts/test_bestbrands_video.py` | Test suite |
| `backend/assets/bestbrands-presentation.mp4` | Video file (not in Git) |
