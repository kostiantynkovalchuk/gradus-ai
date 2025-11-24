# Ukrainian Content Support Guide

## Overview

The Gradus Media AI Agent now supports **bilingual content processing**:
- **English sources**: Automatically translated to Ukrainian
- **Ukrainian sources**: Skip translation, processed directly

## How It Works

### Database Schema

New fields in `ContentQueue` table:
- `language` (VARCHAR(10), default='en'): Source language code ('en', 'uk', etc.)
- `needs_translation` (BOOLEAN, default=TRUE): Whether article needs translation
- `posted_at` (TIMESTAMP): When content was posted to social media

### Content Workflows

#### English Content (Automatic)
1. ✅ Scraper creates article with defaults (`language='en'`, `needs_translation=True`)
2. ✅ Translation task translates to Ukrainian
3. ✅ Image generation creates social media image
4. ✅ Telegram notification sent for approval
5. ✅ Scheduled posting to Facebook/LinkedIn

#### Ukrainian Content (Manual)
1. ✅ API creates article with (`language='uk'`, `needs_translation=False`)
2. ⏭️  Translation task **SKIPS** (no translation needed)
3. ✅ Image generation creates social media image
4. ✅ Ukrainian text → marked as "translated" (for consistency)
5. ✅ Status changes to 'pending_approval'
6. ✅ Telegram notification sent for approval
7. ✅ Scheduled posting to Facebook/LinkedIn

## Adding Ukrainian Content

### Method 1: API Endpoint (Recommended)

Use the `/api/content/create` endpoint:

```bash
curl -X POST http://localhost:8000/api/content/create \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Український заголовок статті",
    "content": "Повний текст української статті...",
    "source": "Ukrainian News Source",
    "source_url": "https://example.com/article",
    "language": "uk",
    "needs_translation": false,
    "platforms": ["facebook", "linkedin"]
  }'
```

**Response:**
```json
{
  "status": "success",
  "message": "Ukrainian content created successfully",
  "content_id": 123,
  "language": "uk",
  "needs_translation": false,
  "next_steps": "Content will be processed for images and sent for approval"
}
```

### Method 2: Add Ukrainian News Scraper (Future)

To automatically scrape Ukrainian sources:

1. **Create new scraper** in `backend/services/ukrainian_scraper.py`
2. **Set language flags** when creating ContentQueue:
   ```python
   new_article = ContentQueue(
       status='draft',
       source='Ukrainian Source Name',
       source_url=article_url,
       original_text=article_content,
       language='uk',              # ← IMPORTANT
       needs_translation=False,     # ← IMPORTANT
       platforms=['facebook', 'linkedin'],
       extra_metadata={'title': article_title}
   )
   ```
3. **Add to scheduler** for automated scraping

## API Reference

### POST /api/content/create

Create Ukrainian content manually.

**Request Body:**
```typescript
{
  title: string;              // Ukrainian title
  content: string;            // Ukrainian content
  source?: string;            // Source name (default: "Manual")
  source_url?: string;        // Source URL (optional)
  language?: string;          // Language code (default: "uk")
  needs_translation?: boolean; // Translation needed? (default: false)
  platforms?: string[];       // Platforms (default: ["facebook", "linkedin"])
}
```

**Example:**
```javascript
const response = await fetch('http://localhost:8000/api/content/create', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    title: "Нові тренди в алкогольній індустрії",
    content: "Детальний опис трендів українською мовою...",
    source: "Ukrainian Industry News",
    language: "uk",
    needs_translation: false
  })
});
```

## Scheduler Behavior

### Translation Task (Every hour at :15)
**Filter:** `status='draft' AND needs_translation=True AND translated_text IS NULL`

- ✅ English articles: **Processed**
- ⏭️ Ukrainian articles: **Skipped** (needs_translation=False)

