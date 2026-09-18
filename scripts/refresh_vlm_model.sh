#!/usr/bin/env bash
set -euo pipefail

# Refresh a local MinerU model: stop the VLM server, delete the cached model
# directory (including the MLX "model.safetensors.orig" backup), and re-download
# it from the configured source.
#
# Why delete first: the MLX VLM model is converted in place on first load, which
# leaves a redundant "model.safetensors.orig" backup and a rewritten
# "model.safetensors". When the upstream model is updated, a plain re-download
# may not cleanly restore the original weights, so this script removes the whole
# model directory and downloads a fresh copy. The MLX config patch is re-applied
# automatically the next time the VLM server starts.
#
# Usage:
#   bash scripts/refresh_vlm_model.sh [repo] [--restart] [--no-stop] [--dry-run]
#
# Arguments:
#   repo          Model repo to refresh (default: MinerU2.5-Pro-2605-1.2B)
#
# Options:
#   --restart     After refreshing, (re)start the VLM server (openai mode)
#   --no-stop     Do not stop a running VLM server before deleting
#   --dry-run     Print the plan (stop/delete/download) without making changes
#   -h, --help    Show this help
#
# Model source: MINERU_MODEL_SOURCE (default: modelscope), same as start script.

print_help() {
  cat <<'EOF'
Usage: bash scripts/refresh_vlm_model.sh [repo] [--restart] [--no-stop] [--dry-run]

Refresh a local MinerU model: stop the VLM server, delete the cached model
directory (including the MLX "model.safetensors.orig" backup), and re-download
it from the configured source.

Arguments:
  repo          Model repo to refresh (default: MinerU2.5-Pro-2605-1.2B)

Options:
  --restart     After refreshing, (re)start the VLM server (openai mode)
  --no-stop     Do not stop a running VLM server before deleting
  --dry-run     Print the plan (stop/delete/download) without making changes
  -h, --help    Show this help

Model source: MINERU_MODEL_SOURCE (default: modelscope), same as start script.

Examples:
  bash scripts/refresh_vlm_model.sh
  bash scripts/refresh_vlm_model.sh --restart
  bash scripts/refresh_vlm_model.sh --dry-run
  bash scripts/refresh_vlm_model.sh MinerU-4_models_torch
EOF
}

REPO="MinerU2.5-Pro-2605-1.2B"
REPO_GIVEN=false
RESTART=false
STOP_SERVER=true
DRY_RUN=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --restart) RESTART=true; shift ;;
    --no-stop) STOP_SERVER=false; shift ;;
    --dry-run) DRY_RUN=true; shift ;;
    -h|--help) print_help; exit 0 ;;
    -*)
      echo "[error] unknown option: $1" >&2
      print_help >&2
      exit 1
      ;;
    *)
      if [[ "$REPO_GIVEN" == "true" ]]; then
        echo "[error] unexpected argument: $1 (only one repo is allowed)" >&2
        exit 1
      fi
      REPO="$1"
      REPO_GIVEN=true
      shift
      ;;
  esac
done

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

# Activate the uv virtual environment (mirrors start_mineru_local.sh).
if [[ -d ".venv" ]]; then
  source .venv/bin/activate
elif command -v uv &>/dev/null; then
  echo "[info] creating uv environment..."
  uv venv
  source .venv/bin/activate
fi

# Model source: default to ModelScope, matching start_mineru_local.sh.
export MINERU_MODEL_SOURCE="${MINERU_MODEL_SOURCE:-modelscope}"

if ! command -v mineru-kit &>/dev/null; then
  echo "[error] mineru-kit not found. Activate the project venv or install it: uv pip install -e ." >&2
  exit 1
fi

# Resolve the model directory through the registry so we never hardcode a path.
resolve_model_dir() {
  python - "$1" <<'PY'
import sys
from mineru.model.registry import get_model_repo
print(get_model_repo(sys.argv[1]).local_dir())
PY
}

