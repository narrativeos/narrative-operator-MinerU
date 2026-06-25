#!/usr/bin/env bash
set -euo pipefail

# macOS-compatible case-insensitive comparison (bash 3.2 compatible)
to_lower() {
  echo "$1" | tr '[:upper:]' '[:lower:]'
}

# Usage:
#   bash scripts/start_mineru_local.sh [gradio|api|openai|queue|all|--help]
# Examples:
#   bash scripts/start_mineru_local.sh gradio
#   bash scripts/start_mineru_local.sh api
#   bash scripts/start_mineru_local.sh queue
#   bash scripts/start_mineru_local.sh all

MODE="${1:-gradio}"

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

# Auto-activate uv virtual environment if it exists
if [[ -d ".venv" ]]; then
  echo "[info] activating uv environment: .venv"
  source .venv/bin/activate
elif command -v uv &>/dev/null && uv venv --help &>/dev/null; then
  echo "[info] creating uv environment..."
  uv venv
  source .venv/bin/activate
fi

# Optional: use domestic model source by default.
export MINERU_MODEL_SOURCE="modelscope"
# Prefer conservative hybrid batch ratio on shared GPUs unless user overrides it.
export MINERU_HYBRID_BATCH_RATIO="${MINERU_HYBRID_BATCH_RATIO:-1}"

# Tunables for local startup. Override via environment variables when needed.
GPU_MEMORY_UTILIZATION="${MINERU_GPU_MEMORY_UTILIZATION:-0.4}"
DATA_PARALLEL_SIZE="${MINERU_DATA_PARALLEL_SIZE:-1}"
MAX_CONVERT_PAGES="${MINERU_MAX_CONVERT_PAGES:-1500}"
BATCH_MAX_CONVERT_PAGES="${MINERU_BATCH_MAX_CONVERT_PAGES:-100}"
ENABLE_GRADIO_UI_CACHE="${MINERU_ENABLE_GRADIO_UI_CACHE:-true}"
ENABLE_API_CACHE="${MINERU_ENABLE_API_CACHE:-true}"

# Preferred ports. If occupied, script will pick the next available port in range.
# Ports are in the 8400-8499 range
GRADIO_PORT="${MINERU_GRADIO_PORT:-8400}"
API_PORT="${MINERU_API_PORT:-8401}"
OPENAI_PORT="${MINERU_OPENAI_PORT:-8402}"
QUEUE_PORT="${MINERU_QUEUE_PORT:-8403}"
REDIS_PORT="${MINERU_REDIS_PORT:-6379}"
PORT_SCAN_SPAN="${MINERU_PORT_SCAN_SPAN:-98}"

# Redis management
REDIS_PID_FILE="${ROOT_DIR}/.redis.pid"

start_redis() {
  # Check if Redis is already running
  if ! command -v redis-server &>/dev/null; then
    echo "[warn] redis-server not found in PATH" >&2
    echo "       Install: brew install redis (macOS) or apt-get install redis-server (Linux)" >&2
    return 1
  fi

  # Check if there's already a Redis process on the port
  if python -c "import socket; sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM); sock.settimeout(1); sock.connect(('127.0.0.1', ${REDIS_PORT})); sock.close()" 2>/dev/null; then
    echo "[info] Redis already running on :${REDIS_PORT}"
    return 0
  fi

  echo "[start] starting Redis on :${REDIS_PORT}"
  redis-server \
    --port "${REDIS_PORT}" \
    --bind 127.0.0.1 \
    --protected-mode no \
    --daemonize yes \
    --pidfile "${REDIS_PID_FILE}" \
    --dir "${ROOT_DIR}/services/redis/data" \
    --logfile "${ROOT_DIR}/.redis.log" 2>/dev/null || {
      echo "[warn] Failed to start Redis. Is redis-server installed?" >&2
      echo "       Install: brew install redis (macOS) or apt-get install redis-server (Linux)" >&2
      return 1
    }
  echo "[ok] Redis started on :${REDIS_PORT}"
}

stop_redis() {
  if [ -f "${REDIS_PID_FILE}" ]; then
    redis_pid=$(cat "${REDIS_PID_FILE}" 2>/dev/null || true)
    if [ -n "${redis_pid}" ] && kill -0 "${redis_pid}" 2>/dev/null; then
      echo "[info] stopping Redis (pid ${redis_pid})..."
      kill "${redis_pid}" 2>/dev/null || true
      sleep 1
      kill -9 "${redis_pid}" 2>/dev/null || true
    fi
    rm -f "${REDIS_PID_FILE}"
    echo "[ok] Redis stopped"
  fi
}

