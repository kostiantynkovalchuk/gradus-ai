# Gradus Media AI Agent

## Overview
This project is an intelligent content management system for Gradus Media, automating social media content creation, translation, image sourcing, and publishing. It integrates Claude AI for content and translation, and Unsplash for authentic photography. Key features include a React dashboard for human-in-the-loop content review, a PostgreSQL database, and integrations with Facebook, LinkedIn, and Telegram. The system aims to ensure high-quality content delivery across social platforms through efficient workflow automation and human oversight, focusing on business vision, market potential, and project ambitions to deliver high-quality, automated content.

## User Preferences
- Language: Ukrainian for content output
- Tech stack: Python (FastAPI), React, PostgreSQL
- Deployment: Render (Docker-based) - https://gradus-ai.onrender.com
- Focus: Content quality with approval workflow

## System Architecture
The system utilizes a FastAPI backend and a React frontend to manage a comprehensive content pipeline.

**UI/UX Decisions:**
- **Frontend:** React with Vite and Tailwind CSS for a modern, responsive dashboard.
- **Dashboard:** Centralized interface for statistics, AI chat, and content approval.

**Technical Implementations:**
- **Backend:** FastAPI for high-performance, asynchronous API operations.
- **Database:** PostgreSQL with SQLAlchemy ORM.
- **Human-in-the-loop Workflow:** Essential for content quality control, enabling review and approval before publishing.
- **Service-Oriented Architecture:** Modular design for extensibility and maintainability.
- **Multi-Source Scraping Architecture:** Modular scraper system with `ScraperManager` coordinating 7 active sources (5 English, 2 Ukrainian). English sources require translation, Ukrainian do not. Playwright is used for JavaScript-rendered sites.
- **Automated Content Pipeline:** 24/7 automation via APScheduler, with platform-optimized scheduling for scraping (LinkedIn: Mon/Wed/Fri; Facebook: Daily), AI translation (3x/day for English sources), and image generation (3x/day for both languages). Includes startup catch-up for missed scrapes and daily cleanup of rejected content.
- **Telegram Quick Approval:** Enables one-click content approval/rejection directly from Telegram with image previews. Includes inline "New Image" button for image regeneration without leaving Telegram.
- **Image Integration (Unsplash):** Articles use authentic photography from Unsplash API with smart keyword extraction (geography, spirits types, business terms, premium indicators). Includes proper attribution ("Photo by {name} on Unsplash") per API Terms Section 9, persistent duplicate prevention via database tracking of `unsplash_image_id`, and manual "Fetch Image" button in Article Manager.
- **Scheduled Posting:** Approved content is automatically posted at optimal engagement times (Facebook: Daily 18:00; LinkedIn: Mon/Wed/Fri 09:00).
- **Duplicate Post Prevention:** Implements database row locking, intermediate posting states, and idempotency checks to prevent duplicate posts in multi-container environments.
- **LinkedIn Integration:** Supports organization page posting with robust asset upload and graceful degradation.
- **API Monitoring:** Daily health checks for external services with Telegram alerts.

**Feature Specifications:**
- **Content Management:** API for managing pending, approved, and rejected content with editing and history.
- **Article Manager (Admin Dashboard):** Full-featured interface at `/articles` for paginated listing, search, filters, bulk deletion, CSV export, and real-time statistics. Clickable status cards with URL sync for deep linking (e.g., `/articles?status=approved`).
- **Article Categorization:** AI-powered classification (News, Reviews, Trends) using keyword matching and Claude AI fallback.
- **AI Services:** Endpoints for Claude AI chat and English-to-Ukrainian translation.
- **AI Avatar System (Maya & Alex Gradus):**
    - **Maya:** Marketing & trends expert, handles grammatical gender rules.
    - **Alex Gradus:** Premium Bar Operations Consultant, focuses on P&L optimization, product selection, and operations, with a business-first, anti-hallucination approach.
- **Preset Answer Service (Cost Optimization):** Provides instant answers for common questions via exact/fuzzy matching and keyword detection, significantly reducing API calls and costs.
- **Direct Content Mapping (Button Optimization):** Button clicks use in-memory content lookup via `maya_hr_content.py` instead of API/database calls, reducing response time from 2-3s to <50ms and saving ~$16/month in API costs. Free text queries still use preset→RAG flow.
- **HR Bot RAG System:** Employee onboarding and support knowledge base using PostgreSQL for content, Pinecone for vector search (namespace: hr_docs), and OpenAI embeddings. Features include preset answers, semantic and hybrid search, Telegram integration with interactive menus, smart back navigation, HR keyword detection, and feedback mechanisms. **Video-only responses:** Queries about company values, history, or overview automatically send video content (no text) with fallback to RAG if video unavailable.
- **HR Admin Dashboard:** Analytics dashboard at `/hr` (HTTP Basic Auth: admin / Maya_2026) for monitoring HR bot performance, including query stats, satisfaction analysis, preset candidates, and recent activity.
- **News Scraper:** Extracts clean content and metadata, with year-agnostic URL matching, duplicate detection, and Playwright support for JavaScript-rendered sites.
- **Notifications:** Telegram notifications for content status, approval, and rejection.
- **Торговий Дім АВ Video Feature:** Sends vertical 9:16 video presentations in multiple languages when users query "Торговий Дім АВ", with file_id caching for efficiency.
- **Query Expansion for RAG:** Automatically expands brand name queries with relevant category keywords for improved retrieval in RAG systems (e.g., "greenday" → "greenday vodka горілка").
- **Legal Contracts Library:** Interactive menu in HR Bot providing access to 44 legal contract templates across 3 company entities: Бест Брендс (19 contracts), Торговий Дім АВ (19 contracts), and Світ Бейкерс (6 contracts). Organized by category (Marketing, Logistics, Distribution, Supply/Procurement, Additional Agreements). Documents served via `/static/legal_contracts/` endpoint and delivered directly to users via Telegram sendDocument API.
- **Database Schema:** `ContentQueue`, `ApprovalLog`, and `MediaFile` tables manage content, audit trails, and Telegram file_id caching respectively.

## External Dependencies
- **Claude AI (Anthropic):** Content generation, English-to-Ukrainian translation.
- **Unsplash API:** Authentic stock photography for article images with proper attribution.
- **PostgreSQL:** Primary database.
- **Telegram Bot API:** Notifications, quick approval, webhook callbacks.
- **Facebook Graph API:** Authentication and scheduled posting to Facebook Pages.
- **LinkedIn API v2:** OAuth 2.0 authentication and scheduled posting to LinkedIn organization pages.
- **Trafilatura:** Clean content extraction for the news scraper.