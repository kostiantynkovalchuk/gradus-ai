# Gradus Media AI Agent

## Overview
This project is an intelligent content management system for Gradus Media, automating social media content creation, translation, image sourcing, and publishing. It integrates Claude AI for content and translation, and Unsplash for authentic photography. The system aims to ensure high-quality content delivery across social platforms through efficient workflow automation and human oversight, focusing on business vision, market potential, and project ambitions to deliver high-quality, automated content.

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
- **GradusMedia Admin Dashboard:** Full admin panel at `/admin` with analytics, preset candidates, user database, and subscriptions.
- **HR Admin Dashboard:** Analytics dashboard at `/hr` for monitoring HR bot performance.

**Technical Implementations:**
- **Backend:** FastAPI for high-performance, asynchronous API operations.
- **Database:** PostgreSQL with SQLAlchemy ORM.
- **Human-in-the-loop Workflow:** Essential for content quality control, enabling review and approval before publishing.
- **Service-Oriented Architecture:** Modular design for extensibility and maintainability.
- **Multi-Source Scraping Architecture:** Modular scraper system coordinating 7 active sources (5 English, 2 Ukrainian) with deduplication.
- **Automated Content Pipeline:** 24/7 automation via APScheduler for scraping, AI translation, and image generation.
- **Telegram Quick Approval:** Enables one-click content approval/rejection directly from Telegram with image previews and "New Image" fetching.
- **Image Integration (Unsplash) with Tier Rotation:** Uses a 4-tier intelligent search system and round-robin rotation for visual diversity, including proper attribution and duplicate prevention.
- **Scheduled Posting:** Approved content is automatically posted at optimal engagement times for Facebook and LinkedIn.
- **Duplicate Post Prevention:** Implements database row locking and idempotency checks.
- **LinkedIn Integration:** Supports organization page posting with asset upload.
- **API Monitoring:** Daily health checks for external services with Telegram alerts.
- **Content Management:** API for managing content with editing and history.
- **Article Manager:** Full-featured interface for content listing, search, filters, bulk deletion, CSV export, and real-time statistics.
- **Article Categorization:** AI-powered classification using keyword matching and Claude AI fallback.
- **AI Services:** Endpoints for Claude AI chat and English-to-Ukrainian translation.
- **AI Avatar System:** Features Maya (marketing/trends expert) and Alex Gradus (premium bar operations consultant).
- **Preset Answer Service (Cost Optimization):** Database-backed preset answers with 3-tier matching and Claude API fallback.
- **Alex Learning System:** Automated query pattern detection and admin workflow for generating and promoting AI answers.
- **Direct Content Mapping:** In-memory content lookup for button clicks to reduce response time and API costs.
- **HR Bot RAG System:** Employee onboarding and support knowledge base using PostgreSQL, Pinecone, and OpenAI embeddings, with cost-optimized query flow, enhanced preset matching, confidence-based responses, domain mismatch detection, and a learning system.
- **Telegram Document Upload:** HR admins can upload documents directly via Telegram for auto-ingestion into the knowledge base.
- **Video-only responses:** Specific queries trigger video content delivery.
- **News Scraper:** Extracts clean content and metadata with Playwright support.
- **Notifications:** Telegram notifications for content status.
- **Торговий Дім АВ Video Feature:** Sends vertical video presentations for specific queries.
- **Query Expansion for RAG:** Automatically expands brand name queries for improved retrieval.
- **Smart Document Linking:** Automatically attaches relevant Google Doc links to Maya's answers.
- **Legal Contracts Library:** Interactive menu in HR Bot providing access to 44 legal contract templates.
- **Multi-Tier Authentication System:** Phone-based verification for HR Bot access with 4 access levels.
- **Blitz Phone Cache:** Local DB cache of employee phones from Blitz xlsx export for future features.
- **Backend Monetization System:** Email-based user management with subscription tiers, DB-backed rate limiting, and WayForPay integration.
- **Maya Hunt Recruitment Module:** Telegram supergroup-based candidate sourcing with interactive UX (2x2 action menu), vacancy parsing, candidate scoring, auto-posting to channels, hire tracking (🎯 Найняти button with filled status), and full 8-section ROI analytics dashboard.
- **Salary Normalization Engine:** Dual-currency (UAH/USD) parser for Ukrainian job market salary formats with automatic conversion, confidence scoring, currency toggle in dashboard, and live NBU exchange rate (daily cached).
- **Robota.ua REST API Integration:** Replaced broken GraphQL approach with official employer REST API (employer-api.robota.ua). Auto-login via `robotaua_auth.py` (POST /Login with email+password, 23h cache, JWT env fallback). City/rubric reference cache in `robotaua_reference.py` (indexes name, nameUkr, nameEng, urlSegment). CV search scraper in `hunt_robotaua_scraper.py` uses POST /cvdb/resumes + GET /resume/{id}. Applications scraper in `hunt_robotaua_applies.py` uses POST /vacancy/list + /apply/list (round 1 only, requires employer auth). Both sources integrated into `hunt_service.py` as 4th gather target.
- **Robota.ua Salary Intelligence:** JWT-authenticated GraphQL salary analytics from Robota.ua transparent salary API, with background pipeline integration, position-level caching (1hr), and market intelligence dashboard cards.
- **NBU Live Exchange Rate:** Daily-cached USD/UAH rate from National Bank of Ukraine API, replacing all hardcoded rates across the codebase.
- **Hunt Analytics Dashboard:** ROI banner, 6 KPI cards, hire funnel chart, source performance chart, salary intelligence with currency toggle, skills chart, salary trends, recent vacancies table, data sources panel, efficiency comparison table.
- **Solomon Court Search Bot:** Telegram bot (@solomon_court_ua_bot) for searching Ukrainian Supreme Court cassation decisions via court-search-agent proxy, with Claude AI query parsing and one-sentence summaries. Phone-based whitelist auth, search history, inline feedback (like/dislike) per result card, feedback analytics (`/law/analytics/data`), FastAPI `/law` endpoints. Migrations 017, 019 (solomon_feedback).
- **Alex Photo Report Bot:** Merchandising verification bot for AVTD trade agents. Claude Sonnet vision analyzes shelf photos (up to 5) against AVTD merchandising standards (shelf share, brand placement, POS materials, elite shelf). Conversation flow: point name → photos → AI analysis → formatted report. Webhook at `/webhook/photo-report`, `PHOTO_REPORT_BOT_TOKEN` env var. Module: `backend/photo_report/`. Migration 018 (tables: `photo_agents`, `photo_reports`, `photo_report_images`).
- **Easter 2026 Survey System:** Employee holiday survey via Telegram with live scoreboard. Migration 030 (tables: `hr_surveys`, `hr_survey_votes`, `hr_survey_meta`). Seed row for `easter_holiday_2026`. Survey card on HR dashboard Pulse tab with 30s auto-refresh. Scheduler jobs at 07:00/07:05 UTC on April 7. Observer-targeted scoreboard, 3s debounce on edits.
- **GA4 Analytics:** Google Analytics 4 tracking via gtag.js in frontend (`G-XXXXXXXXXX` placeholder). Analytics utility at `frontend/src/lib/analytics.js` with named helpers: `trackChatStarted`, `trackQuickQuestionClicked`, `trackEmailSubmitted`, `trackTrialStarted`, `trackPlanViewed`, `trackContentApproved/Rejected`. `chat_started` event fires on every chat submission.
- **LinkedIn Daily News Digest:** AI-powered daily LinkedIn posts via `backend/services/linkedin_digest_service.py`. Fetches top 5 posted articles → Claude Haiku generates 2-3 sentence insights → posts native text (no link) → first comment with source URLs. Saves to `linkedin_posts` table (migration 031). Scheduler: daily 07:00 UTC.
- **Alex Avatar Video Digest (Scaffold):** Weekly AI video pipeline scaffold in `backend/services/video_digest_service.py`. Steps: fetch news → Claude Sonnet script (Alex persona, 60-90s, Ukrainian) → HeyGen avatar video → distribute to Facebook + Telegram + LinkedIn. Status tracking in `video_digests` table (migration 031). Scheduler: Monday 08:00 UTC. Activates when `HEYGEN_API_KEY` + `HEYGEN_AVATAR_ID` env vars are set.
- **Solomon Contracts MVP:** Second tab ("Договори поставки") on the existing /law page for AVTD's law department. AI-powered supply contract risk analysis using Claude Sonnet free-form scan, Pinecone RAG-grounded alternative wording generation, DOCX artifact output (risk note, protocol, legal opinion). Module at `backend/solomon_contracts/`. API at `/api/contracts/*`. Migration 041 creates 11 tables with `solcon_` prefix. Auth: cookie `solcon_auth=<base64(solomon:gradus2026)>`. Two Pinecone namespaces: `solomon-contracts-corpus` (legal corpus) and `solomon-contracts-findings`. Tab state via `?tab=contracts` query param. Features: engagement CRUD, bundle upload (ZIP/DOCX/PDF/XLSX), Claude Haiku classification, clause-ref guardrail (§10.1), legal grounding guardrail (§10.2), eval harness at `?tab=contracts&view=admin/eval`. Phase 1 complete; Phase 2 UI built. Corpus seeding via `/api/contracts/admin/corpus/seed-sources` + rebuild endpoint. Eval: precision target ≥0.75, recall ≥0.70, grounding rate ≥0.60.

## External Dependencies
- **Claude AI (Anthropic):** Content generation, English-to-Ukrainian translation.
- **Unsplash API:** Authentic stock photography.
- **PostgreSQL:** Primary database.
- **Telegram Bot API:** Notifications, quick approval, webhook callbacks.
- **Facebook Graph API:** Authentication and scheduled posting to Facebook Pages.
- **LinkedIn API v2:** OAuth 2.0 authentication and scheduled posting to LinkedIn organization pages.
- **WayForPay:** Ukrainian payment gateway for monetization.
- **NBU API:** National Bank of Ukraine exchange rates.
- **Telethon:** Telegram client library for scraping candidate channels.
- **Trafilatura:** Clean content extraction for the news scraper.
- **Work.ua:** CV search scraper with authenticated session, CSRF handling, and salary normalization for candidate sourcing.