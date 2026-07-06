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
  Sara's `chk_sara_*`). Going-forward rule. Known legacy columns WITHOUT
  constraints — do not assume the DB rejects typos here:
  `hunt_candidates.hr_decision`, `hunt_sources.channel_type`,
  `hr_broadcast_log.status`.
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
  inbound dedup table (`sara_inbound_updates`, `ON CONFLICT DO NOTHING`) and
  atomic transitions (`UPDATE ... WHERE status='pending' RETURNING ...`,
  see `solomon_contracts/router.py:107`). **KNOWN GAP: Maya HR, Alex Gradus,
  and Alex AVTD webhooks have no update-id dedup.** New handlers must have it.
- **User-facing flows never crash silently:** wrap sends and keyboard
  rendering in try/except with a plain-text fallback (reference:
  `telegram_webhook.py:~508-524`). **KNOWN GAP:**
  `telegram_webhook.py:449` calls `process_telegram_message()` unwrapped —
  an AI/RAG failure there produces the exact 200-OK-but-silent failure this
  rule forbids.
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

1. Maya HR webhook not auto-registered on startup.
2. Maya HR / Alex Gradus / Alex AVTD: no inbound update dedup.
3. `telegram_webhook.py:449` — unwrapped `process_telegram_message()` call.
4. `remove_discontinued_products.py:67` — namespace-less Pinecone delete.
5. `hunt_candidates.hr_decision`, `hunt_sources.channel_type`,
   `hr_broadcast_log.status` — no CHECK constraints.
6. Duplicate `052` migration prefix (both applied; harmless at PK level;
   never reason "by number").

When any of these areas is touched for other reasons, closing the adjacent
gap in the same change is preferred over preserving it. Removing an item from
this register requires evidence (file + line) in the commit message.
