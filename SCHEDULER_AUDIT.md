# Scheduler Audit — Gradus Media AI Agent

> Prepared: 2026-04-26  
> Purpose: Baseline for adding a monthly Claude model-deprecation check  
> Scope: Read-only — no code changes

---

## Section 1 — Scheduler Infrastructure

### Library

**APScheduler `BackgroundScheduler`** (`apscheduler.schedulers.background`).  
Triggers are `CronTrigger` for time-based jobs and the plain `'interval'` trigger for two high-frequency polling loops.

### Entry point

`backend/services/scheduler.py` — single file, one class (`ContentScheduler`).  
All 21 jobs are registered inside the `start()` method (lines 1191–1407).  
The singleton instance `content_scheduler` is exported at module level and imported by `backend/main.py`.

### Process model

The scheduler runs **in the same process as FastAPI**.  
`main.py` uses the `lifespan` async context manager (`@asynccontextmanager`) to start it on server boot (line 114) and stop it on shutdown (line 225).  
There is no separate worker process.

### Frequency specification

Almost all jobs use `CronTrigger` with named arguments (`hour`, `minute`, `day_of_week`, `day`, `year`).  
Two jobs use `'interval'` with `minutes=5`.  
One job uses `CronTrigger(minute='*/5')` (cron-style every-5-minutes).

### Default job config

```python
BackgroundScheduler(job_defaults={
    'coalesce': True,           # merge multiple missed runs into one
    'max_instances': 1,
    'misfire_grace_time': 3600 * 2   # 2-hour catch-up window
})
```

`coalesce=True` means that if the server was down during a scheduled window, the job fires once on restart (not N times).

### Safety guard

`DISABLE_SCHEDULER=true` env var prevents `start()` from registering any jobs — used in the Replit dev environment.

### DB row-locking pattern

Facebook and LinkedIn posting tasks use **`SELECT FOR UPDATE SKIP LOCKED`** (via SQLAlchemy) to prevent duplicate posts when multiple Render containers run simultaneously. The pattern is documented in the job docstrings (lines 793–794, 968–969). The API monitor, knowledge-gap, and candidate-aggregation jobs do **not** use row locking — they are idempotent or single-writer by nature.

### Full job inventory

| Job ID | Frequency | What it does | Task method |
|--------|-----------|--------------|-------------|
| `scrape_linkedin` | Mon/Wed/Fri 01:00 UTC | Scrape The Spirits Business + Drinks International | `scrape_linkedin_sources_task` |
| `scrape_facebook` | Daily 02:00 UTC | Scrape Delo.ua, HoReCa-Україна, Just Drinks, MRM | `scrape_facebook_sources_task` |
| `translate_articles` | Daily 06:00, 14:00, 20:00 UTC | Translate pending articles (Claude → Ukrainian) | `translate_pending_task` |
| `generate_images` | Daily 06:15, 14:15, 20:15 UTC | Generate Unsplash images + send Telegram approval notifications | `generate_images_task` |
| `post_linkedin` | Mon/Wed/Fri 09:00 UTC | Post approved content to LinkedIn org page | `post_to_linkedin_task` |
| `post_facebook` | Daily 18:00 UTC | Post approved content to Facebook page | `post_to_facebook_task` |
| `cleanup_old_content` | Daily 03:00 UTC | Delete old rejected articles | `cleanup_old_content_task` |
| `check_expired_subscriptions` | Daily 04:00 UTC | Expire/downgrade lapsed subscriptions | `check_expired_subscriptions_task` |
| `check_api_services` | Daily 08:00 UTC | Health-check Anthropic, OpenAI, Telegram bot | `check_api_services_task` |
| `detect_knowledge_gaps` | Daily 07:00 UTC | Analyse HR bot unanswered queries | `detect_knowledge_gaps_task` |
| `aggregate_alex_candidates` | Daily 03:30 UTC | Aggregate Alex Gradus preset answer candidates | `aggregate_alex_candidates_task` |
| `process_channel_queue` | Interval, every 5 min | Post queued articles to Telegram channel | `_process_channel_queue_task` |
| `cleanup_alex_memory` | Sunday 04:30 UTC | Prune Alex conversation memory (keep 50/user) | `_cleanup_alex_memory_task` |
| `send_pulse_survey` | day=13–17, 07:00 UTC, Mon–Fri | Monthly Team Pulse mood survey | `_send_pulse_survey_task` |
| `pulse_risk_decay` | Monday 02:00 UTC | Weekly Pulse risk score decay | `_pulse_risk_decay_task` |
| `weekly_photo_accuracy_digest` | Monday 09:00 UTC | Alex Photo Report weekly accuracy digest | `_weekly_photo_accuracy_digest` |
| `linkedin_weekly_digest` | Thursday 08:00 UTC | LinkedIn weekly HoReCa news digest | `_linkedin_digest_task` |
| `alex_video_digest` | Monday 08:00 UTC | Alex Gradus weekly avatar video digest (needs HEYGEN keys) | `_video_digest_task` |
| `survey_easter_send` | 2026-04-07 07:00 UTC (one-shot) | Easter 2026 survey broadcast | `_survey_easter_broadcast_task` |
| `survey_easter_scoreboard` | 2026-04-07 07:05 UTC (one-shot) | Easter 2026 survey initial scoreboard | `_survey_easter_scoreboard_task` |
| `onboarding_email_checker` | cron `*/5` (every 5 min) | Onboarding email sequence for Alex Gradus website users | `_onboarding_email_task` |

