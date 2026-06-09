#!/bin/bash
echo "starting miner server"
set -euo pipefail

. /app/venv/bin/activate
cd /app/app
uvicorn app.app --host 0.0.0.0 --port 8000