find_free_port() {
  local start_port="$1"
  local span="$2"
  local end_port=$((start_port + span))
  local port

  for ((port = start_port; port <= end_port; port++)); do
    if python - "$port" <<'PY' >/dev/null 2>&1
import socket
import sys

port = int(sys.argv[1])
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    sock.bind(("0.0.0.0", port))
    print(port)
except OSError:
    sys.exit(1)
finally:
    sock.close()
PY
    then
      echo "$port"
      return 0
    fi
  done

  return 1
}

pick_port() {
  local preferred_port="$1"
  local service_name="$2"
  local selected_port

  selected_port="$(find_free_port "$preferred_port" "$PORT_SCAN_SPAN")" || {
    echo "[error] no free port found for ${service_name} in range ${preferred_port}-$((preferred_port + PORT_SCAN_SPAN))" >&2
    echo "        You can expand search range via MINERU_PORT_SCAN_SPAN or set a fixed free port." >&2
    exit 1
  }

  if [[ "$selected_port" != "$preferred_port" ]]; then
    echo "[warn] ${service_name} preferred port :${preferred_port} is busy, using :${selected_port}" >&2
  fi

  echo "$selected_port"
}

start_gradio() {
  local selected_gradio_port
  selected_gradio_port="$(pick_port "$GRADIO_PORT" "gradio")"
  echo "[start] gradio on :${selected_gradio_port}"
  if [[ "$(to_lower "${ENABLE_GRADIO_UI_CACHE}")" == "true" ]]; then
    gradio_cache_flag="--enable-ui-cache"
  else
    gradio_cache_flag="--disable-ui-cache"
  fi
  python -m mineru.cli.gradio_app \
    --server-name 0.0.0.0 \
    --server-port "$selected_gradio_port" \
    --enable-api true \
    "$gradio_cache_flag" \
    --max-convert-pages "$MAX_CONVERT_PAGES" \
    --batch-max-convert-pages "$BATCH_MAX_CONVERT_PAGES" \
    --data-parallel-size "$DATA_PARALLEL_SIZE" \
    --gpu-memory-utilization "$GPU_MEMORY_UTILIZATION"
}

start_api() {
  local selected_api_port
  selected_api_port="$(pick_port "$API_PORT" "api")"
  echo "[start] api on :${selected_api_port}"
  if [[ "$(to_lower "${ENABLE_API_CACHE}")" == "true" ]]; then
    api_cache_flag="--enable-api-cache"
  else
    api_cache_flag="--disable-api-cache"
  fi
  python -m mineru.cli.fast_api \
    --host 0.0.0.0 \
    --port "$selected_api_port" \
    "$api_cache_flag" \
    --max-convert-pages "$MAX_CONVERT_PAGES" \
    --batch-max-convert-pages "$BATCH_MAX_CONVERT_PAGES" \
    --data-parallel-size "$DATA_PARALLEL_SIZE" \
    --gpu-memory-utilization "$GPU_MEMORY_UTILIZATION"
}

start_openai() {
  local selected_openai_port
  selected_openai_port="$(pick_port "$OPENAI_PORT" "openai")"
  echo "[start] openai server on :${selected_openai_port}"
  python -m mineru.cli.vlm_server \
    --host 0.0.0.0 \
    --port "$selected_openai_port" \
    --data-parallel-size "$DATA_PARALLEL_SIZE" \
    --gpu-memory-utilization "$GPU_MEMORY_UTILIZATION"
}

start_queue_docker() {
  echo "[start] starting queue + redis via Docker Compose..."
  
  # Check if Docker is available
  if ! command -v docker &>/dev/null; then
    echo "[error] Docker not found. Please install Docker." >&2
    return 1
  fi
  
  # Build and start queue + redis
  docker compose -f "${ROOT_DIR}/docker/compose.queue.yml" up -d --build || {
    echo "[error] Failed to start queue service via Docker Compose" >&2
    return 1
  }
  
  # Wait for queue service to be ready
  echo "[info] waiting for queue service to be ready..."
  local retries=30
  while [ $retries -gt 0 ]; do
    if curl -s http://127.0.0.1:8403/health >/dev/null 2>&1; then
      echo "[ok] queue service is ready on :8403"
      export MINERU_QUEUE_SERVICE_URL="http://127.0.0.1:8403"
      return 0
    fi
    sleep 1
    retries=$((retries - 1))
  done
  
  echo "[warn] Queue service did not become ready in time" >&2
  return 1
}

