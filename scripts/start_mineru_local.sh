#!/usr/bin/env bash
set -euo pipefail

# macOS-compatible case-insensitive comparison (bash 3.2 compatible)
to_lower() {
  echo "$1" | tr '[:upper:]' '[:lower:]'
}

# Usage:
#   bash scripts/start_mineru_local.sh [gradio|api|openai|all|--help]
# Modes:
#   gradio  - mineru-kit webui (auto-starts a managed V1 API server)
#   api     - vlm-server + api-server (api-server uses the local VLM server for Standard/Advanced)
#   openai  - mineru-kit vlm-server (OpenAI-compatible VLM server)
#   all     - vlm-server + webui (webui manages its own V1 API server and
#             uses the local VLM server for Standard/Advanced inference)
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

# Ensure project is installed in current environment
ensure_project_installed() {
  local needs_install=false
  if ! python -c "import loguru" 2>/dev/null; then
    needs_install=true
  fi
  if ! python -c "import gradio" 2>/dev/null; then
    needs_install=true
  fi

  if [ "$needs_install" = true ]; then
    echo "[info] Project dependencies not found, installing..."
    if [[ -d ".venv" ]] && command -v uv &>/dev/null; then
      uv pip install -e "." || {
        echo "[error] Failed to install project dependencies." >&2
        echo "        Please install manually: uv pip install -e ." >&2
        exit 1
      }
    elif command -v pip &>/dev/null; then
      pip install -e "." || {
        echo "[error] Failed to install project dependencies." >&2
        echo "        Please install manually: pip install -e ." >&2
        exit 1
      }
    else
      python -m pip install -e "." || {
        echo "[error] Failed to install project dependencies." >&2
        echo "        Please install manually: python -m pip install -e ." >&2
        exit 1
      }
    fi
    echo "[ok] Project installed successfully"
  fi
}

ensure_project_installed

