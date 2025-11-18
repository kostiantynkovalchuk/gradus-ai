# Gradus Media AI Agent

A multi-stage AI agent system for automated content creation, approval workflow, and social media management for Gradus Media.

## Overview

This project implements an intelligent content management system with human-in-the-loop approval for social media content. It uses Claude AI for translation and content generation, with a React dashboard for content review and approval.

## Project Structure

```
├── backend/                    # FastAPI backend
│   ├── main.py                # Main API application
│   ├── models/                # Database models
│   │   ├── __init__.py       # Database connection
│   │   └── content.py        # ContentQueue, ApprovalLog models
│   └── services/             # Business logic services
│       ├── claude_service.py      # Claude AI integration
│       ├── news_scraper.py        # News scraping service
│       ├── image_generator.py     # DALL-E integration
│       ├── social_poster.py       # Social media posting
│       └── notification_service.py # Notifications
│
├── frontend/                  # React dashboard
│   ├── src/
│   │   ├── pages/
│   │   │   ├── HomePage.jsx          # Dashboard home
│   │   │   ├── ChatPage.jsx          # Claude chat & translation
│   │   │   └── ContentApproval.jsx   # Content review UI
│   │   ├── App.jsx           # Main app component
│   │   └── main.jsx          # Entry point
│   └── vite.config.js        # Vite configuration
│
└── .env                       # Environment variables
```

## Features Implemented (Phase 1)

✅ **Backend (FastAPI)**
- Claude AI integration for chat and translation
- RESTful API endpoints for content management
- PostgreSQL database with ContentQueue and ApprovalLog models
- Human-in-the-loop approval workflow
- Service architecture for extensibility
- **News scraper for The Spirits Business** (manual trigger)
- Telegram notifications for content approval

✅ **Frontend (React + Vite)**
- Dashboard with statistics
- Chat interface for testing Claude
- English to Ukrainian translation tool
- Content approval page (ready for content)
- Responsive UI with Tailwind CSS

✅ **API Endpoints**

**Content Management:**
- `GET /api/content/pending` - Get pending content
- `POST /api/content/{id}/approve` - Approve content
- `POST /api/content/{id}/reject` - Reject content
- `PUT /api/content/{id}/edit` - Edit content
- `GET /api/content/history` - Get content history
- `GET /api/content/stats` - Get statistics

**AI Services:**
- `POST /chat` - Chat with Claude AI
- `POST /translate` - Translate English to Ukrainian

**News Scraper:**
- `POST /api/scraper/test` - Test scraper with 1 article
- `POST /api/scraper/run?limit=5` - Manually scrape articles (default: 5)

**Notifications:**
- `POST /api/test/telegram` - Test Telegram notification

**Image Generation:**
- `POST /api/images/generate/{article_id}` - Generate image for specific article
- `POST /api/images/regenerate/{article_id}` - Regenerate image with new prompt
- `POST /api/images/generate-pending` - Batch generate for articles without images

## Environment Variables

**Required:**
- `ANTHROPIC_API_KEY` - Claude AI API key
- `DATABASE_URL` - PostgreSQL connection (auto-configured by Replit)
- `TELEGRAM_BOT_TOKEN` - Telegram bot token for notifications
- `TELEGRAM_CHAT_ID` - Telegram chat ID for notifications

**Required (for image generation):**
- `OPENAI_API_KEY` - For DALL-E 3 image generation

**Optional (for future features):**
- `PINECONE_API_KEY` - For RAG functionality
- `FACEBOOK_PAGE_ACCESS_TOKEN` - Facebook posting
- `LINKEDIN_ACCESS_TOKEN` - LinkedIn posting

## Running the Application

**Backend**: Runs automatically on port 8000 (configured workflow)
```bash
cd backend && python start.py
```

**Frontend**: Runs automatically on port 5000 (configured workflow)
- Access the dashboard at the Replit webview

**API Documentation**: http://localhost:8000/docs (when backend is running)

## Database Schema

