# Gradus Media AI Agent - Database Schema

## Overview

The Gradus Media AI Agent uses PostgreSQL for persistent storage of content, approval workflows, and system state.

## Tables

### content_queue

Main table for tracking content through the pipeline: scraping → translation → image generation → approval → posting.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | SERIAL | NO | Primary key |
| `status` | VARCHAR(20) | NO | Current status: draft, pending_approval, approved, rejected, posted, posting_facebook, posting_linkedin |
| `source` | VARCHAR(255) | YES | Source name (e.g., "The Spirits Business", "Delo.ua") |
| `source_url` | VARCHAR(500) | YES | Original article URL |
| `source_title` | TEXT | YES | Original title from source |
| `original_text` | TEXT | YES | Original article content |
| `translated_title` | TEXT | YES | Ukrainian translated title |
| `translated_text` | TEXT | YES | Ukrainian translated content |
| `image_url` | TEXT | YES | DALL-E generated image URL (temporary, expires in ~1 hour) |
| `image_prompt` | TEXT | YES | Prompt used for DALL-E image generation |
| `local_image_path` | TEXT | YES | Local filesystem path to saved image |
| `image_data` | BYTEA | YES | **Persistent image storage** - binary image data for Render deployment |
| `scheduled_post_time` | TIMESTAMP | YES | When to post (if scheduled) |
| `platforms` | VARCHAR(50)[] | YES | Target platforms: ['facebook'], ['linkedin'], or both |
| `created_at` | TIMESTAMP | YES | When the article was scraped (default: now()) |
| `reviewed_at` | TIMESTAMP | YES | When content was reviewed |
| `reviewed_by` | VARCHAR(100) | YES | Who reviewed the content |
| `rejection_reason` | TEXT | YES | Reason for rejection (if rejected) |
| `edit_history` | JSON | YES | History of edits made to content |
| `extra_metadata` | JSON | YES | Additional metadata (author, content_hash, etc.) |
| `analytics` | JSON | YES | Post-publication analytics |
| `posted_at` | TIMESTAMP | YES | When content was posted |
| `language` | VARCHAR(10) | YES | Original language code: 'en' or 'uk' (default: 'en') |
| `needs_translation` | BOOLEAN | YES | Whether translation is required (default: TRUE) |

**Status Flow:**
```
draft → pending_approval → approved → posting_facebook → posted
                                    → posting_linkedin → posted
                        ↘ rejected
```

**Intermediate statuses** (`posting_facebook`, `posting_linkedin`) are used during the posting process to prevent race conditions in multi-container deployments.

### approval_log

Audit trail for all content approval/rejection actions.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | SERIAL | NO | Primary key |
| `content_id` | INTEGER | YES | Reference to content_queue.id |
| `action` | VARCHAR(50) | YES | Action taken: 'approved', 'rejected', 'edited' |
| `moderator` | VARCHAR(100) | YES | Who performed the action |
| `timestamp` | TIMESTAMP | YES | When the action was taken (default: now()) |
| `details` | JSON | YES | Additional action details |

## Key Fields Explained

### image_data (BYTEA)

This column stores the actual image binary data directly in PostgreSQL. This is critical for Render deployment because:

1. **DALL-E URLs expire** - Generated image URLs only last ~1 hour
2. **Render filesystem is ephemeral** - Local files don't persist across deploys
3. **Database persists** - PostgreSQL data survives container restarts

The posting workflow prioritizes image sources:
1. `image_data` (database) - Most reliable
2. `local_image_path` - For local development
3. `image_url` - Fallback (usually expired)

### extra_metadata (JSON)

Common fields stored in extra_metadata:
- `title` - Original article title
- `author` - Article author
- `published_date` - Original publication date
- `content_hash` - MD5 hash for duplicate detection
- `scraped_at` - When the article was scraped
- `notification_sent` - Whether Telegram notification was sent
- `notification_sent_at` - When notification was sent
- `fb_post_id` - Facebook post ID after posting
- `fb_post_url` - Facebook post URL
- `fb_post_retries` - Number of failed posting attempts
- `linkedin_post_id` - LinkedIn post ID
- `linkedin_post_url` - LinkedIn post URL

### platforms (VARCHAR[])

Array field indicating target social platforms:
- `['facebook']` - Post to Facebook only
- `['linkedin']` - Post to LinkedIn only
- `['facebook', 'linkedin']` - Post to both

## Running Schema Updates

### Using init_db.py (Recommended)

```bash
# Local development
cd backend
python init_db.py

# On Render Shell
python init_db.py

# Verify schema only (no changes)
python init_db.py --verify-only

# Show current schema
python init_db.py --show-schema
```

### Manual Column Addition

If you need to add a column manually on Render Shell:

```bash
python -c "import os, psycopg2; conn = psycopg2.connect(os.environ['DATABASE_URL']); cur = conn.cursor(); cur.execute('ALTER TABLE content_queue ADD COLUMN IF NOT EXISTS column_name TYPE'); conn.commit(); print('Done'); conn.close()"
```

Example - adding image_data column:
```bash
python -c "import os, psycopg2; conn = psycopg2.connect(os.environ['DATABASE_URL']); cur = conn.cursor(); cur.execute('ALTER TABLE content_queue ADD COLUMN IF NOT EXISTS image_data BYTEA'); conn.commit(); print('Done'); conn.close()"
```

## Migration History

| Date | Change | Description |
|------|--------|-------------|
| 2024-11 | Initial | Created content_queue and approval_log tables |
| 2024-11 | Language support | Added `language` and `needs_translation` columns |
| 2024-12-02 | Image persistence | Added `image_data` BYTEA column for Render deployment |

## Performance Considerations

1. **image_data size** - Each image is ~200-500KB. Monitor database size.
2. **JSON fields** - Using JSON type for flexibility (consider JSONB for indexing if needed)
3. **Connection pooling** - Configured in SQLAlchemy with pool_size=10, max_overflow=20
