#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

BACKEND_HOST="${BACKEND_HOST:-0.0.0.0}"
BACKEND_PORT="${BACKEND_PORT:-41900}"
FRONTEND_HOST="${FRONTEND_HOST:-0.0.0.0}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

cd "$ROOT_DIR"

backend_pid=""
frontend_pid=""

cleanup() {
  if [[ -n "${frontend_pid}" ]] && kill -0 "${frontend_pid}" 2>/dev/null; then
    kill "${frontend_pid}" 2>/dev/null || true
  fi
  if [[ -n "${backend_pid}" ]] && kill -0 "${backend_pid}" 2>/dev/null; then
    kill "${backend_pid}" 2>/dev/null || true
  fi
}

trap cleanup EXIT INT TERM

echo "[hogue-ide] Starting backend on ${BACKEND_HOST}:${BACKEND_PORT}"
uv run uvicorn main:app --host "${BACKEND_HOST}" --port "${BACKEND_PORT}" --reload --reload-dir backend &
backend_pid=$!

echo "[hogue-ide] Starting frontend dev server on ${FRONTEND_HOST}:${FRONTEND_PORT}"
pnpm dev --host "${FRONTEND_HOST}" --port "${FRONTEND_PORT}" --strictPort &
frontend_pid=$!

while true; do
  if ! kill -0 "${backend_pid}" 2>/dev/null; then
    echo "[hogue-ide] Backend exited. Shutting down."
    break
  fi
  if ! kill -0 "${frontend_pid}" 2>/dev/null; then
    echo "[hogue-ide] Frontend exited. Shutting down."
    break
  fi
  sleep 1
done
