# Tenderlot Bot

Telegram notification bot for [tenderlot.net](https://tenderlot.net) — AVTD's procurement platform. Replaces/augments email notifications with instant Telegram alerts when a new tender opens.

---

## What this is

When a tender is published on tenderlot.net with `start_mail_status=1`, this bot finds all registered Telegram users whose role matches the tender's target audience (supplier / carrier / both) and sends them a notification with a direct "Відкрити тендер" button. Users link their Telegram account to their tenderlot.net profile once by sharing their phone number; after that, everything is automatic.

This repository is a **development skeleton** using SQLite mocks. Production deployment targets Render.com with a real MariaDB (tenderlot) + Neon PostgreSQL (bot state) setup.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                      main.py                            │
│  init_db → seed_mock → build_app → start_worker         │
└──────────────┬──────────────────────────┬───────────────┘
               │                          │
    ┌──────────▼──────────┐   ┌───────────▼────────────┐
    │   PTB Application   │   │    PollingWorker        │
    │  (run_polling loop) │   │  (asyncio.create_task) │
    │                     │   │  every 30s             │
    │  /start  → consent  │   │                        │
    │  contact → link     │   │  TenderlotRepo (R/O)   │
    │  /help              │   │  BotStateRepo  (R/W)   │
    │  /status            │   │  Notifier              │
    │  /unlink            │   └────────────────────────┘
    └─────────────────────┘
               │                          │
    ┌──────────▼──────────┐   ┌───────────▼────────────┐
    │  tenderlot_mock.db  │   │   tenderlot_bot.db      │
    │  (SQLite mock)      │   │   (SQLite dev)          │
    │                     │   │                        │
    │  tenderlot_user     │   │  bot_user              │
    │  tenderlot_tender   │   │  notification_log      │
    └─────────────────────┘   └────────────────────────┘
```

---

## Quick start in Replit

1. **Set the bot token secret**
   - In the Replit sidebar → Secrets → add `TENDERLOT_BOT_TELEGRAM_BOT_TOKEN` = your bot token from [@BotFather](https://t.me/BotFather)
   - Use a **separate dev bot** — never the production token here

2. **Install dependencies**
   ```bash
   pip install -e ".[dev]"
   ```

3. **Click Run** (or `python main.py` in the Shell)

4. Look for this log line:
   ```
   Bot started. Polling for tenders every 30 seconds.
   ```

5. Open Telegram, find your bot, send `/start`

---

## How to test the full flow

### Step 1 — Link your Telegram account
1. Send `/start` to the bot
2. Tap **✅ Згоден**
3. Tap **📱 Поділитись контактом** — share your contact
4. If your phone is in the mock DB, you'll see "Прив'язку успішно завершено"

> **Test phones pre-seeded:**
> - `+380000000001` — Тестовий Користувач (supplier)
> - `+380675755800` — Апенко Дмитро Сергійович (supplier)

### Step 2 — Trigger a new tender notification
```bash
python scripts/seed_mock_db.py --add-tender
```

### Step 3 — Wait up to 30 seconds
You should receive `🟢 Новий тендер: ...` in Telegram with a working **Відкрити тендер** button.

---

## Running tests

```bash
pytest tests/ -v
```

All tests use in-memory SQLite — no real Telegram API calls are made.

---

## Code quality checks

```bash
# Linting
ruff check src/

# Type checking
mypy src/ --strict

# Both
ruff check src/ && mypy src/ --strict
```

---

## Production migration checklist

When deploying to Render, make these changes:

| What | Dev (Replit) | Production (Render) |
|------|-------------|---------------------|
| `TENDERLOT_BOT_TELEGRAM_BOT_TOKEN` | Dev bot token | Production bot token |
| `TENDERLOT_BOT_TENDERLOT_DATABASE_URL` | `sqlite+aiosqlite:///./tenderlot_mock.db` | `mysql+pymysql://user:pass@host/tenderlot` |
| `TENDERLOT_BOT_BOT_DATABASE_URL` | `sqlite+aiosqlite:///./tenderlot_bot.db` | `postgresql+asyncpg://user:pass@neon.host/tenderlot_bot` |
| `TENDERLOT_BOT_BOT_MODE` | `polling` | `webhook` |
| `TENDERLOT_BOT_ENVIRONMENT` | `replit_dev` | `render_prod` |
| `TENDERLOT_BOT_LOG_FORMAT` | `text` | `json` |

**Additional steps for production:**
1. Switch `main.py` from `app.run_polling()` to `app.run_webhook(url=..., webhook_url=...)` when `settings.bot_mode == "webhook"`
2. Remove the `mocks/` layer and `tenderlot_mock.db` — connect to real MariaDB
3. Apply database migrations on Neon PostgreSQL before first deploy
4. Set `TENDERLOT_BOT_LOG_FORMAT=json` for structured logging in Render dashboard
5. Configure `WEBHOOK_URL` to `https://your-render-app.onrender.com/webhook`
6. Add CA certificate if MariaDB requires TLS: set `ssl_ca` in the connection args

---

## Known limitations of this skeleton

- **No real database connection** — tenderlot data is mocked in SQLite
- **Polling only** — webhook mode is noted in code but not implemented
- **No T−10 minute reminders** — out of scope for this phase
- **No "bid outbid" notifications** — out of scope
- **No tender completion / winner notifications** — out of scope
- **No currency conversion** — currency is stored and displayed as-is
- **No email fallback** — Telegram-only
- **No web dashboard** — management via bot commands only
- **Single notification template** — auction and proposal_collection use the same message
- **SQLite concurrency limits** — fine for dev; PostgreSQL required for production load
