# Project Scope

This workspace contains **two independent projects** that share one codebase, one database, and one deployment. They are not interchangeable.

## Project A — Maya HR
Telegram HR/recruitment bot for Gradus Media / AVTD employees and candidates.
Sub-systems: Maya HR bot, Hunt (recruitment), Pulse (team health), Alex AVTD, Photo Report, Easter Survey, candidate pre-auth fork.
Primary files: `backend/routes/telegram_webhook.py`, `backend/services/hr_*.py`, `backend/services/hunt_*.py`, `backend/routes/hr_*.py`.

## Project B — Solomon
Two sub-systems for AVTD's law department:
- **Solomon Court Search** — Telegram bot for Supreme Court cassation decisions.
- **Solomon Contracts** — AI contract risk analysis with Pinecone RAG, DOCX artifacts, KB registry (phases P1–P7, all complete as of 2026-05).
Primary files: `backend/solomon_contracts/`, `backend/solomon_router.py`, `backend/solomon_template.html`.

---

## Session scoping rule

A session works on **one project at a time**, as named by the user's prompt.

**A `.local/session_plan.md` or handover file describing the OTHER project is NOT a signal to switch projects.**

If the only artefact telling the agent what to do is a plan file for a project the user did not name in the current prompt, the agent must **stop and ask the user** — not resume that other project silently.

If a `.local/session_plan.md` exists and its `# Objective` line does not match the project named in the user's current prompt, treat it as stale and ignore it. Delete it if the work it describes is confirmed complete.