---

## Section 2 — api_token_monitor.py Deep Read

**File:** `backend/services/api_token_monitor.py`  
**Class:** `APITokenMonitor` (singleton instance: `api_token_monitor`)

### Services monitored

| Service | Method | Detection mechanism |
|---------|--------|---------------------|
| Anthropic (Claude) | `check_anthropic_api()` | Real minimal API call — `messages.create(model=HAIKU, max_tokens=10)` — using typed SDK exceptions; timeout 10 s |
| OpenAI | `check_openai_api()` | `client.models.list()` — checks key validity and DALL-E availability |
| Telegram bot | `check_telegram_bot()` | `getMe` endpoint — validates `TELEGRAM_BOT_TOKEN` |
| ~~Facebook~~ | removed | Uses non-expiring Business Portfolio token; check was redundant |

### Frequency

Called once by `check_api_services_task` in the scheduler, which runs **daily at 08:00 UTC**.

### On failure / warning detection

`check_all_services()` iterates all three checks, collects `warnings` and `errors` into a results dict, then calls `self._send_alert_notification(results)` if either list is non-empty.

Anthropic exception mapping:

| Exception | `status` | `error_type` |
|-----------|----------|-------------|
| `AuthenticationError` | `error` | `AUTH_FAILURE` |
| `RateLimitError` | `warning` | `RATE_LIMITED` |
| `InternalServerError` (529) | `warning` | `OVERLOADED` |
| `APITimeoutError` | `warning` | `TIMEOUT` |
| `APIConnectionError` | `warning` | `CONNECTION_ERROR` |
| `APIStatusError` (400 + "credit balance") | `error` | `BILLING_ERROR` |

### Notification call signature

```python
def _send_alert_notification(self, results: Dict) -> None
```

Private method; returns `None`. Only fires when `warnings` or `errors` are present. Builds an HTML-formatted string and sends it directly via `requests.post` to the Telegram Bot API (not through `notification_service`).

There is also a public:

```python
def send_success_notification(self, results: Dict) -> None
```

but it is **never called by the scheduler** — only by tests or manual invocation.

### Retry / error handling / fallback

- Single attempt per daily run — no retry loop inside the monitor.
- Network exceptions in `_send_alert_notification` are caught and logged (`logger.error`), not re-raised.
- No fallback channel (e.g., email or Slack).

### DB persistence

**None.** Results are logged to Render stdout/stderr only. There is no table or row written on each check run.

### Deduplication

**None.** If a condition (e.g., `RATE_LIMITED`) persists across multiple daily runs, the same alert is re-sent every day at 08:00 UTC.

---

## Section 3 — Telegram Admin Notification Pipeline

### Two separate notification paths exist in the codebase

---

#### Path A — `APITokenMonitor._send_alert_notification()` (inline)

| Property | Value |
|----------|-------|
| File | `backend/services/api_token_monitor.py:422` |
| Bot token env var | `TELEGRAM_BOT_TOKEN` |
| Chat ID env var | `TELEGRAM_CHAT_ID` |
| Parse mode | `HTML` |
| Transport | Synchronous `requests.post` (timeout 10 s) |
| Return type | `None` |
| Deduplication | None |
| Failure handling | Logs error, does not raise |

This path is **self-contained** — it calls the Telegram API directly without going through any shared service.

---

#### Path B — `NotificationService.send_custom_notification(message: str)` (shared)

| Property | Value |
|----------|-------|
| File | `backend/services/notification_service.py:215` |
| Bot token env var | `TELEGRAM_BOT_TOKEN` |
| Chat ID env var | `TELEGRAM_CHAT_ID` |
| Parse mode | `HTML` |
| Transport | Synchronous `requests.post` (timeout 10 s) |
| Return type | `bool` (True = sent, False = failed) |
| Deduplication | None |
| Failure handling | Logs error, returns False, does not raise |

This is the shared service used by Facebook/LinkedIn posting tasks for success notifications. It accepts raw HTML text — the caller is responsible for composing the message string.

Signature:

```python
def send_custom_notification(self, message: str) -> bool
```

---

#### Path C — `send_telegram_message(chat_id, text)` (HR / Maya bot)

File: `backend/routes/telegram_webhook.py:1058`  
Bot token: `TELEGRAM_MAYA_BOT_TOKEN`  
Used exclusively for HR bot and Maya responses — **not the admin notification channel**.  
This path is `async` and uses `httpx`.

---

### Summary: admin alerts use Path A or Path B

