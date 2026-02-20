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
- **Telegram Quick Approval:** Enables one-click content approval/rejection directly from Telegram with image previews. Includes inline "New Image" button for fetching alternative images from Unsplash without leaving Telegram, with tier advancement on each click.
- **Image Integration (Unsplash) with Tier Rotation:** Articles use authentic photography from Unsplash API with a 4-tier intelligent search system and round-robin rotation for visual diversity. Tier 0: Geographical, Tier 1: Context-based, Tier 2: HoReCa/Cocktail, Tier 3: Abstract. Starting tier rotates based on `article_id % 4` to ensure ~25% distribution across tiers. "New Image" button advances to next tier. Tracks `last_tier_used` and `tier_attempts` in database. Includes proper attribution ("Photo by {name} on Unsplash") per API Terms Section 9, persistent duplicate prevention via `unsplash_image_id`, and manual "Fetch Image" button in Article Manager.
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
- **HR Bot RAG System:** Employee onboarding and support knowledge base using PostgreSQL for content (43 entries including training manuals), Pinecone for vector search (namespace: hr_docs), and OpenAI embeddings. Features include preset answers, semantic and hybrid search, Telegram integration with interactive menus, smart back navigation, and feedback mechanisms. **Unified query routing:** ALL authenticated employee messages route through hr_rag_service pipeline (no bypass to chat_endpoints). **Cost-optimized query flow:** Preset ($0) → Keyword with stop-word filtering ($0) → RAG semantic search (~$0.0001), saving ~90% on API costs. **Enhanced preset matching:** Meta-instruction detection (rejects system/search commands), Ukrainian morphology normalization (word root mapping), multi-signal fuzzy scoring (rapidfuzz: direct, normalized, token_set, partial ratios), threshold 0.75. **Confidence-based responses:** High (>0.45) normal answer, Medium (0.35-0.45) answer + disclaimer, Low (<0.35) honest "not found". Domain mismatch detection prevents cross-topic hallucinations (e.g., стул/furniture vs стіл/desktop). **Learning system:** Feedback buttons on every RAG answer, negative feedback creates preset candidates, nightly gap detection (7:00 AM) sends admin reports via Telegram. **Telegram document upload:** HR admins can upload .txt/.pdf/.docx/.md files directly via Telegram for auto-ingestion into the knowledge base (text extraction + embedding + Pinecone). **Video-only responses:** Queries about company values, history, or overview automatically send video content (no text) with fallback to RAG if video unavailable.
- **HR Admin Dashboard:** Analytics dashboard at `/hr` (HTTP Basic Auth: admin / Maya_2026) for monitoring HR bot performance, including query stats, satisfaction analysis, preset candidates, and recent activity.
- **News Scraper:** Extracts clean content and metadata, with year-agnostic URL matching, duplicate detection, and Playwright support for JavaScript-rendered sites.
- **Notifications:** Telegram notifications for content status, approval, and rejection.
- **Торговий Дім АВ Video Feature:** Sends vertical 9:16 video presentations in multiple languages when users query "Торговий Дім АВ", with file_id caching for efficiency.
- **Query Expansion for RAG:** Automatically expands brand name queries with relevant category keywords for improved retrieval in RAG systems (e.g., "greenday" → "greenday vodka горілка").
- **Smart Document Linking:** Automatically attaches relevant Google Doc links to Maya's answers. Uses `DocumentService` with regex-based document number extraction (№XX, шаблон XX, додаток XX) and PostgreSQL array overlap for topic matching. Returns up to 3 documents per answer, formatted as clickable links. Works universally across preset, keyword, and RAG answer paths. Table: `hr_documents` with topics/keywords arrays and GIN index. Initial seed: 7 documents (templates №69, №33, №63, №114, №83; appendices №42.1, №42.2).
- **Legal Contracts Library:** Interactive menu in HR Bot providing access to 44 legal contract templates across 3 company entities: Бест Брендс (19 contracts), Торговий Дім АВ (19 contracts), and Світ Бейкерс (6 contracts). Organized by category (Marketing, Logistics, Distribution, Supply/Procurement, Additional Agreements). Documents served via `/static/legal_contracts/` endpoint and delivered directly to users via Telegram sendDocument API.
- **Multi-Tier Authentication System:** Phone-based verification for HR Bot access with 4 access levels (employee, contractor, admin_hr, developer). Flow: /start → phone input → whitelist check → SED API verification → access granted or HR admin notification. Whitelist bypass for developers/contractors. Admin commands: /admin (panel), /adduser (whitelist), /logs (verification journal), /stats (detailed stats), /listusers (developer only). Failed registrations auto-notify HR admins via Telegram. 7-day SED data sync. Tables: `hr_users`, `hr_whitelist`, `verification_log`.
- **Backend Monetization System:** Email-based user management with subscription tiers (free: 5 questions/day, standard: $7/mo, premium: $10/mo). DB-backed rate limiting via `maya_users` table. WayForPay payment integration (UAH via live NBU exchange rate) for checkout and webhooks with HMAC_MD5 signature verification. Daily subscription expiry checker at 4:00 AM. Tables: `maya_users`, `maya_subscriptions`, `maya_query_log`.
- **Database Schema:** `ContentQueue`, `ApprovalLog`, `MediaFile`, `HRUser`, `HRWhitelist`, `VerificationLog`, `MayaUser`, `MayaSubscription`, `MayaQueryLog` tables manage content, auth, monetization, and Telegram file_id caching respectively.

## External Dependencies
- **Claude AI (Anthropic):** Content generation, English-to-Ukrainian translation.
- **Unsplash API:** Authentic stock photography for article images with proper attribution.
- **PostgreSQL:** Primary database.
- **Telegram Bot API:** Notifications, quick approval, webhook callbacks.
- **Facebook Graph API:** Authentication and scheduled posting to Facebook Pages.
- **LinkedIn API v2:** OAuth 2.0 authentication and scheduled posting to LinkedIn organization pages.
- **WayForPay:** Ukrainian payment gateway with UAH pricing, HMAC-MD5 signature verification, and pay-widget.js checkout.
- **NBU API:** National Bank of Ukraine exchange rates for real-time USD→UAH conversion.
- **Trafilatura:** Clean content extraction for the news scraper.