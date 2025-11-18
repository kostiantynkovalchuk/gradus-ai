# Gradus Media AI Agent

## Overview

This project implements an intelligent content management system with human-in-the-loop approval for social media content. It automates content creation, translation, image generation, and social media posting for Gradus Media, leveraging Claude AI for content generation and translation, and DALL-E 3 for image creation. The system includes a React dashboard for content review and approval, a PostgreSQL database, and integrates with Facebook and Telegram. The core purpose is to streamline the content workflow from scraping to publishing, ensuring quality control through human approval.

## User Preferences

- Language: Ukrainian for content output
- Tech stack: Python (FastAPI), React, PostgreSQL
- Deployment: Replit native (no Docker)
- Focus: Content quality with approval workflow

## System Architecture

The system is built with a FastAPI backend and a React frontend. Key architectural decisions include:

**UI/UX Decisions:**
- **Frontend Framework:** React with Vite for fast development and a modern user interface.
- **Styling:** Responsive UI with Tailwind CSS.
- **Dashboard:** Provides a central hub for statistics, chat interaction with Claude, and a dedicated content approval page.

**Technical Implementations:**
- **Backend Framework:** FastAPI for high performance, async support, and automatic API documentation.
- **Database:** PostgreSQL managed by SQLAlchemy ORM for robust data handling.
- **Human-in-the-loop Workflow:** Critical for quality control, allowing review and approval of content before publishing.
- **Service-Oriented Architecture:** Modular design for extensibility, testability, and maintainability.
- **Content Pipeline:** Fully automated 24/7 content generation pipeline using APScheduler for background tasks including:
    - News scraping from "The Spirits Business" every 6 hours.
    - Translation of draft articles every hour.
    - Image generation for pending articles every hour.
    - Daily cleanup of old rejected content.
- **Telegram Quick Approval:** Enables one-click approval/rejection and auto-posting directly from Telegram notifications, including image previews.
- **Image Generation Pipeline:** Uses Claude AI to generate contextual DALL-E 3 prompts, ensuring text-free, professional, 1024x1024 images optimized for social media.
- **Facebook Auto-Posting:** Integrates directly into the approval workflow, automatically posting approved content with images to a specified Facebook Page.

**Feature Specifications:**
- **Content Management:** API endpoints for managing pending, approved, and rejected content, including editing and historical tracking.
- **AI Services:** Dedicated endpoints for Claude AI chat and English-to-Ukrainian translation.
- **News Scraper:** Extracts clean content and metadata from "The Spirits Business", supporting year-agnostic URL matching and duplicate detection.
- **Notifications:** Telegram notifications for content approval, rejection, and posting status.
- **Database Schema:** `ContentQueue` table for content review and `ApprovalLog` for audit trails, capturing comprehensive metadata, scheduling information, and review details.

## External Dependencies

- **Claude AI (Anthropic):** Used for content generation, prompt generation for DALL-E, and English-to-Ukrainian translation.
- **DALL-E 3 (OpenAI):** Utilized for AI-powered image generation based on Claude-generated prompts.
- **PostgreSQL:** The primary database for storing content, approval logs, and other system data.
- **Telegram Bot API:** For sending notifications, enabling quick approval via inline keyboard buttons, and receiving webhook callbacks.
- **Facebook Graph API:** For authenticating, testing, and auto-posting content to a designated Facebook Page.
- **Trafilatura:** Used by the news scraper for clean content extraction from web articles.

## Setup & Configuration

### Required Environment Variables

```bash
# AI Services
ANTHROPIC_API_KEY=<your_anthropic_api_key>
OPENAI_API_KEY=<your_openai_api_key>

# Database (automatically configured by Replit)
DATABASE_URL=<auto_configured>

# Telegram Bot
TELEGRAM_BOT_TOKEN=<your_bot_token>
TELEGRAM_CHAT_ID=<your_chat_id>

# Facebook Integration
FACEBOOK_PAGE_ACCESS_TOKEN=<your_page_access_token>
FACEBOOK_PAGE_ID=<your_page_id>

# Optional: Webhook Security (Recommended for Production)
TELEGRAM_WEBHOOK_SECRET=<random_secret_token>
```

### Telegram Quick Approval Setup

The Telegram Quick Approval feature allows one-click approval/rejection of content directly from Telegram notifications with automatic Facebook posting.

#### Step 1: Create Telegram Bot
1. Message [@BotFather](https://t.me/BotFather) on Telegram
2. Send `/newbot` and follow instructions
3. Save your `TELEGRAM_BOT_TOKEN`
4. Find your chat ID using [@userinfobot](https://t.me/userinfobot) and save as `TELEGRAM_CHAT_ID`

#### Step 2: Configure Webhook (Optional but Recommended)
For production security, configure webhook authentication:

```bash
# 1. Generate a random secret token
TELEGRAM_WEBHOOK_SECRET=$(openssl rand -hex 32)

# 2. Add to Replit Secrets

# 3. Set up Telegram webhook with secret
curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook?url=<YOUR_REPLIT_URL>/api/telegram/webhook&secret_token=<YOUR_SECRET>"

# Example:
# curl "https://api.telegram.org/bot123456:ABC-DEF.../setWebhook?url=https://yourapp.repl.co/api/telegram/webhook&secret_token=abc123..."
```

**Without Webhook Secret:**
- System works but webhook is unauthenticated
- Not recommended for production
- Anyone with your webhook URL could send fake requests

**With Webhook Secret:**
- Validates `X-Telegram-Bot-Api-Secret-Token` header
- Returns 403 Forbidden for invalid tokens
- Recommended for production deployments

#### Step 3: Quick Approval Flow

Once configured, the system automatically:

1. **Scrapes content** from The Spirits Business (every 6 hours)
2. **Translates to Ukrainian** using Claude AI (every hour)
3. **Generates images** with DALL-E 3 (every hour)
4. **Sends Telegram notification** with:
   - Image preview (if available)
   - Inline buttons: "✅ Approve & Post" | "❌ Reject"

5. **User clicks "✅ Approve & Post":**
   - Webhook receives callback and validates secret token
   - Posts to Facebook with image
   - Updates database (status = "posted")
   - Updates Telegram message with Facebook post URL

6. **User clicks "❌ Reject":**
   - Marks content as rejected in database
   - Updates Telegram message with rejection notice

#### Error Handling & Recovery

**Transaction Safety:**
- Facebook posting occurs BEFORE database commit
- If DB commit fails after posting, system reports "partial_success"
- Manual recovery: Check Facebook for posted content and update DB manually

**Caption Update Failures:**
- If Telegram caption update fails, user sees notification: "✅ Posted! (Notification update failed)"
- Content is still posted successfully to Facebook
- Check logs for Telegram API errors

**Webhook Failures:**
- Invalid secret token: Returns 403 Forbidden
- Invalid callback data: Returns error response with validation message
- Database errors: Automatic rollback, user notified via callback query

### Facebook Setup

1. Create a Facebook Page or use existing page
2. Get Page Access Token from [Facebook Developer Console](https://developers.facebook.com/)
3. Get Page ID from Page Settings → About
4. Add credentials to Replit Secrets
5. Test connection: `POST /api/test/facebook`

### Testing the System

```bash
# Test Telegram notifications
POST /api/test/telegram

# Test news scraper
POST /api/scraper/test

# Manually run scraper
POST /api/scraper/run?limit=5

# Translate pending articles
POST /api/translate/pending?limit=5

# Generate images for articles
POST /api/images/generate/{article_id}
```