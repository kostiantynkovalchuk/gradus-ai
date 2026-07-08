---
name: sara_realtime standalone service testing
description: How to actually reach a live server when testing sara_realtime (or any standalone uvicorn service not bound to a configured workflow) via the bash tool.
---

`backend/sara_realtime/` is a standalone FastAPI/uvicorn service, separate from the `backend` workflow (which runs the main app on port 8000). There is no configured workflow for it in dev.

**Why this matters:** background processes started with `&`, `nohup ... &`, or `(cmd &)` in one `bash` tool call do NOT survive into the next `bash` tool call — the sandbox tears down child processes between invocations. Attempts to start the server in one call and `curl` it in a later call will always get connection-refused (curl exit code / http 000), even though the log file shows "Application startup complete".

**How to apply:** start the server, sleep long enough for full import/startup (a few seconds — heavier than it looks due to anthropic/elevenlabs client imports), curl the endpoints, and kill the PID — all inside **one single bash tool invocation** (`cmd & ...; sleep N; curl ...; kill $!`). This is the only reliable way to smoke-test standalone services that aren't wired to a workflow.

Also: manually curling an ad-hoc port (e.g. 8899) causes Replit to auto-append a `[[ports]]` block to `.replit`. That file can't be edited directly by the agent (blocked), so prefer reusing a port you don't mind leaving registered, or accept the harmless leftover mapping.
