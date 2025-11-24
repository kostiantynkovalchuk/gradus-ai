# Gradus Media AI Agent

## Overview
This project is an intelligent content management system designed to automate and streamline social media content creation, translation, image generation, and publishing for Gradus Media. It integrates Claude AI for content and translation, and DALL-E 3 for image generation. The system features a React dashboard for human-in-the-loop content review and approval, a PostgreSQL database, and integrations with Facebook, LinkedIn, and Telegram. Its primary goal is to ensure high-quality content delivery across social platforms with efficient workflow automation and human oversight.

## User Preferences
- Language: Ukrainian for content output
- Tech stack: Python (FastAPI), React, PostgreSQL
- Deployment: Replit native (no Docker)
- Focus: Content quality with approval workflow

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
- **Multi-Source Scraping Architecture:** Modular scraper system with ScraperManager coordinating:
    - The Spirits Business (English, needs translation) - Professional industry news
    - Just Drinks (English, needs translation) - Lighter, more accessible content
    - Delo.ua (Ukrainian, no translation) - Ukrainian business news
    - MinFin.ua (Ukrainian, no translation) - Ukrainian market data
- **Automated Content Pipeline:** 24/7 automation via APScheduler for:
    - Multi-source news scraping (every 6 hours at 00:00, 06:00, 12:00, 18:00).
    - AI-driven translation (hourly, only for English sources).
    - Image generation (hourly, for both languages).
    - Daily cleanup of rejected content.
- **Telegram Quick Approval:** Allows one-click content approval/rejection directly from Telegram notifications, including image previews.
- **Image Generation:** Utilizes Claude AI to craft DALL-E 3 prompts for 1024x1024, text-free, professional social media images.
- **Permanent Image Storage:** DALL-E generated images are downloaded and stored locally in `attached_assets/generated_images/` to prevent link expiration.
- **Scheduled Posting:** Approved content is automatically posted at optimal engagement times:
    - **Facebook:** Daily at 18:00.
    - **LinkedIn:** Monday, Wednesday, Friday at 09:00.
- **LinkedIn Integration:** Supports organization page posting with robust asset upload, local image fallback, and graceful degradation to text-only posts.
- **API Monitoring:** Daily health checks for all external services with proactive Telegram alerts for issues.

**Feature Specifications:**
- **Content Management:** API for managing pending, approved, and rejected content with editing and history.
- **AI Services:** Endpoints for Claude AI chat and English-to-Ukrainian translation.
- **News Scraper:** Extracts clean content and metadata, with year-agnostic URL matching and duplicate detection.
- **Notifications:** Telegram notifications for content status, approval, and rejection.
- **Database Schema:** `ContentQueue` for reviewable content and `ApprovalLog` for audit trails, storing comprehensive metadata.

## External Dependencies
- **Claude AI (Anthropic):** Content generation, DALL-E prompt creation, English-to-Ukrainian translation.
- **DALL-E 3 (OpenAI):** AI-powered image generation.
- **PostgreSQL:** Primary database for all system data.
- **Telegram Bot API:** Notifications, quick approval via inline keyboard, webhook callbacks.
- **Facebook Graph API:** Authentication, testing, and scheduled posting to Facebook Pages.
- **LinkedIn API v2:** OAuth 2.0 authentication and scheduled posting to LinkedIn organization pages.
- **Trafilatura:** Used for clean content extraction by the news scraper.