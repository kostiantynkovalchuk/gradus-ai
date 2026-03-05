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
- **Maya Hunt Recruitment Module:** Telegram supergroup-based candidate sourcing with interactive UX, vacancy parsing, candidate scoring, and auto-posting.

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