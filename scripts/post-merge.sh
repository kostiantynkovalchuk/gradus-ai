#!/bin/bash
set -e

echo "=== Post-merge setup ==="

echo "--- Installing Python backend dependencies ---"
pip install -r backend/requirements.txt --quiet

echo "--- Running database migrations ---"
cd backend && python3 -c "
import sys
sys.path.insert(0, '.')
from db_migrations import run_migrations
run_migrations()
print('Migrations OK')
"
cd ..

echo "--- Installing frontend dependencies ---"
cd frontend && npm install --silent
cd ..

echo "=== Post-merge setup complete ==="
