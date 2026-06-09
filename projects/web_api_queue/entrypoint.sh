#!/usr/bin/env bash
set -euo pipefail

echo "starting miner server"

. /app/venv/bin/activate
exec uvicorn app:app "$@"
