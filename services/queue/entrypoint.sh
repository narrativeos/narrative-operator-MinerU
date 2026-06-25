#!/usr/bin/env bash
###
 # @Author: Future Meng futuremeng@gmail.com
 # @Date: 2026-06-25 20:44:55
 # @LastEditors: Future Meng futuremeng@gmail.com
 # @LastEditTime: 2026-06-25 23:28:45
 # @FilePath: /narrative-operator-MinerU/services/queue/entrypoint.sh
 # @Description: 这是默认设置,请设置`customMade`, 打开koroFileHeader查看配置 进行设置: https://github.com/OBKoro1/koro1FileHeader/wiki/%E9%85%8D%E7%BD%AE
### 
set -euo pipefail

echo "Starting MinerU Queue Service..."

# Ensure temp directory exists
mkdir -p /tmp/mineru-queue
mkdir -p /app/output

# Activate virtual environment if it exists
if [ -d "/app/venv" ]; then
    . /app/venv/bin/activate
fi

# Export environment variables with defaults
export MINERU_REDIS_HOST="${MINERU_REDIS_HOST:-redis}"
export MINERU_REDIS_PORT="${MINERU_REDIS_PORT:-6379}"
export MINERU_REDIS_DB="${MINERU_REDIS_DB:-0}"
export MINERU_QUEUE_PORT="${MINERU_QUEUE_PORT:-8403}"
export MINERU_QUEUE_HOST="${MINERU_QUEUE_HOST:-0.0.0.0}"
export MINERU_QUEUE_MAX_SIZE="${MINERU_QUEUE_MAX_SIZE:-20}"
export MINERU_QUEUE_RESULT_TTL="${MINERU_QUEUE_RESULT_TTL:-86400}"
export MINERU_QUEUE_OUTPUT_ROOT="${MINERU_QUEUE_OUTPUT_ROOT:-/app/output}"
export MINERU_QUEUE_TMP_DIR="${MINERU_QUEUE_TMP_DIR:-/tmp/mineru-queue}"
export MINERU_QUEUE_POLL_INTERVAL="${MINERU_QUEUE_POLL_INTERVAL:-1.0}"

cd /app
export PYTHONPATH=/app:${PYTHONPATH:-}
exec uvicorn mineru_queue.app:app --host "$MINERU_QUEUE_HOST" --port "$MINERU_QUEUE_PORT"
