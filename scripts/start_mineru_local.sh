#!/usr/bin/env bash
set -euo pipefail

# macOS-compatible case-insensitive comparison (bash 3.2 compatible)
to_lower() {
  echo "$1" | tr '[:upper:]' '[:lower:]'
}

# Usage:
#   bash scripts/start_mineru_local.sh [gradio|api|openai|all|--help]
# Examples:
#   bash scripts/start_mineru_local.sh gradio
#   bash scripts/start_mineru_local.sh api
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
PORT_SCAN_SPAN="${MINERU_PORT_SCAN_SPAN:-98}"

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

print_usage() {
  echo "Usage: bash scripts/start_mineru_local.sh [gradio|api|openai|all]"
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

    cleanup() {
      echo
      echo "[info] stopping all services..."
      for pid in "${pids[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
          kill "$pid" 2>/dev/null || true
        fi
      done
      wait || true
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
  *)
    echo "Unknown mode: $MODE"
    print_usage
    exit 1
    ;;
esac