Both paths use the same env vars (`TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`) and the same HTML parse mode. Path A is private to the monitor; Path B is the shared admin-notification surface.

---

## Section 4 — Recommended Integration for Model Deprecation Check

### File location

`backend/services/model_deprecation_check.py`

This mirrors the pattern of `api_token_monitor.py` — a standalone service module with a module-level function callable from the scheduler.

### Scheduler registration

Add one `add_job` call in `ContentScheduler.start()`, after the `check_api_services` block:

```python
# Model deprecation check — 1st of month at 09:05 UTC
self.scheduler.add_job(
    self._check_model_deprecation_task,
    CronTrigger(day=1, hour=9, minute=5),
    id='model_deprecation_check',
    name='Monthly Claude model deprecation check',
    replace_existing=True
)
```

Offset by 5 minutes from `check_api_services` (08:00) to avoid simultaneous Telegram bursts.

Add the task wrapper method to `ContentScheduler`:

```python
def _check_model_deprecation_task(self):
    try:
        from services.model_deprecation_check import check_model_deprecations
        check_model_deprecations()
    except Exception as e:
        logger.error(f"[SCHEDULER] Model deprecation check failed: {e}", exc_info=True)
```

### Notification function to call

Use **Path B — `notification_service.send_custom_notification(message)`**.

Reasons:
- It is the shared admin-notification surface already used by multiple tasks.
- Returns a `bool` so the caller can log failures.
- Synchronous — no event loop wiring needed (scheduler runs in a background thread, not async context).
- Same bot and chat ID as `api_token_monitor`, so alerts land in the same admin feed.

### DB persistence recommendation

**Do not mirror** the zero-persistence pattern of `api_token_monitor`. Because this check fires only once a month, add a simple persistence layer — a module-level in-memory dict is sufficient per-process but resets on restart. Better: write one row to a new lightweight table or use a key-value entry in an existing table to record `last_check_at` and `last_flagged_models`. This prevents a Render restart on the 1st from re-alerting if the check already ran.

Minimal option: store `{'model_deprecation_last_check': '2026-05-01', 'flagged': '[]'}` in a JSON column on a config/settings table if one exists, or simply check the Render logs and accept the rare double-fire on the 1st of month restart.

### Frequency

**Monthly (1st of month) is the right call.** Anthropic's practice has been to announce deprecation 30–90 days before retirement. Monthly polling gives 1–3 warning cycles before the deadline. Weekly would be noise; quarterly would miss a full announcement cycle.

---

## Section 5 — Risks and Gotchas

### Render zero-downtime deploys

Render starts the new instance before terminating the old one. During the overlap window (typically 30–60 s), both instances run `BackgroundScheduler`. For a job that fires once a month, the risk is that both fire near-simultaneously on deploy day if the deploy coincides with the 1st of month at 09:05 UTC.

Mitigation: The deprecation check is read-only (HTTP GET to an external URL + Telegram push). A double-fire would send two identical Telegram messages. This is tolerable. No DB write race condition exists because the check is stateless. If the `last_check_at` persistence described in Section 4 is implemented, the second instance's check would see `last_check_at = today` and skip.

The Facebook/LinkedIn posting tasks are more sensitive and already use `SELECT FOR UPDATE SKIP LOCKED`. The deprecation check does not need this because it writes nothing to content tables.

### No existing external HTTP-fetch jobs to model after

The scheduler currently has **no job that fetches an external documentation URL**. All external HTTP calls in the scheduler go to partner APIs (Telegram, Facebook, LinkedIn, NBU) with known schemas, not scraped HTML pages. The deprecation check would be the first.

Model after: `check_anthropic_api()` in `api_token_monitor.py` for structure (try/except, typed errors, logger calls, return early on missing config). Use `httpx` (already in the stack) rather than `requests` for the HTTP GET so the pattern is consistent with other recent services (`solomon_search.py`, `routes/telegram_webhook.py`).

### Telegram rate-limit risk

Telegram's Bot API allows 30 messages/second per bot and 1 message/second to the same chat. The deprecation check sends at most one message per month. No rate-limit risk even if the scheduler retries on failure. The one risk scenario: if `check_api_services` (08:00) fires an error alert and `model_deprecation_check` (09:05) fires a deprecation alert the same day, two messages land in the admin channel within an hour — acceptable.

There is no deduplication anywhere in the existing notification pipeline, so do not build it for the deprecation check either. Instead, keep messages informative so the admin understands context without needing history.

### Where to log HTTP fetch failures

- `logger.error("[DeprecationCheck] Failed to fetch deprecation page: {e}")` — goes to Render logs.
- Do **not** send a Telegram alert on fetch failure. A transient network blip on the 1st of month should not create admin noise. If the page is unreachable, log, increment a counter, and consider alerting only after two consecutive monthly failures (requires DB persistence).
- If `httpx` is used, catch `httpx.TimeoutException`, `httpx.ConnectError`, and the broad `httpx.HTTPError` separately for clean log messages.