stop_queue_docker() {
  echo "[info] stopping queue + redis Docker containers..."
  docker compose -f "${ROOT_DIR}/docker/compose.queue.yml" down || true
  echo "[ok] queue service stopped"
}

print_usage() {
  echo "Usage: bash scripts/start_mineru_local.sh [gradio|api|openai|queue|all]"
  echo ""
  echo "Modes:"
  echo "  gradio  - Start Gradio web UI"
  echo "  api     - Start FastAPI server"
  echo "  openai  - Start OpenAI-compatible VLM server"
  echo "  queue   - Start queue service via Docker (requires Docker)"
  echo "  all     - Start all services (gradio + api + openai + queue+redis via Docker)"
}

if [[ "$MODE" == "--help" || "$MODE" == "-h" ]]; then
  print_usage
  exit 0
fi

if [[ -z "${CONDA_DEFAULT_ENV:-}" ]]; then
  echo "[warn] No conda env detected in this shell."
  echo "       Recommended: conda activate mineru"
fi

echo "[info] working dir: $ROOT_DIR"
echo "[info] python: $(command -v python)"
echo "[info] model source: $MINERU_MODEL_SOURCE"
echo "[info] hybrid-batch-ratio: $MINERU_HYBRID_BATCH_RATIO"
echo "[info] gpu-memory-utilization: $GPU_MEMORY_UTILIZATION"
echo "[info] gradio-ui-cache: $ENABLE_GRADIO_UI_CACHE"
echo "[info] api-cache: $ENABLE_API_CACHE"

case "$MODE" in
  gradio)
    start_gradio
    ;;
  api)
    start_api
    ;;
  openai)
    start_openai
    ;;
  all)
    selected_openai_port="$(pick_port "$OPENAI_PORT" "openai")"
    selected_api_port="$(pick_port "$API_PORT" "api")"
    selected_gradio_port="$(pick_port "$GRADIO_PORT" "gradio")"

    if [[ "$(to_lower "${ENABLE_API_CACHE}")" == "true" ]]; then
      api_cache_flag="--enable-api-cache"
    else
      api_cache_flag="--disable-api-cache"
    fi
    if [[ "$(to_lower "${ENABLE_GRADIO_UI_CACHE}")" == "true" ]]; then
      gradio_cache_flag="--enable-ui-cache"
    else
      gradio_cache_flag="--disable-ui-cache"
    fi

    pids=()

    # Start queue + redis via Docker Compose
    queue_docker_started=false
    if start_queue_docker; then
      queue_docker_started=true
    else
      echo "[warn] Queue service (Docker) not available - Gradio will not show queue toggle" >&2
    fi

    cleanup() {
      echo
      echo "[info] stopping all services..."
      for pid in "${pids[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
          kill "$pid" 2>/dev/null || true
        fi
      done
      wait || true
      if [ "$queue_docker_started" = true ]; then
        stop_queue_docker
      fi
      echo "[ok] all services stopped"
    }

    trap cleanup INT TERM

    echo "[start] openai server on :${selected_openai_port}"
    python -m mineru.cli.vlm_server --host 0.0.0.0 --port "$selected_openai_port" --data-parallel-size "$DATA_PARALLEL_SIZE" --gpu-memory-utilization "$GPU_MEMORY_UTILIZATION" &
    pids+=("$!")

    echo "[start] api on :${selected_api_port}"
    python -m mineru.cli.fast_api --host 0.0.0.0 --port "$selected_api_port" "$api_cache_flag" --max-convert-pages "$MAX_CONVERT_PAGES" --batch-max-convert-pages "$BATCH_MAX_CONVERT_PAGES" --data-parallel-size "$DATA_PARALLEL_SIZE" --gpu-memory-utilization "$GPU_MEMORY_UTILIZATION" &
    pids+=("$!")

    echo "[start] gradio on :${selected_gradio_port}"
    python -m mineru.cli.gradio_app --server-name 0.0.0.0 --server-port "$selected_gradio_port" --enable-api true "$gradio_cache_flag" --max-convert-pages "$MAX_CONVERT_PAGES" --batch-max-convert-pages "$BATCH_MAX_CONVERT_PAGES" --data-parallel-size "$DATA_PARALLEL_SIZE" --gpu-memory-utilization "$GPU_MEMORY_UTILIZATION" &
    pids+=("$!")

    echo "[ok] started all services in foreground-managed mode"
    echo "[info] press Ctrl+C to stop all"

    wait
    ;;
  queue)
    start_queue_docker
    ;;
  *)
    echo "Unknown mode: $MODE"
    print_usage
    exit 1
    ;;
esac
