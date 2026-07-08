---
name: Partial unique index ON CONFLICT
description: How to write upsert INSERT ... ON CONFLICT statements when the target uniqueness comes from a partial unique index (e.g. CREATE UNIQUE INDEX ... WHERE col IS NOT NULL) rather than a table constraint.
---

When a column's uniqueness is enforced via `CREATE UNIQUE INDEX ux_name ON table (col) WHERE col IS NOT NULL` (a nullable/optional-identity column pattern — e.g. supporting two mutually exclusive identity types like `tg_user_id` vs `web_session_id` on the same table), Postgres does NOT let you target it with `ON CONFLICT ON CONSTRAINT ux_name` — that syntax only works for indexes backing a real named constraint (`ADD CONSTRAINT ... UNIQUE`/`PRIMARY KEY`), and raises `constraint "..." does not exist` for a bare index.

**Why:** Easy trap when the schema uses partial unique indexes for conditional uniqueness (nullable dual-identity columns, soft-delete-aware uniqueness, etc.) instead of a full constraint — the natural-looking `ON CONFLICT ON CONSTRAINT <index_name>` compiles fine mentally but fails at runtime, and `ON CONFLICT (col)` alone also fails with `no unique or exclusion constraint matching the ON CONFLICT specification` because Postgres can't tell which partial index you mean without the predicate.

**How to apply:** Match the index's inference clause exactly: `INSERT ... ON CONFLICT (col1[, col2]) WHERE <same predicate as the index> DO NOTHING/UPDATE ...`. E.g. for `CREATE UNIQUE INDEX ux_turns ON turns (session_id, turn_index) WHERE turn_index IS NOT NULL`, use `ON CONFLICT (session_id, turn_index) WHERE turn_index IS NOT NULL DO NOTHING`. Verify against `pg_indexes`/`information_schema` before writing the upsert, not after a 500 in prod.