if ! MODEL_DIR="$(resolve_model_dir "$REPO" 2>&1)"; then
  echo "[error] cannot resolve model dir for repo '$REPO'." >&2
  echo "        $MODEL_DIR" >&2
  exit 1
fi

echo "[info] repo: $REPO"
echo "[info] model dir: $MODEL_DIR"
echo "[info] model source: $MINERU_MODEL_SOURCE"

# Dry-run: print the plan and exit without making any changes.
if [[ "$DRY_RUN" == "true" ]]; then
  dry_pids="$(pgrep -f "mineru-kit vlm-server" 2>/dev/null || true)"
  if [[ -n "$dry_pids" ]]; then
    echo "[dry-run] would stop VLM server (pids: $(echo "$dry_pids" | tr '\n' ' '))"
  else
    echo "[dry-run] no running VLM server to stop"
  fi
  if [[ -d "$MODEL_DIR" ]]; then
    echo "[dry-run] would delete: $MODEL_DIR ($(du -sh "$MODEL_DIR" 2>/dev/null | cut -f1))"
  else
    echo "[dry-run] $MODEL_DIR does not exist (nothing to delete)"
  fi
  echo "[dry-run] would run: mineru-kit models download $REPO"
  echo "[dry-run] no changes made"
  exit 0
fi

# Best-effort stop of the VLM server, which holds the VLM model in memory.
stop_vlm_server() {
  # Match the VLM server subcommand specifically. The api-server command line
  # contains "--vlm-server-url", so a bare "vlm-server" pattern would over-match.
  local pattern="mineru-kit vlm-server"
  local pids
  pids="$(pgrep -f "$pattern" 2>/dev/null || true)"
  if [[ -z "$pids" ]]; then
    echo "[info] no running VLM server found"
    return 0
  fi
  echo "[info] stopping VLM server (pids: $(echo "$pids" | tr '\n' ' '))"
  # shellcheck disable=SC2086
  kill $pids 2>/dev/null || true
  local i
  for i in 1 2 3 4 5 6 7 8 9 10; do
    if [[ -z "$(pgrep -f "$pattern" 2>/dev/null || true)" ]]; then
      break
    fi
    sleep 1
  done
  pids="$(pgrep -f "$pattern" 2>/dev/null || true)"
  if [[ -n "$pids" ]]; then
    echo "[warn] VLM server did not stop in time; sending SIGKILL"
    # shellcheck disable=SC2086
    kill -9 $pids 2>/dev/null || true
  fi
  echo "[ok] VLM server stopped"
}

if [[ "$STOP_SERVER" == "true" ]]; then
  stop_vlm_server
else
  echo "[info] skipping VLM server stop (--no-stop)"
fi

# Delete the cached model directory (removes the MLX .orig backup too).
if [[ -d "$MODEL_DIR" ]]; then
  echo "[info] deleting $MODEL_DIR"
  rm -rf "$MODEL_DIR"
else
  echo "[info] $MODEL_DIR does not exist; nothing to delete"
fi

# Re-download a fresh copy.
echo "[info] re-downloading $REPO (source: $MINERU_MODEL_SOURCE)..."
if ! mineru-kit models download "$REPO"; then
  echo "[error] failed to download $REPO (source: $MINERU_MODEL_SOURCE)" >&2
  exit 1
fi
echo "[ok] $REPO refreshed"

if [[ -d "$MODEL_DIR" ]]; then
  echo "[info] new model size: $(du -sh "$MODEL_DIR" 2>/dev/null | cut -f1)"
fi

# Optionally (re)start the VLM server in the foreground.
if [[ "$RESTART" == "true" ]]; then
  echo "[info] (re)starting VLM server via start_mineru_local.sh openai"
  exec bash "$ROOT_DIR/scripts/start_mineru_local.sh" openai
fi

echo "[ok] done. Start the server with: bash scripts/start_mineru_local.sh <mode>"