### Image Generation Task (Every hour at :30)
**Filter:** 
```sql
WHERE (status='pending_approval')  -- Translated English articles
   OR (status='draft' AND needs_translation=False)  -- Ukrainian articles
AND image_url IS NULL
```

- ✅ English articles: **Processed** after translation
- ✅ Ukrainian articles: **Processed** directly, then:
  - `status` → 'pending_approval'
  - `translated_title` ← `extra_metadata.title`
  - `translated_text` ← `original_text`

## Testing

### Test Ukrainian Content Flow

1. **Create Ukrainian article:**
   ```bash
   curl -X POST http://localhost:8000/api/content/create \
     -H "Content-Type: application/json" \
     -d '{
       "title": "Тестова стаття",
       "content": "Це тестовий контент українською мовою",
       "language": "uk",
       "needs_translation": false
     }'
   ```

2. **Wait for image generation** (runs every hour at :30)
   - Or manually trigger: `POST /api/images/generate/{article_id}`

3. **Check Telegram** for approval notification
   - Should show Ukrainian text without translation

4. **Approve** via Telegram button
   - Content marked for scheduled posting

5. **Verify posting** at scheduled times:
   - Facebook: Daily at 18:00
   - LinkedIn: Mon/Wed/Fri at 09:00

## Migration

The database migration ran successfully:
```
✅ Migration completed successfully!
   - Added 'language' column (default: 'en')
   - Added 'needs_translation' column (default: TRUE)
   - Added 'posted_at' column
```

**All existing articles** have:
- `language='en'`
- `needs_translation=True`
- Will continue to be translated as before

## Troubleshooting

### Ukrainian content being translated
**Problem:** Ukrainian article went through translation
**Solution:** Verify API request set `needs_translation=false`

### Ukrainian content stuck in 'draft'
**Problem:** Image generation not picking it up
**Solution:** Check that `language='uk'` and `needs_translation=False`

### No Telegram notification
**Problem:** Notification not sent after image generation
**Solution:** Check logs for image generation errors

## Future Enhancements

1. **Automated Ukrainian scraper**
   - Add Ukrainian news source
   - Auto-detect language and set flags

2. **Language detection**
   - Auto-detect article language
   - Set `needs_translation` automatically

3. **Multi-language support**
   - Support more languages (Russian, Polish, etc.)
   - Language-specific posting schedules

## Example Use Cases

### Use Case 1: Manual Ukrainian News
```bash
# Add Ukrainian article from external source
POST /api/content/create
{
  "title": "Українська горілка отримала міжнародну нагороду",
  "content": "Українська горілка \"Хлібний Дар\" отримала золоту медаль...",
  "source": "Ukrainian Industry Awards",
  "source_url": "https://example.com/award",
  "language": "uk",
  "needs_translation": false
}
```

### Use Case 2: Mixed Language Workflow
```bash
# English article (automatic translation)
Scraper creates → Translation → Image → Approval → Post

# Ukrainian article (skip translation)
API creates → Image → Approval → Post
```

## Database Queries

### Check Ukrainian articles
```sql
SELECT id, status, language, needs_translation, 
       extra_metadata->>'title' as title
FROM content_queue
WHERE language = 'uk';
```

### Check translation queue
```sql
SELECT id, language, needs_translation, status
FROM content_queue
WHERE needs_translation = TRUE AND status = 'draft';
```

### Check ready for approval
```sql
SELECT id, language, status, image_url IS NOT NULL as has_image
FROM content_queue
WHERE status = 'pending_approval';
```

## Summary

✅ **Implemented:**
- Database schema for language support
- Translation task filters Ukrainian content
- Image generation handles Ukrainian articles
- API endpoint for manual Ukrainian content
- Ukrainian articles flow to approval without translation

⏳ **Future Work:**
- Automated Ukrainian news scraper
- Language auto-detection
- More language support

📝 **Documentation:**
- API endpoint usage
- Workflow diagrams
- Testing procedures
- Troubleshooting guide
