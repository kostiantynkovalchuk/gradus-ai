#!/usr/bin/env bash
set -e
cd backend
exec uvicorn sara_realtime.app:app --host 0.0.0.0 --port "${PORT:-10000}"
