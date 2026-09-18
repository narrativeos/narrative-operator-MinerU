# macOS Deployment Guide

> **Important**: MinerU officially states that Docker deployment is not suitable for macOS. This guide provides the best deployment options for macOS (MinerU 4.0).

## System Requirements

- **Operating System**: macOS 14.0 or later
- **Chip**: Apple Silicon (M1/M2/M3 series) recommended, Intel Mac also supported
- **Memory**: Minimum 16GB, 32GB+ recommended
- **Disk Space**: 20GB+ (SSD recommended)
- **Python Version**: 3.10-3.13

## 4.0 Architecture Overview

MinerU 4.0 has two inference paths on macOS:

1. **Local engines (recommended)**: small models (ONNX/Torch) + a local VLM engine
   (on Apple Silicon, `auto` defaults to llama.cpp; `mlx` can be selected explicitly).
   No external service is required; models are downloaded automatically per tier
   (Basic needs only the small-model package, Standard also needs the VLM model).
2. **Remote VLM service (optional)**: use an OpenAI-compatible service such as
   LM Studio for VLM inference, configured via `model.vlm.server_url`. Small models
   still run locally according to the selected tier.

Parsing tiers: `flash` (plain text extraction, no models), `basic` (small models),
`standard` / `advanced` (small models + VLM).

## Step 1: Install MinerU

```bash
# Upgrade pip and install uv
pip install --upgrade pip -i https://mirrors.aliyun.com/pypi/simple
pip install uv -i https://mirrors.aliyun.com/pypi/simple

# Install MinerU full version (including torch and other dependencies)
uv pip install -U "mineru[all]" -i https://mirrors.aliyun.com/pypi/simple
```

> **Note**: Standard/Advanced tiers require local small-model dependencies (torch,
> opencv, etc.), provided by `mineru[all]`. Apple Silicon automatically uses MPS
> (Metal Performance Shaders) for acceleration.

## Step 2: Configure Model Source (Optional, recommended for China)

```bash
# Use ModelScope as model source (faster access in China)
export MINERU_MODEL_SOURCE=modelscope
```

See [Model Download and Configuration](./model_source.md) for downloading,
checking, and offline usage.

## Step 3 (Optional): Use LM Studio as a Remote VLM Service

If you don't want to run a local VLM engine, you can use LM Studio to provide an
OpenAI-compatible VLM inference service:

1. Visit https://lmstudio.ai/ to download and install LM Studio
2. Search and download a supported VLM model (e.g. `Qwen2.5-VL-7B-Instruct` or
   other vision-language models)
3. After loading the model, start the OpenAI-compatible server in the
   "Local Server" tab (default port `1234`)
4. Point MinerU at the service (environment variable or the `model.vlm` fields
   in `config.yaml`):

```bash
export MINERU_MODEL_VLM_SERVER_URL=http://127.0.0.1:1234/v1
# If the model name exposed by LM Studio doesn't match auto-discovery, set it explicitly:
export MINERU_MODEL_VLM_MODEL=<model name in LM Studio>
```