### ContentQueue Table
Stores content for review and approval
- **Core fields:** id, status, source, source_url, source_title
- **Content fields:** original_text, translated_title, translated_text, image_url, image_prompt
- **Metadata:** extra_metadata (JSON), edit_history (JSON), analytics (JSON)
- **Scheduling:** scheduled_post_time, platforms (array)
- **Review tracking:** created_at, reviewed_at, reviewed_by, rejection_reason
- **Status flow:** draft → pending_approval → approved → posted

### ApprovalLog Table
Audit trail for all approval actions
- **Fields:** id, content_id, action, moderator, timestamp, details (JSON)

## News Scraper

The news scraper fetches latest articles from The Spirits Business website:

**Features:**
- **Clean content extraction** using Trafilatura (removes metadata prefixes like dates/authors)
- Scrapes article metadata (title, URL, excerpt, date, author)
- Year-agnostic URL matching (works across calendar years)
- Duplicate detection (prevents re-adding existing articles)
- Saves articles as "draft" status in ContentQueue
- Full article text extraction (2000-3000+ characters of clean content)

**Translation Service:**
- **Separate title and content translations** for better quality
- Title translation: 200 token limit for concise headlines
- Content translation: 4000 token limit for full article text
- Uses Claude Sonnet 4 model
- Automatic Telegram notifications when content is ready for approval
- Saves both `translated_title` and `translated_text` to database

**Usage:**
```bash
# Test with 1 article
curl -X POST http://localhost:8000/api/scraper/test

# Scrape 5 articles (default)
curl -X POST http://localhost:8000/api/scraper/run

# Scrape 10 articles
curl -X POST http://localhost:8000/api/scraper/run?limit=10
```

## Image Generation (DALL-E 3)

AI-powered image generation for social media posts using Claude + DALL-E 3 pipeline:

**Features:**
- **Claude-powered prompt generation** - Uses Claude Sonnet 4 to create contextual DALL-E prompts
- **Text-free images** - Explicit instructions to avoid text/labels in generated images
- **Professional aesthetic** - Premium alcohol industry styling with minimalist design
- **1024x1024 images** - Square format optimized for social media (Facebook/LinkedIn)
- **Regeneration support** - Create new images with different prompts if needed
- **Batch generation** - Generate images for multiple articles at once

**Image Generation Flow:**
1. Article content (title + text) → Claude API
2. Claude creates professional DALL-E prompt (2-3 sentences) with "no text" instructions
3. DALL-E 3 generates image (standard quality, $0.04 per image)
4. Image URL + prompt saved to database
5. Frontend displays image with regeneration option

**Database Schema Note:**
- `image_url` column changed from `VARCHAR(255)` to `TEXT` to handle long DALL-E URLs (400-500 characters)
- Applied via: `ALTER TABLE content_queue ALTER COLUMN image_url TYPE TEXT;`
- **Production deployment:** Run same ALTER TABLE on production database before deploying

**Usage:**
```bash
# Generate image for specific article
curl -X POST http://localhost:8000/api/images/generate/4

# Regenerate with new prompt
curl -X POST http://localhost:8000/api/images/regenerate/4

# Batch generate for all pending articles without images
curl -X POST http://localhost:8000/api/images/generate-pending
```

## Next Steps (Phase 2)

✅ **Stage 1: News Scraping (Manual)** - COMPLETED
- ✅ News scraper for The Spirits Business
- ✅ Telegram notifications
- ✅ DALL-E image generation (text-free images)
- 🔲 Scheduled/automated scraping
- 🔲 Social media posting

🔲 **Stage 2: Outreach Agent**
- Social media monitoring
- Lead qualification
- Personalized outreach

🔲 **Stages 3 & 4: Telegram Bots**
- Training bot with RAG
- HR recruitment bot

## Architecture Decisions

1. **FastAPI** - High performance, async support, automatic API docs
2. **React + Vite** - Fast development, modern frontend
3. **SQLAlchemy** - Robust ORM for PostgreSQL
4. **Human-in-the-loop** - Quality control before publishing
5. **Service-oriented** - Modular, testable, extensible

## User Preferences

- Language: Ukrainian for content output
- Tech stack: Python (FastAPI), React, PostgreSQL
- Deployment: Replit native (no Docker)
- Focus: Content quality with approval workflow