# Auto-detect platform and install appropriate VLM inference engine
detect_and_install_vlm_engine() {
  local install_cmd=""

  if [[ -d ".venv" ]] && command -v uv &>/dev/null; then
    install_cmd="uv pip install"
  elif command -v pip &>/dev/null; then
    install_cmd="pip install"
  else
    install_cmd="python -m pip install"
  fi

  local python_version
  python_version=$(python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
  local python_minor
  python_minor=$(python -c "import sys; print(sys.version_info.minor)")

  local arch
  arch=$(uname -m)

  if [[ "$arch" == "arm64" ]] && [[ "$(uname -s)" == "Darwin" ]]; then
    if [[ "$python_minor" -ge 13 ]]; then
      echo "[warn] Python ${python_version} detected, but vllm-metal has issues with Python 3.13+"
      echo "[info] Recreating uv environment with Python 3.12..."
      rm -rf .venv
      uv venv --python 3.12 || {
        echo "[error] Failed to create uv environment with Python 3.12." >&2
        echo "        Please install Python 3.12 first: brew install python@3.12" >&2
        exit 1
      }
      source .venv/bin/activate
      python_version=$(python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
      python_minor=$(python -c "import sys; print(sys.version_info.minor)")
      install_cmd="uv pip install"
      echo "[ok] uv environment recreated with Python ${python_version}"
      echo "[info] Reinstalling project dependencies..."
      uv pip install -e "." || {
        echo "[error] Failed to install project dependencies." >&2
        exit 1
      }
      echo "[ok] Project dependencies installed"
    fi

    # Apple Silicon: use the MLX engine. vllm-metal has no Qwen2-VL multimodal
    # adapter, so the default MinerU model cannot run image inference under vLLM.
    local mlx_vlm_ok
    mlx_vlm_ok=$(python -c "
import importlib.util, importlib.metadata as m
from packaging.version import Version
if importlib.util.find_spec('mlx_vlm') is None:
    raise SystemExit(1)
v = Version(m.version('mlx-vlm'))
raise SystemExit(0 if Version('0.7.0') <= v < Version('0.8.0') else 1)
" 2>/dev/null && echo 1 || echo 0)

    if [[ "$mlx_vlm_ok" != "1" ]]; then
      echo "[info] Installing mlx-vlm 0.7.1 for Apple Silicon..."
      if ! $install_cmd "mlx-vlm==0.7.1"; then
        echo "[warn] Failed to install mlx-vlm. Install manually:" >&2
        echo "       $install_cmd mlx-vlm==0.7.1" >&2
      else
        echo "[ok] mlx-vlm installed successfully"
      fi
    fi
  elif command -v nvidia-smi &>/dev/null && nvidia-smi &>/dev/null; then
    if ! python -c "import vllm" 2>/dev/null; then
      echo "[info] Detected NVIDIA GPU (Python ${python_version}), installing vllm for VLM support..."
      $install_cmd vllm || {
        echo "[error] Failed to install vllm. VLM server will not work." >&2
        echo "        Please install manually: $install_cmd vllm" >&2
        exit 1
      }
      echo "[ok] vllm installed successfully"
    else
      echo "[info] vllm already installed"
    fi
  else
    if ! python -c "import vllm" 2>/dev/null && ! python -c "import lmdeploy" 2>/dev/null; then
      echo "[warn] No GPU detected (Python ${python_version}). Attempting to install vllm..."
      $install_cmd vllm || {
        echo "[warn] vllm installation failed, attempting lmdeploy..."
        $install_cmd lmdeploy || {
          echo "[warn] Both vllm and lmdeploy installation failed." >&2
          echo "       VLM server may not work. Install manually:" >&2
          echo "       - NVIDIA GPU: $install_cmd vllm" >&2
          echo "       - macOS/Other: $install_cmd lmdeploy" >&2
          return 0
        }
        echo "[ok] lmdeploy installed successfully"
      }
      echo "[ok] vllm installed successfully"
    fi
  fi
}

detect_and_install_vlm_engine

# Optional: use domestic model source by default.
export MINERU_MODEL_SOURCE="modelscope"

# Tunables for local startup
GPU_MEMORY_UTILIZATION="${MINERU_GPU_MEMORY_UTILIZATION:-0.4}"
DATA_PARALLEL_SIZE="${MINERU_DATA_PARALLEL_SIZE:-1}"
MAX_PAGES="${MINERU_MAX_PAGES:-}"

# VLM inference engine: auto, vllm, lmdeploy, mlx.
# On Apple Silicon, default to mlx: vllm-metal has no Qwen2-VL multimodal
# adapter, so the default MinerU model cannot run image inference under vLLM.
if [[ -n "${MINERU_VLM_ENGINE:-}" ]]; then
  VLM_ENGINE="$MINERU_VLM_ENGINE"
elif [[ "$(uname -m)" == "arm64" ]] && [[ "$(uname -s)" == "Darwin" ]]; then
  VLM_ENGINE="mlx"
else
  VLM_ENGINE="auto"
fi

# Preferred ports (8400-8499 range)
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
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("0.0.0.0", port))
    except OSError:
        sys.exit(1)
print(port)
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
    exit 1
  }

  if [[ "$selected_port" != "$preferred_port" ]]; then
    echo "[warn] ${service_name} preferred port :${preferred_port} is busy, using :${selected_port}" >&2
  fi

  echo "$selected_port"
}

build_vlm_server_args() {
  local port="$1"
  VLM_SERVER_ARGS=(--engine "$VLM_ENGINE" --host 0.0.0.0 --port "$port")
  # mlx-vlm's server does not accept vllm-specific scheduling flags.
  if [[ "$VLM_ENGINE" != "mlx" ]]; then
    VLM_SERVER_ARGS+=(--data-parallel-size "$DATA_PARALLEL_SIZE" --gpu-memory-utilization "$GPU_MEMORY_UTILIZATION")
  fi
}

