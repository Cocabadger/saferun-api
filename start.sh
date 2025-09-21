#!/bin/sh
set -e
PORT_VALUE=${PORT:-8500}

# Ensure SQLite directory exists when using local/volume storage
DEFAULT_SQLITE_PATH="/data/saferun.db"
SQLITE_PATH="${SR_SQLITE_PATH:-$DEFAULT_SQLITE_PATH}"
SQLITE_DIR="$(dirname "$SQLITE_PATH")"
if [ ! -d "$SQLITE_DIR" ]; then
  if ! mkdir -p "$SQLITE_DIR" 2>/dev/null; then
    echo "[start.sh] WARN: unable to create $SQLITE_DIR, falling back to ./data" >&2
    SQLITE_PATH="data/saferun.db"
    SQLITE_DIR="$(dirname "$SQLITE_PATH")"
    mkdir -p "$SQLITE_DIR"
  fi
fi
export SR_SQLITE_PATH="$SQLITE_PATH"

exec uvicorn saferun.app.main:app --host 0.0.0.0 --port "$PORT_VALUE"
