# Gradus Media AI Agent

## Overview
This project is an intelligent content management system designed to automate and streamline social media content creation, translation, image generation, and publishing for Gradus Media. It integrates Claude AI for content and translation, and DALL-E 3 for image generation. The system features a React dashboard for human-in-the-loop content review and approval, a PostgreSQL database, and integrations with Facebook, LinkedIn, and Telegram. Its primary goal is to ensure high-quality content delivery across social platforms with efficient workflow automation and human oversight.

## User Preferences
- Language: Ukrainian for content output
- Tech stack: Python (FastAPI), React, PostgreSQL
- Deployment: Render (Docker-based) - https://gradus-ai.onrender.com
- Focus: Content quality with approval workflow

## Render Deployment
- **Production URL:** https://gradus-ai.onrender.com
- **GitHub Repo:** https://github.com/kostiantynkovalchuk/gradus-ai
- **Deployment Method:** Docker (Dockerfile)
- **Architecture:** Backend serves both API (port 8000) and frontend static files (port 5000)
- **Required Environment Variables:**
  - DATABASE_URL, ANTHROPIC_API_KEY, OPENAI_API_KEY
  - TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
  - FACEBOOK_PAGE_ACCESS_TOKEN, FACEBOOK_PAGE_ID
  - LINKEDIN_ACCESS_TOKEN, LINKEDIN_ORGANIZATION_URN
  - APP_URL

## System Architecture
The system employs a FastAPI backend and a React frontend to manage a sophisticated content pipeline.

**UI/UX Decisions:**
- **Frontend:** React with Vite, styled using Tailwind CSS for a modern, responsive dashboard experience.
- **Dashboard:** Centralized interface for statistics, AI chat interaction, and content approval workflows.

**Technical Implementations:**
- **Backend:** FastAPI for high-performance, asynchronous API operations.
- **Database:** PostgreSQL with SQLAlchemy ORM for robust data persistence.
- **Human-in-the-loop Workflow:** Critical for content quality control, enabling review and approval before publishing.
- **Service-Oriented Architecture:** Modular design supporting extensibility and maintainability.
- **Multi-Source Scraping Architecture:** Modular scraper system with ScraperManager coordinating 7 active sources:
    - **English sources (need translation):**
      - The Spirits Business - Professional industry news
      - Just Drinks - Lighter, more accessible drinks industry content
      - Drinks International - Vodka and spirits industry news
      - Modern Restaurant Management - US HoReCa industry trends
      - Class Magazine - UK bar and cocktail industry (classbarmag.com)
    - **Ukrainian sources (no translation):**
      - Delo.ua - Ukrainian retail and business news (uses Playwright for JavaScript rendering)
      - HoReCa-Україна - Ukrainian HoReCa industry news
- **Automated Content Pipeline:** 24/7 automation via APScheduler with platform-optimized scheduling:
    - **Platform-Specific Scraping:**
      - LinkedIn sources (Mon/Wed/Fri 1:00 AM): The Spirits Business, Drinks International
      - Facebook sources (Daily 2:00 AM): Delo.ua, HoReCa-Україна, Just Drinks
    - **Startup Catch-Up:** On backend restart, automatically checks for missed scraping:
      - Facebook: catch-up if >24h since last scrape
      - LinkedIn: catch-up if >48h since last scrape (runs any day if overdue)
      - Per-platform tracking ensures one platform's recent activity doesn't suppress another
    - **Processing:**
      - AI-driven translation (3x/day at 6am, 2pm, 8pm - only for English sources)
      - Image generation (3x/day at 6:15am, 2:15pm, 8:15pm - for both languages)
    - **Maintenance:**
      - Daily cleanup of rejected content (3:00 AM)
      - API monitoring (8:00 AM)
- **Telegram Quick Approval:** Allows one-click content approval/rejection directly from Telegram notifications, including image previews.
- **Image Generation:** Utilizes Claude AI to craft DALL-E 3 prompts for 1024x1024, text-free, professional social media images.
- **Permanent Image Storage:** DALL-E generated images are stored as binary data (BYTEA) in PostgreSQL database for Render persistence. Priority: Database → Local file → URL.
- **Scheduled Posting:** Approved content is automatically posted at optimal engagement times:
    - **Facebook:** Daily at 18:00.
    - **LinkedIn:** Monday, Wednesday, Friday at 09:00.
- **Duplicate Post Prevention:** Race condition protection for multi-container Render deployments:
    - Database row locking (`SELECT FOR UPDATE SKIP LOCKED`) prevents multiple workers from grabbing the same article
    - Intermediate posting states (`posting_facebook`, `posting_linkedin`) mark articles during posting
    - Idempotency checks verify `fb_post_id`/`linkedin_post_id` doesn't exist before API calls
    - Automatic status reset to 'approved' on posting failure for retry
    - Manual approval endpoint respects intermediate states to avoid conflicts
- **LinkedIn Integration:** Supports organization page posting with robust asset upload, local image fallback, and graceful degradation to text-only posts.
- **API Monitoring:** Daily health checks for all external services with proactive Telegram alerts for issues.

**Feature Specifications:**
- **Content Management:** API for managing pending, approved, and rejected content with editing and history.
- **Article Categorization:** AI-powered classification into News, Reviews, or Trends:
    - Uses keyword matching + Claude AI fallback for accuracy
    - Auto-categorizes articles on Telegram approval
    - API supports filtering: `/api/articles?category=news|reviews|trends`
- **AI Services:** Endpoints for Claude AI chat and English-to-Ukrainian translation.
- **News Scraper:** Extracts clean content and metadata, with year-agnostic URL matching and duplicate detection. Includes Playwright headless browser support for JavaScript-rendered sites.
- **Notifications:** Telegram notifications for content status, approval, and rejection.
- **Database Schema:** `ContentQueue` for reviewable content and `ApprovalLog` for audit trails, storing comprehensive metadata.

## Database Setup

### Schema Initialization
Run the initialization script to ensure all tables and columns exist:

```bash
# Local development
cd backend && python init_db.py

# On Render Shell
python init_db.py

# Verify schema only
python init_db.py --verify-only

# Show current schema
python init_db.py --show-schema
```

### Manual Column Addition (if needed)
```bash
python -c "import os, psycopg2; conn = psycopg2.connect(os.environ['DATABASE_URL']); cur = conn.cursor(); cur.execute('ALTER TABLE table_name ADD COLUMN IF NOT EXISTS column_name TYPE'); conn.commit(); print('Done'); conn.close()"
```

### Documentation
- Schema details: `backend/docs/database_schema.md`
- Deployment guide: `backend/docs/deployment_checklist.md`

## External Dependencies
- **Claude AI (Anthropic):** Content generation, DALL-E prompt creation, English-to-Ukrainian translation.
- **DALL-E 3 (OpenAI):** AI-powered image generation.
- **PostgreSQL:** Primary database for all system data.
- **Telegram Bot API:** Notifications, quick approval via inline keyboard, webhook callbacks.
- **Facebook Graph API:** Authentication, testing, and scheduled posting to Facebook Pages.
- **LinkedIn API v2:** OAuth 2.0 authentication and scheduled posting to LinkedIn organization pages.
- **Trafilatura:** Used for clean content extraction by the news scraper.