start_gradio() {
  local selected_gradio_port
  selected_gradio_port="$(pick_port "$GRADIO_PORT" "gradio")"
  echo "[start] webui on :${selected_gradio_port}"
  webui_args=(--server-name 0.0.0.0 --server-port "$selected_gradio_port" --enable-api)
  if [[ -n "$MAX_PAGES" ]]; then
    webui_args+=(--max-pages "$MAX_PAGES")
  fi
  mineru-kit webui "${webui_args[@]}"
}

start_openai() {
  local selected_openai_port
  selected_openai_port="$(pick_port "$OPENAI_PORT" "openai")"
  echo "[start] openai server on :${selected_openai_port}"
  build_vlm_server_args "$selected_openai_port"
  mineru-kit vlm-server "${VLM_SERVER_ARGS[@]}"
}

print_usage() {
  echo "Usage: bash scripts/start_mineru_local.sh [gradio|api|openai|all]"
  echo ""
  echo "Modes:"
  echo "  gradio  - Start the Gradio web UI (mineru-kit webui; auto-starts a managed V1 API server)"
  echo "  api     - Start the VLM server and the V1 parse API server (the API server uses the local VLM server for Standard/Advanced)"
  echo "  openai  - Start the OpenAI-compatible VLM server (mineru-kit vlm-server)"
  echo "  all     - Start the VLM server and the web UI (the web UI manages its own V1 API server)"
}

if [[ "$MODE" == "--help" || "$MODE" == "-h" ]]; then
  print_usage
  exit 0
fi

echo "[info] working dir: $ROOT_DIR"
echo "[info] python: $(command -v python)"
echo "[info] model source: $MINERU_MODEL_SOURCE"
echo "[info] vlm-engine: $VLM_ENGINE"
echo "[info] gpu-memory-utilization: $GPU_MEMORY_UTILIZATION"
echo "[info] data-parallel-size: $DATA_PARALLEL_SIZE"

case "$MODE" in
  gradio)
    start_gradio
    ;;
  api)
    selected_openai_port="$(pick_port "$OPENAI_PORT" "openai")"
    selected_api_port="$(pick_port "$API_PORT" "api")"

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
    build_vlm_server_args "$selected_openai_port"
    mineru-kit vlm-server "${VLM_SERVER_ARGS[@]}" &
    pids+=("$!")

    # The API server uses the local VLM server for Standard/Advanced inference.
    echo "[start] api on :${selected_api_port} (VLM -> :${selected_openai_port})"
    mineru-kit api-server \
      --host 0.0.0.0 \
      --port "$selected_api_port" \
      --vlm-server-url "http://127.0.0.1:${selected_openai_port}/v1" &
    pids+=("$!")

    echo "[ok] started api + vlm services in foreground-managed mode"
    echo "[info] press Ctrl+C to stop all"

    wait
    ;;
  openai)
    start_openai
    ;;
  all)
    selected_openai_port="$(pick_port "$OPENAI_PORT" "openai")"
    selected_gradio_port="$(pick_port "$GRADIO_PORT" "gradio")"

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
    build_vlm_server_args "$selected_openai_port"
    mineru-kit vlm-server "${VLM_SERVER_ARGS[@]}" &
    pids+=("$!")

    # The web UI auto-starts its own managed V1 API server and uses the local
    # VLM server for Standard/Advanced inference.
    echo "[start] webui on :${selected_gradio_port}"
    webui_args=(--server-name 0.0.0.0 --server-port "$selected_gradio_port" --enable-api)
    if [[ -n "$MAX_PAGES" ]]; then
      webui_args+=(--max-pages "$MAX_PAGES")
    fi
    MINERU_MODEL_VLM_SERVER_URL="http://127.0.0.1:${selected_openai_port}/v1" \
      mineru-kit webui "${webui_args[@]}" &
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