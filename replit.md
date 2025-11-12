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

✅ **Frontend (React + Vite)**
- Dashboard with statistics
- Chat interface for testing Claude
- English to Ukrainian translation tool
- Content approval page (ready for content)
- Responsive UI with Tailwind CSS

✅ **API Endpoints**
- `POST /chat` - Chat with Claude AI
- `POST /translate` - Translate English to Ukrainian
- `GET /api/content/pending` - Get pending content
- `POST /api/content/{id}/approve` - Approve content
- `POST /api/content/{id}/reject` - Reject content
- `PUT /api/content/{id}/edit` - Edit content
- `GET /api/content/stats` - Get statistics

## Environment Variables

Required:
- `ANTHROPIC_API_KEY` - Claude AI API key
- `DATABASE_URL` - PostgreSQL connection (auto-configured by Replit)

Optional (for future features):
- `OPENAI_API_KEY` - For DALL-E image generation
- `PINECONE_API_KEY` - For RAG functionality
- `TELEGRAM_BOT_TOKEN_TRAINING` - Training bot
- `TELEGRAM_BOT_TOKEN_HR` - HR bot
- `FACEBOOK_PAGE_ACCESS_TOKEN` - Facebook posting
- `LINKEDIN_ACCESS_TOKEN` - LinkedIn posting

## Running the Application

**Frontend**: Runs automatically on port 5000 (configured workflow)
- Access the dashboard at the Replit webview

**Backend**: Start manually when needed
```bash
cd backend && python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

## Database Schema

### ContentQueue Table
- Stores content for review and approval
- Fields: id, status, source, original_text, translated_text, image_url, platforms, timestamps
- Status flow: draft → pending_approval → approved → posted

### ApprovalLog Table
- Audit trail for all approval actions
- Fields: id, content_id, action, moderator, timestamp, details

## Next Steps (Phase 2)

🔲 Stage 1: News Automation
- Implement automated news scraping
- DALL-E image generation
- Scheduled social media posting
- Notification system

🔲 Stage 2: Outreach Agent
- Social media monitoring
- Lead qualification
- Personalized outreach

🔲 Stages 3 & 4: Telegram Bots
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
