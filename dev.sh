#!/usr/bin/env bash
# Starts the backend (FastAPI, :8000) and frontend (Vite, :5173) together.
# Ctrl+C stops both. See README.md for one-time setup (venv, npm install, .env).
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ ! -x "$ROOT_DIR/backend/.venv/bin/uvicorn" ]; then
  echo "backend/.venv not found or incomplete. Run the Backend setup steps in README.md first." >&2
  exit 1
fi

if [ ! -d "$ROOT_DIR/frontend/node_modules" ]; then
  echo "frontend/node_modules not found. Run 'npm install' in frontend/ first (see README.md)." >&2
  exit 1
fi

BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
  echo
  echo "Stopping..."
  [ -n "$BACKEND_PID" ] && kill "$BACKEND_PID" 2>/dev/null || true
  [ -n "$FRONTEND_PID" ] && kill "$FRONTEND_PID" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

(cd "$ROOT_DIR/backend" && .venv/bin/uvicorn app.main:app --reload --port 8000) &
BACKEND_PID=$!

(cd "$ROOT_DIR/frontend" && npm run dev) &
FRONTEND_PID=$!

echo
echo "Backend:  http://localhost:8000"
echo "Frontend: http://localhost:5173"
echo "Press Ctrl+C to stop both."
echo

wait