> **Note**: `model.vlm.server_url` is a model inference endpoint, not the MinerU
> V1 document parsing API. Once configured, Standard/Advanced VLM inference goes
> through LM Studio while small models still run locally. See
> [Model Download and Configuration](./model_source.md#remote-vlm-service) for
> the full field reference.

## Step 4: Start Services

One-click script modes (4.0 launches everything through `mineru-kit` subcommands):

| Command | Description |
|---------|-------------|
| `bash scripts/start_mineru_local.sh gradio` | Start the Web UI (`mineru-kit webui`, default 8400, auto-manages its own V1 API server) |
| `bash scripts/start_mineru_local.sh api` | Start the V1 parsing API (`mineru-kit api-server`, default 8401) |
| `bash scripts/start_mineru_local.sh openai` | Start the OpenAI-compatible VLM service (`mineru-kit vlm-server`, default 8402) |
| `bash scripts/start_mineru_local.sh all` | Start the VLM service and the Web UI together |

When a port is occupied the script automatically picks the next free port; the
actual port is shown in the startup log as `[start] ... on :<port>`. See
`LOCAL_START.md` in the repository root for details.

## Step 5: Parse Documents

```bash
# Standard tier (small models + VLM, recommended)
mineru-kit parse <input_path> -o <output_path> --tier standard

# Basic tier (small models only, runs on CPU)
mineru-kit parse <input_path> -o <output_path> --tier basic

# Flash tier (plain text extraction, no models)
mineru-kit parse <input_path> -o <output_path> --tier flash
```

## Tier Selection Guide

| Tier | Model Dependencies | Use Case |
|------|--------------------|----------|
| `flash` | None | Plain text extraction, quick preview |
| `basic` | Small-model package | Runs on CPU, everyday documents |
| `standard` / `advanced` | Small-model package + VLM model (or a remote VLM service) | Complex layouts, formulas, tables; best accuracy |

### Local Engines vs Remote VLM Service

- **Choose local engines (default)**:
  - No extra service required, works out of the box
  - On Apple Silicon, `auto` defaults to llama.cpp (CPU inference); `mlx` can be
    selected explicitly (requires `mlx-vlm`)
  - Models are downloaded automatically per tier on first run

- **Choose a remote VLM service (LM Studio)**:
  - Limited local memory to host both small models and a VLM
  - You want to reuse a model already loaded in LM Studio
  - Note: small models still run locally according to the tier; `server_url`
    only replaces VLM inference

## Alternative: CPU-Only Operation

If you don't want to run a VLM at all, use the `basic` tier (small models only),
which runs comfortably on CPU:

```bash
mineru-kit parse <input_path> -o <output_path> --tier basic
```

> **Note**: `basic` trades some accuracy on complex layouts for low resource
> usage. Use `standard`/`advanced` (local VLM engine or a remote VLM service)
> when accuracy matters.

## Environment Variables Configuration

```bash
# Model source configuration (recommended for China)
export MINERU_MODEL_SOURCE=modelscope

# Remote VLM service (optional, e.g. LM Studio)
export MINERU_MODEL_VLM_SERVER_URL=http://127.0.0.1:1234/v1

# Local VLM engine (optional: auto/llama-cpp/vllm/lmdeploy/mlx; MLX is explicit-only)
export MINERU_MODEL_VLM_ENGINE=auto

# Small-model backend (optional: auto/onnx/torch)
export MINERU_MODEL_SMALL_BACKEND=auto
```

## Frequently Asked Questions

### Q1: LM Studio cannot start server

**Solution**:
1. Ensure a model is loaded (select model in "My Models" and click Load)
2. Check if port is occupied (default 1234)
3. Try changing port: modify port number in LM Studio settings, and update
   `MINERU_MODEL_VLM_SERVER_URL` accordingly

### Q2: Parsing is slow

**Solution**:
1. Ensure MPS acceleration with an Apple Silicon chip
2. Select the `mlx` engine explicitly (requires `mlx-vlm>=0.7.0,<0.8.0`):
   `export MINERU_MODEL_VLM_ENGINE=mlx`
3. Reduce number of concurrent tasks

### Q3: Insufficient memory

**Solution**:
1. Close other memory-intensive applications
2. Use a remote VLM service (LM Studio) for VLM inference to reduce local memory usage
3. Use the `basic` tier (no VLM loaded)

### Q4: Cannot access ModelScope

**Solution**:
1. Check network connection
2. Try switching to huggingface: `export MINERU_MODEL_SOURCE=huggingface`
3. Or use local models: `export MINERU_MODEL_SOURCE=local` (models must be downloaded first)

### Q5: Does Intel Mac support GPU acceleration?

**Answer**: Intel Mac does not support MPS acceleration and can only run on CPU.
Use the `basic` tier, or combine a remote VLM service (LM Studio) with the
`standard` tier.

## Performance Optimization Tips

1. **Use Apple Silicon**: M1/M2/M3 series chips support MPS acceleration, significantly outperforming Intel
2. **Pick the right tier**: use `basic` for everyday documents, `standard`/`advanced` for complex ones
3. **Batch processing**: Use a directory as input to process multiple files at once

## Service Management

### Start Services

```bash
# One-click start (recommended)
bash scripts/start_mineru_local.sh all
```

### Stop Services

- Single-service modes (`gradio/api/openai`): press `Ctrl+C` in the terminal.
- `all` mode: `Ctrl+C` stops all child processes together.

## Related Documentation

- [Quick Start](../quick_start/index.md)
- [Command Line Tools](./cli_tools.md)
- [FAQ](../faq/index.md)
