#!/bin/sh
set -e
PORT_VALUE=${PORT:-8500}
exec uvicorn saferun.app.main:app --host 0.0.0.0 --port "$PORT_VALUE"
