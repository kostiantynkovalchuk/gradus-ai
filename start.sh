#!/bin/bash

echo "========================================"
echo "  Gradus Media AI Agent - Starting..."
echo "========================================"
echo ""

PORT="${PORT:-10000}"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting FastAPI backend on port $PORT..."
echo "Backend will serve both API and frontend static files"
echo ""

cd backend
exec uvicorn main:app --host 0.0.0.0 --port $PORT --log-level info
