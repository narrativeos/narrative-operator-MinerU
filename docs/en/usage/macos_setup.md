# macOS Deployment Guide

> **Important**: MinerU officially states that Docker deployment is not suitable for macOS. This guide provides the best deployment options for macOS.

## System Requirements

- **Operating System**: macOS 14.0 or later
- **Chip**: Apple Silicon (M1/M2/M3 series) recommended, Intel Mac also supported
- **Memory**: Minimum 16GB, 32GB+ recommended
- **Disk Space**: 20GB+ (SSD recommended)
- **Python Version**: 3.10-3.13

## Recommended Solution: LM Studio + http-client Backend

This solution uses local LM Studio to provide an OpenAI-compatible VLM inference service, combined with MinerU's `http-client` backend, achieving the best parsing accuracy (95+ score) on macOS.

### Step 1: Install LM Studio

1. Visit https://lmstudio.ai/ to download and install LM Studio
2. Launch LM Studio
3. Search and download supported VLM models:
   - Recommended models: `Qwen2.5-VL-7B-Instruct`, `Qwen2-VL-7B-Instruct`, or other vision-language models
   - Download models in the "My Models" tab
4. Load the model:
   - Select the downloaded model on the left
   - Click "Load" to load the model into memory
5. Start the local server:
   - Go to the "Local Server" tab
   - Click "Start Server" to launch the OpenAI-compatible server
   - Default port is `1234`, can be changed in settings

### Step 2: Install MinerU

```bash
# Upgrade pip and install uv
pip install --upgrade pip -i https://mirrors.aliyun.com/pypi/simple
pip install uv -i https://mirrors.aliyun.com/pypi/simple

# Install MinerU full version (including torch and other dependencies)
uv pip install -U "mineru[all]" -i https://mirrors.aliyun.com/pypi/simple
```

> **Note**: `hybrid-http-client` requires locally installing `mineru[all]` to provide pipeline dependencies (torch, opencv, etc.). Apple Silicon (M1/M2/M3) will automatically use MPS (Metal Performance Shaders) to accelerate pipeline computations.

### Step 3: Configure Model Source (Optional, recommended for China)

```bash
# Use ModelScope as model source (faster access in China)
export MINERU_MODEL_SOURCE=modelscope
```

### Step 4: Check if LM Studio is Running

```bash
# Use script to check LM Studio
bash scripts/start_mineru_local.sh check-lm-studio

# Custom port
export LM_STUDIO_PORT=1234
bash scripts/start_mineru_local.sh check-lm-studio
```

### Step 5: One-Click Start MinerU Services

```bash
# One-click start all services (automatically checks LM Studio)
bash scripts/start_mineru_local.sh start
```

After starting, you can check service status:

```bash
# Check service status
bash scripts/start_mineru_local.sh status
```

Example output:
```
[info] MinerU Service Status:
┌─────────────────────────────────────────────────────────────────┐
│  LM Studio              : ✓ (port 1234)                         │
│  MinerU API             : ✓ (port 8000)                         │
│  MinerU Gradio          : ✓ (port 7860)                         │
│  MinerU OpenAI          : ✗ (port 30000)                        │
└─────────────────────────────────────────────────────────────────┘
```

**Common Commands:**

| Command | Description |
|---------|-------------|
| `bash scripts/start_mineru_local.sh start` | One-click start all services |
| `bash scripts/start_mineru_local.sh stop` | Stop all services |
| `bash scripts/start_mineru_local.sh status` | Check service status |

### Step 6: Use http-client Backend for Document Parsing

```bash
# High-accuracy hybrid mode (recommended, requires local pipeline dependencies)
mineru -p <input_path> -o <output_path> -b hybrid-http-client -u http://127.0.0.1:1234

# Lightweight remote mode (no local torch required, Chinese and English only)
mineru -p <input_path> -o <output_path> -b vlm-http-client -u http://127.0.0.1:1234
```

## Backend Selection Guide

| Backend | Accuracy | Local Dependencies | Use Case |
|---------|----------|-------------------|----------|
| `hybrid-http-client` | 95+ (High) | Requires mineru[all] + torch | Multi-language support, best accuracy |
| `vlm-http-client` | 95+ (High) | **No torch required** | Edge devices, Chinese/English only |
| `pipeline` | 85+ | Requires mineru[pipeline] | Pure CPU, no additional services |

### hybrid-http-client vs vlm-http-client Selection Guide

- **Choose `hybrid-http-client`**:
  - Need multi-language support (Chinese, English, Japanese, Korean, etc.)
  - Pursue best parsing accuracy
  - Device meets mineru[all] installation requirements

- **Choose `vlm-http-client`**:
  - Only need Chinese and English support
  - Limited device resources, cannot install torch
  - Edge device deployment

### VLM Backend Modes Architecture

MinerU supports two VLM backend modes. Understanding their differences is crucial for proper configuration:

#### 1. `hybrid-http-client` Backend (Hybrid Mode)

```
┌─────────────────────────────────────────────────────────────────┐
│                        hybrid-http-client                       │
│                                                                 │
│   MinerU API                                                    │
│   ├── Local MinerU Model (MinerU2.5-Pro)                        │
│   │    ├── Layout Analysis                                      │
│   │    ├── OCR Text Recognition                                 │
│   │    ├── Formula Recognition                                  │
│   │    └── Table Recognition                                    │
│   │         ↓ When complex pages need VLM assistance            │
│   └──→ LM Studio (http://127.0.0.1:1234)                       │
│         └── VLM Model (e.g., Qwen2.5-VL-7B)                    │
│                                                                 │
│   Features:                                                     │
│   - Local Model: MinerU2.5-Pro (auto-downloaded)                │
│   - Inference Engine: mlx-engine (Apple Silicon GPU acceleration)│
│   - LM Studio: Assists with complex page analysis               │
│   - Accuracy: Highest (95+)                                     │
│   - Memory: Higher (loads both local model + LM Studio model)   │
└─────────────────────────────────────────────────────────────────┘
```

