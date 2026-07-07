# CLAUDE.md — gradus-ai

Persistent rules and verified facts for AI assistants working on this codebase.
Every claim below was verified against the actual code (audit: July 2026).
`replit.md` holds the descriptive project overview and changelog; this file
holds behavioral rules. When they conflict, this file wins for *how to work*,
`replit.md` wins for *what exists* only if it is newer than this file.
The Gradus AI platform handover document (April 2026) is historical
context only — useful for stakeholder routing and product origins,
but its current-state claims (migration numbers, repo structure,
pending items) are stale; where it conflicts with this file or with
the code, it is wrong.

---

## 1. What this is

Gradus AI platform for AVTD (Ukraine's largest alcohol distributor).
**Monorepo:** `backend/` (FastAPI/Python → Render) and `frontend/`
(Vite + React `.jsx`, not TypeScript → Cloudflare Pages) in one repo.
Shared Neon PostgreSQL, shared Pinecone index (`gradus-media`), Anthropic
Claude (Sonnet client-facing, Haiku background). Seven Telegram bots on
eight webhook routes share one Render service — **every deploy restarts
all of them.**

| Bot | Webhook path | Token env var |
|---|---|---|
| Maya HR | `/api/telegram/webhook/maya` (+ legacy `/api/telegram/webhook`) | `TELEGRAM_MAYA_BOT_TOKEN` |
| GradusMediaBot | `/api/telegram/webhook/gradus` | `TELEGRAM_BOT_TOKEN` |
| Alex Gradus | `/webhook/alex-gradus` | `ALEX_GRADUS_BOT_TOKEN` |
| Alex AVTD | `/api/telegram/alex_avtd_webhook` | `TELEGRAM_ALEX_AVTD_BOT_TOKEN` |
| Sara | `/webhook/sara` | `SARA_BOT_TOKEN` |
| Photo Report | `/webhook/photo-report` | `PHOTO_REPORT_BOT_TOKEN` |
| SOLOMON | `/law/telegram/webhook` | `SOLOMON_BOT_TOKEN` |

**Maya Hunt is parked (July 2026).** Do not refactor, extend, or "improve"
hunt_* code, hunt_ tables, or the Telethon scraper unless Hunt is
reactivated or the change is required by a live feature sharing the same
file. Section 4's Telethon rule remains binding for anyone who ever
reactivates it.

---

## 2. Non-negotiable workflow rules

1. **Audit before implement.** Audit prompts read files and report; only after
   review does an implementation prompt go out. Never combine them.
2. **Read the relevant files, don't work from summaries.** Before calling a
   function from a service file, open that file and grep for the name.
3. **Before writing any migration**, run
   `SELECT version, applied_at FROM schema_migrations ORDER BY applied_at DESC LIMIT 10;`
   against the production Neon DB and number strictly above the true maximum.
   Never pick a number from code, docs, or chat memory — the 052 duplicate
   prefix (`052_citation_filter` / `052_avtd_role_default_notnull`, both
   applied) exists because an agent numbered from stale context.
4. **Consult the developer agent before structural decisions.** Claude
   proposes → the agent that can read the code validates → then implement.
5. **Post-deploy reconciliation:** report which other routes/handlers import
   from every changed file and confirm they still import cleanly. Then confirm
   Maya HR + SOLOMON respond in Telegram (deploy restarts all seven bots).

---

## 3. Database rules

- Migrations are entries in the flat `MIGRATIONS` list in
  `backend/db_migrations.py`, run on startup via `run_migrations()` in the
  FastAPI lifespan. The `backend/migrations/*.sql` directory is **legacy and
  not executed** — never add files there.
- `schema_migrations`: `version VARCHAR(255) PRIMARY KEY, applied_at TIMESTAMP`.
  Uniqueness is on the full string, not the numeric prefix — which is why
  rule 2.3 exists.
- Migrations are **append-only**: never edit an applied migration; fix forward.
- **New migrations must be idempotent** (`IF NOT EXISTS`, `ON CONFLICT DO
  NOTHING`, `DO $$` guards for constraint changes). Known non-compliant legacy
  entries exist (e.g. `052_avtd_role_default_notnull`, `057`, `058`) — do not
  copy their style.
- **CHECK constraints on every enum-like column in new tables** (pattern:
  Sara's `chk_sara_*`). Going-forward rule. `hunt_candidates.hr_decision`,
  `hunt_sources.channel_type`, and `hr_broadcast_log.status` are no longer
  exceptions — all three now have `chk_<table>_<column>` constraints
  (migration `065_legacy_enum_check_constraints`).
- **DB access pattern is per-module, not per-layer.** Existing modules:
  raw psycopg2 with explicit close — `broadcast_service`, `survey_service`,
  `solomon_contracts/db`; SQLAlchemy ORM — `scheduler`, request routes;
  mixed — `hunt_service`. When editing a module, match its existing pattern;
  never introduce a second pattern into one module.
- **Neon drops connections.** Engine has `pool_pre_ping=True, pool_recycle=300`.
  Scheduled bulk jobs commit per-item with rollback → fresh session →
  re-fetch → retry-once (reference implementation:
  `scheduler.py` translation job, ~line 262).
- Table prefixes by product (complete list): `hr_`, `hunt_`, `maya_`, `alex_`,
  `photo_`, `pulse_`, `sara_`, `solomon_`, `solcon_`, `linkedin_`, `video_`.
  New products get a new prefix.
- Two Telegram inbound dedup tables coexist by design (append-only rule
  forbids merging them): `telegram_inbound_updates` (shared, composite PK
  `bot_source, update_id` — Maya/Alex Gradus/Alex AVTD) and
  `sara_inbound_updates` (Sara's own). Both are retained by the daily
  `cleanup_telegram_inbound_dedup` scheduler job.

---

## 4. Telegram rules

- **Webhooks only, never polling** in production code (409 Conflict on
  Render zero-downtime deploys).
- Webhooks auto-register in the `main.py` lifespan for six bots.
  **KNOWN GAP: Maya HR is NOT auto-registered** — after any webhook-URL
  change, Maya requires manual `setWebhook`. If you touch the lifespan,
  closing this gap is the preferred fix over preserving it.
- **Idempotency for any handler with side effects.** Telegram retries
  unanswered webhooks; users double-tap. Patterns in the codebase:
  inbound dedup tables (`ON CONFLICT DO NOTHING`) and atomic transitions
  (`UPDATE ... WHERE status='pending' RETURNING ...`, see
  `solomon_contracts/router.py:107`). Maya, Alex Gradus, and Alex AVTD dedup
  on the shared `telegram_inbound_updates` table (composite PK
  `bot_source, update_id`); Sara keeps her own `sara_inbound_updates`. Both
  tables are pruned by the daily `cleanup_telegram_inbound_dedup` scheduler
  job (48h retention). New handlers must dedup the same way.
- **User-facing flows never crash silently:** wrap sends and keyboard
  rendering in try/except with a plain-text fallback (reference:
  `telegram_webhook.py:~508-524`).
- One bot token per bot per environment. Never reuse a dev (Replit) token on
  Render — causes 409s and startup timeouts.
- **Telethon (Maya Hunt) is pull-based only:** `iter_messages` over entities
  resolved from the `hunt_sources` allowlist (`channel_type='scan'`).
  There is deliberately **no** `events.NewMessage` listener. If anyone ever
  adds an event-driven Telethon listener, they MUST add a hard chat filter
  (`if chat_id > 0: return` + env-driven allowlist) in the same commit —
  a personal session receives ALL of the account's DMs, and an unfiltered
  listener previously leaked private messages into the /hr dashboard.

---

## 5. Pinecone / embeddings

- One index: `gradus-media` (1536-dim). Namespaces in use:

  | Namespace | Owner | Written by |
  |---|---|---|
  | `hr_docs` | Maya HR knowledge | `hr_content_processor`, `upload_hr_data` |
  | `company_knowledge` | GradusMedia / Alex knowledge | `rag_utils`, `chat_endpoints` |
  | `solomon-contracts-corpus` | Solomon legal corpus | `solomon_contracts/corpus`, `kb_ingest` |
  | `solomon-contracts-findings` | Solomon findings | `solomon_contracts/corpus` |

- **Every Pinecone operation must pass `namespace=` explicitly.** The default
  (unnamed) namespace is off-limits.
  **KNOWN LANDMINE:** `scripts/remove_discontinued_products.py:67` calls
  `index.delete(ids=batch)` with no namespace — it targets the default
  namespace, not `company_knowledge`. Fix before reusing that script.
- Embedding model: `text-embedding-3-small` only, everywhere. Never mix
  models in the index.

---

## 6. Scheduler / time

- **No `timezone=` kwarg in any CronTrigger.** All cron jobs are UTC with
  the Kyiv time noted in a comment (e.g. `hour=2  # 04:00 Kyiv summer`).
  History: `timezone='Europe/Kiev'` crashed a Render deploy.
- `tzdata` is pinned in `requirements.txt`, so `ZoneInfo("Europe/Kyiv")` in
  runtime code (e.g. `survey_service.py:168`) is acceptable — but prefer it
  over hardcoded offsets for anything user-facing, since UTC-offset cron
  comments drift by one hour at DST changes.
- Python version pinning: deployment is `runtime: docker` per `render.yaml`;
  the pin (if any) lives in the `Dockerfile`. Pinned: Dockerfile line 1 is
  `FROM python:3.11-slim`. If you change the base image, update this line
  in the same commit.

---

## 7. Deployment

- `git push origin main` → Render auto-deploys backend → migrations run on
  startup → **all seven bots restart**. Frontend deploys to Cloudflare Pages
  from its own push.
- **Before pushing:** required env vars must already exist on Render (and in
  Cloudflare Pages with `VITE_` prefix for frontend vars). The same value is
  often needed in both Replit Secrets (dev) and Render (prod) — set both.
- Court-registry (reyestr) **data fetches** go through the Replit proxy
  (`court-search-agent.replit.app`) — Render/AWS IPs are blocked. Direct
  `reyestr.court.gov.ua` URLs are permitted only as user-facing link buttons.
- **KNOWN LIMITATION (July 2026):** reyestr deployed an anti-automation
  captcha on search; SOLOMON court search (Судова практика) is broken
  upstream — not a code bug (proxy returns 200, backend healthy,
  Solomon Contracts worker unaffected). Fix path: authenticated
  "Повний доступ" reyestr account, session held by the Replit proxy.
  Do not debug the proxy or backend for this.

## 8. Post-deploy verification checklist

- [ ] Render deploy green; startup logs show migrations applied/skipped cleanly
- [ ] Migration row present in `schema_migrations` (if a migration shipped)
- [ ] New tables/constraints verified via `information_schema`
- [ ] `git diff` on `db_migrations.py` is pure addition
- [ ] Maya HR + SOLOMON respond in Telegram
- [ ] No `Webhook error` lines or 404 floods in Render logs
- [ ] Changed files: dependent handlers re-import cleanly (rule 2.5)

---

## 9. Business constraints

- User-facing content in Ukrainian. Use "бренді", never "коньяк"
  (Ukrainian legislation).
- Address the owner as "Вітаю, Фелікс Борисович!" — never with surname.
- AVTD brands: GREENDAY, HELSINKI, UKRAINKA, ADJARI, DOVBUSH, KLINKOV,
  VILLA UA, DIDI LARI, KRISTI VALLEY, KOSHER, FUNJU (secondary: Marlin,
  Viaggio, Pedro Martinez). **NOT AVTD:** Nemiroff, Hlibny Dar, Oxygen,
  Celsius, Aznauri, Adamyan, Aliko, Koblevo VS, Bolgrad.
- KOSHER = єдині кошерні вина в Україні. No WINEVIAGGIO/ADJARI in the wine
  category.
- Social media images: Unsplash only, never AI-generated (algorithmic
  suppression 15–80%).

---

## 10. Known gaps register (fix candidates — do not silently rely on these)

1. Duplicate `052` migration prefix (both applied; harmless at PK level;
   never reason "by number").
2. `telegram_webhook.py:429` — `asyncio.create_task(_handle_hunt_vacancy(...))`
   fire-and-forget; task failures are invisible (no done-callback / exception
   logging). (Maya Hunt path — feature parked; fix only if Hunt reactivates
   or the file is touched for other reasons.)

When any of these areas is touched for other reasons, closing the adjacent
gap in the same change is preferred over preserving it. Removing an item from
this register requires evidence (file + line) in the commit message.

---

## 11. Sara English — realtime voice service

### Deployment
- Second Render service named **`sara-english`**, same repo and Dockerfile as
  the main backend.
- Docker Command (dashboard is authoritative):  `bash start_sara.sh`
  The `render.yaml` entry mirrors this for documentation only.
- Package: `backend/sara_realtime/` — deliberately **not** renamed to match
  the service name; it names the architecture, not the product.

### Hard rules — never violate
- **No migrations, no DB reads/writes, no webhook registration, no Telegram**
  in this service. Any import of `sqlalchemy`, `psycopg`, `register_webhook`,
  or Telegram-bot code is a regression.
- **AsyncAnthropic only** in `pipeline.py`. The sync `Anthropic` client is
  forbidden here (blocks the event loop during streaming).
- **Half-duplex by design.** Mic frames are discarded while Sara is speaking
  (`turn_active` gate at ingestion) and committed transcripts are dropped
  while a turn is active (`stt_recv` gate). This is correct behaviour — do
  not "fix" the gating. Barge-in is a Phase 3 feature.

### Voice / model env vars — explicit split
| Variable | Holds | Notes |
|---|---|---|
| `SARA_RT_VOICE_ID` | Clarice — `sIak7pFapfSLCfctxdOu` | **Set explicitly. Never fall back to `ELEVENLABS_VOICE_ID`.** |
| `ELEVENLABS_VOICE_ID` | Yaroslava (employee bot) | Belongs to the main service only. |
| `SARA_RT_TTS_MODEL` | Realtime TTS model (Flash / `multilingual_v2`) | `eleven_v3` is **not** supported on the TTS WebSocket. |
| `ELEVENLABS_TTS_MODEL` | Async Telegram path | `sara_webhook.py` only — never used in `sara_realtime/`. |
| `SARA_RT_VAD_SILENCE_S` | VAD commit threshold in seconds (default `2.2`) | Tunable without redeploy. |

### Regression checklist R1–R10
Must be included verbatim in every Sara implementation prompt and re-verified
(all PASS) in every implementation report.

| # | What to check | How |
|---|---|---|
| R1 | `SARA_REALTIME_PROMPT_BASE` + level block contains **zero** `{` chars | `composed.count('{') == 0` |
| R2 | `t0 = time.monotonic()` appears **exactly once** in `run_turn` (at entry — VAD commit baseline) | `getsource(run_turn).count('t0 = time.monotonic()') == 1` |
| R3 | Scribe URL contains `model_id`, `audio_format=pcm_16000`, `commit_strategy=vad`, `vad_silence_threshold_secs={VAD_SILENCE_S}` | format the template and assert all four substrings |
| R4 | `xi_api_key` absent from both `STT_URL_TMPL` and `TTS_URL_TMPL` | string search |
| R5 | `eleven_flash_v2_5` present in `app.py` | string search |
| R6 | `AsyncAnthropic` present in `pipeline.py`; sync `Anthropic` import absent | string search |
| R7 | EOS frame `{"text": ""}` present in `FlashStreamingTTS.close_stream()` | `json.dumps({'text':''}) in getsource(close_stream)` |
| R8 | No `sqlalchemy` / `psycopg` / `register_webhook(` calls anywhere in `sara_realtime/` | grep |
| R9 | `ConnectionClosedError`/`OK` **not** caught inside `ScribeRealtimeSTT.receive_events()` | assert absent from `getsource(receive_events)` |
| R10 | No `get_nowait()` drain loop in `app.py` or `pipeline.py` | string search |

### Known gaps (Sara-specific)
1. **Intermittent silent-audio turn** — one observed instance; root side
   (server or client) undetermined. Diagnose first: correlate the
   `SARA_RT_TURN` log line with browser console output before writing any
   fix.
2. **Claude first-token variance 0.8–4.8 s** — Anthropic-side latency, not
   a local bug. Monitor in pilot; do not attempt to work around in code
   without data showing a consistent pattern.
