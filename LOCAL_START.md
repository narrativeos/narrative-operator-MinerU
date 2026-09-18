# MinerU 本地启动说明

## 本地脚本启动（非 Docker）

本文档用于快速在本地环境启动 MinerU（不使用容器），并使用一键脚本管理服务。

## 1. 前置条件

- 已在本机安装依赖（建议使用 uv 管理的 `.venv` 环境）
- 当前目录位于仓库根目录

建议安装方式：

```bash
uv venv .venv
source .venv/bin/activate
uv pip install -e ".[all]"
```

模型源：脚本默认使用 ModelScope（国内镜像）。如需改用其他源，在运行脚本前
预先设置 `MINERU_MODEL_SOURCE`（可选值：`auto` / `huggingface` / `modelscope` / `local`）：

```bash
export MINERU_MODEL_SOURCE=huggingface   # 例如改用 Hugging Face
```

## 2. 一键启动脚本

已提供脚本：`scripts/start_mineru_local.sh`

查看帮助：

```bash
bash scripts/start_mineru_local.sh --help
```

支持模式（4.0 起统一通过 `mineru-kit` 子命令启动）：

- `gradio`：启动 `mineru-kit webui`（默认 8400），自动托管一个本地 V1 API server
- `api`：同时启动 VLM 服务和 `mineru-kit api-server` 自托管 V1 解析 API（默认 8401）；api-server 通过 `--vlm-server-url` 使用本地 VLM 服务执行 Standard/Advanced 推理
- `openai`：启动 `mineru-kit vlm-server` OpenAI 兼容 VLM 服务（默认 8402）
- `all`：同时启动 VLM 服务和 webui；webui 自托管 V1 API server，并通过
  `MINERU_MODEL_VLM_SERVER_URL` 使用本地 VLM 服务执行 Standard/Advanced 推理

脚本会优先使用上述端口；如果端口被占用，会在后续端口中自动寻找可用端口（默认最多向后扫描 98 个端口）。

首次运行 Standard/Advanced 相关服务时会按当前模型源自动下载所需模型（VLM 权重约 2.15 GB），也可提前执行 `mineru-kit models download --tier standard` 完成下载。

### macOS 上的 VLM 引擎（mlx）

在 Apple Silicon 上，脚本默认以 `--engine mlx` 启动 `vlm-server`（可用 `MINERU_VLM_ENGINE` 覆盖）。原因：

- `api` / `all` / `openai` 模式依赖**独立 VLM 服务**（OpenAI 兼容端点）。`vlm-server` 只支持 `vllm` / `lmdeploy` / `mlx`，**没有 llama.cpp 独立服务**。
- macOS 上 `vllm-metal` 无 Qwen2-VL 多模态支持，`lmdeploy` 非 macOS 目标路径，因此 **mlx 是该形态下唯一可用的引擎**（全精度权重，需 `mlx-vlm>=0.7.0,<0.8.0`，脚本自动安装）。
- `llama.cpp`（Q8_0 量化）是 upstream 的 macOS 默认，但只能**内联**运行（`api-server` 不传 `--vlm-server-url` 时），无法提供独立服务，故不用于 `api` 模式。

选型对比与决策背景见 [ADR-0035](docs/next/decisions/0035-macos-vlm-engine-mlx.md)。

## 3. 常用启动命令

只启动 Gradio：

```bash
bash scripts/start_mineru_local.sh gradio
```

只启动 API：

```bash
bash scripts/start_mineru_local.sh api
```

同时启动全部服务：

```bash
bash scripts/start_mineru_local.sh all
```

如果显存紧张或端口冲突频繁，可在启动前设置环境变量：

```bash
export MINERU_GPU_MEMORY_UTILIZATION=0.35
export MINERU_DATA_PARALLEL_SIZE=1
export MINERU_MAX_PAGES=200
export MINERU_GRADIO_PORT=8403
export MINERU_API_PORT=8404
export MINERU_OPENAI_PORT=8405
export MINERU_PORT_SCAN_SPAN=50
bash scripts/start_mineru_local.sh gradio
```

说明：

- `MINERU_GPU_MEMORY_UTILIZATION` / `MINERU_DATA_PARALLEL_SIZE` 只作用于 `vlm-server`（透传给 vLLM）。
- `MINERU_MAX_PAGES` 可选，限制 webui 单次非 Flash PDF 解析的最多页数（对应 `mineru-kit webui --max-pages`），不设置则不限制。
- 模型源、小模型后端与 VLM 引擎等配置见 `config.yaml`（默认 `~/.mineru/config.yaml`）或 `MINERU_MODEL_*` 环境变量，详见文档《模型下载与配置》。

## 4. 停止方式

- 单服务模式（`gradio/openai`）：终端按 `Ctrl+C` 即可停止。
- `api` 模式：终端按 `Ctrl+C` 会同时停止 VLM 服务与 api-server。
- `all` 模式：终端按 `Ctrl+C` 会同时停止 VLM 服务与 webui（含 webui 托管的 V1 API server）。

## 5. 访问地址

- Web UI（Gradio）: `http://127.0.0.1:<gradio_port>`
- V1 解析 API health: `http://127.0.0.1:<api_port>/v1/health`
- V1 解析 API 能力发现: `http://127.0.0.1:<api_port>/v1/tiers`
- OpenAI 兼容 VLM 服务（示例）: `http://127.0.0.1:<openai_port>/v1/models`

说明：

- 实际端口以启动日志中的 `[start] ... on :<port>` 为准。
- `gradio` / `all` 模式下 webui 托管的 V1 API server 使用自动选择的 loopback 端口，以 webui 启动日志为准，不与 `MINERU_API_PORT` 混用。

## 6. 说明

脚本内部使用 `mineru-kit` 子命令（`webui` / `api-server` / `vlm-server`）启动，因此要求项目已安装到当前环境（脚本会自动检测并安装缺失依赖）。