**Workflow:**
1. MinerU loads local model (MinerU2.5-Pro), using mlx-engine for Apple Silicon acceleration
2. For standard pages, local model independently completes layout analysis, OCR, formula/table recognition
3. For complex pages (charts, special layouts), calls LM Studio's VLM model for assistance
4. Merges results from local model and VLM, outputs final parsing result

#### 2. `vlm-http-client` Backend (Pure Remote Mode)

```
┌─────────────────────────────────────────────────────────────────┐
│                      vlm-http-client                            │
│                                                                 │
│   MinerU API                                                    │
│   └──→ LM Studio (http://127.0.0.1:1234)                       │
│         └── VLM Model (e.g., Qwen2.5-VL-7B)                    │
│                                                                 │
│   Features:                                                     │
│   - Local Model: Not used                                        │
│   - Inference Engine: Fully relies on LM Studio                 │
│   - Memory: Lower (only needs LM Studio model)                  │
│   - Accuracy: High (95+)                                         │
│   - Limitation: Chinese and English only                        │
└─────────────────────────────────────────────────────────────────┘
```

**Workflow:**
1. MinerU does not load any local models
2. All page analysis requests are sent directly to LM Studio
3. LM Studio's VLM model independently completes all analysis tasks
4. Returns results to MinerU for post-processing

#### Model Location Comparison

| Component | hybrid-http-client | vlm-http-client |
|-----------|-------------------|-----------------|
| MinerU2.5-Pro Model | ✅ Driven by MinerU code (mlx-engine) | ❌ Not loaded |
| LM Studio Model | ✅ Driven by LM Studio (assistance) | ✅ Driven by LM Studio (primary) |
| Model Download Location | `~/.cache/modelscope/hub/models/OpenDataLab/MinerU2.5-Pro-*` | N/A |
| GPU Acceleration | Apple Silicon MPS (mlx-engine) | Managed by LM Studio |

> **Important Note**: The MinerU2.5-Pro model is **driven by MinerU code**, using `mlx-engine` on Apple Silicon. The LM Studio model is **driven by LM Studio software**. They are independent models running in separate processes.

## Alternative Solution: Pure CPU Operation

If you don't want to install LM Studio, you can use the `pipeline` backend to run in a pure CPU environment:

```bash
# Install MinerU
uv pip install -U "mineru[all]" -i https://mirrors.aliyun.com/pypi/simple

# Use pipeline backend (pure CPU)
mineru -p <input_path> -o <output_path> -b pipeline
```

> **Note**: The `pipeline` backend has an accuracy of about 85+, suitable for scenarios with low accuracy requirements or quick testing.

## Environment Variables Configuration

```bash
# Model source configuration (recommended for China)
export MINERU_MODEL_SOURCE=modelscope

# LM Studio port (optional, default 1234)
export LM_STUDIO_PORT=1234

# GPU memory utilization (Apple Silicon can be lowered to avoid memory pressure)
export MINERU_GPU_MEMORY_UTILIZATION=0.35

# Batch processing configuration
export MINERU_HYBRID_BATCH_RATIO=1

# Cache configuration
export MINERU_ENABLE_GRADIO_UI_CACHE=true
export MINERU_ENABLE_API_CACHE=true
```

## Frequently Asked Questions

### Q1: LM Studio cannot start server

**Solution**:
1. Ensure a model is loaded (select model in "My Models" and click Load)
2. Check if port is occupied (default 1234)
3. Try changing port: modify port number in LM Studio settings

### Q2: Parsing is slow

**Solution**:
1. Adjust `MINERU_GPU_MEMORY_UTILIZATION` parameter (default 0.4, can be increased)
2. Ensure MPS acceleration with Apple Silicon chip
3. Reduce number of concurrent tasks

### Q3: Insufficient memory

**Solution**:
1. Lower `MINERU_GPU_MEMORY_UTILIZATION` to 0.2-0.3
2. Set `MINERU_HYBRID_BATCH_RATIO=1`
3. Close other memory-intensive applications
4. Consider using `vlm-http-client` backend to reduce local memory usage

### Q4: Cannot access ModelScope

**Solution**:
1. Check network connection
2. Try switching to huggingface: `export MINERU_MODEL_SOURCE=huggingface`
3. Or use local models: `export MINERU_MODEL_SOURCE=local`

### Q5: Does Intel Mac support GPU acceleration?

**Answer**: Intel Mac does not support MPS acceleration, can only run on CPU. Recommended to use `pipeline` backend or `http-client` backend with LM Studio.

## Performance Optimization Tips

1. **Use Apple Silicon**: M1/M2/M3 series chips support MPS acceleration, significantly outperforming Intel
2. **Adjust memory utilization**: Adjust `MINERU_GPU_MEMORY_UTILIZATION` based on device memory
3. **Enable caching**: Set `MINERU_ENABLE_API_CACHE=true` to avoid duplicate parsing
4. **Batch processing**: Use directory as input to process multiple files at once

## Service Management

### Start Services

```bash
# One-click start (recommended)
bash scripts/start_mineru_local.sh start
```

### Check Status

```bash
bash scripts/start_mineru_local.sh status
```

### Stop Services

```bash
bash scripts/start_mineru_local.sh stop
```

## Related Documentation

- [Quick Start](../quick_start/index.md)
- [Command Line Tools](./cli_tools.md)
- [FAQ](../faq/index.md)
