#!/bin/bash

echo "========================================"
echo "  Gradus Media AI Agent - Starting..."
echo "========================================"
echo ""

cleanup() {
    echo ""
    echo "Shutting down services..."
    kill $BACKEND_PID $FRONTEND_PID 2>/dev/null
    exit 0
}

trap cleanup SIGINT SIGTERM

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting FastAPI backend on port 8000..."
cd backend
uvicorn main:app --host 0.0.0.0 --port 8000 --log-level info &
BACKEND_PID=$!
cd ..

sleep 2

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting React frontend on port 5000..."
cd frontend
npm run preview -- --host 0.0.0.0 --port 5000 &
FRONTEND_PID=$!
cd ..

sleep 2

echo ""
echo "========================================"
echo "  Services Started Successfully"
echo "========================================"
echo "  Backend:  http://0.0.0.0:8000"
echo "  Frontend: http://0.0.0.0:5000"
echo "  Health:   http://0.0.0.0:8000/health"
echo "========================================"
echo ""
echo "Press Ctrl+C to stop all services"
echo ""

wait $BACKEND_PID $FRONTEND_PID
