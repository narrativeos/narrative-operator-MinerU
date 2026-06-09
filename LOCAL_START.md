# MinerU 本地启动说明

## Docker Compose 启动（推荐，支持 macOS / Linux）

### 基础镜像构建

```bash
docker compose build
```

### macOS / 无 GPU Linux

```bash
# 仅启动 Gradio（7860）
docker compose --profile gradio up -d

# 仅启动 API（8000）
docker compose --profile api up -d

# 仅启动 OpenAI Server（30000）
docker compose --profile openai-server up -d

# 停止
docker compose --profile gradio down
```

### Linux + NVIDIA GPU

```bash
# 合并 GPU 覆盖配置启动
docker compose -f docker-compose.yaml -f docker-compose.gpu.yml --profile gradio up -d
```

> **注意**：vllm 基础镜像约 1.5GB，首次构建需较长时间，建议在 GPU 服务器上执行。

---

## 本地脚本启动（非 Docker）

本文档用于快速在本地环境启动 MinerU（不使用容器），并使用一键脚本管理服务。

## 1. 前置条件

- 已在本机安装依赖（建议在 conda 环境）
- 当前目录位于仓库根目录：`/mnt/services/docker-compose/one-mineru`

建议安装方式：

```bash
conda activate mineru
pip install -U pip uv
uv pip install -e .[all]
```

可选（国内模型源）：

```bash
export MINERU_MODEL_SOURCE=modelscope
```

## 2. 一键启动脚本

已提供脚本：`scripts/start_mineru_local.sh`

查看帮助：

```bash
bash scripts/start_mineru_local.sh --help
```

支持模式：

- `gradio`：只启动 Gradio（7860）
- `api`：只启动 FastAPI（8000）
- `openai`：只启动 OpenAI-compatible server（30000）
- `all`：同时启动以上三个服务

脚本会优先使用上述端口；如果端口被占用，会在后续端口中自动寻找可用端口（默认最多向后扫描 20 个端口）。

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
export MINERU_HYBRID_BATCH_RATIO=1
export MINERU_ENABLE_GRADIO_UI_CACHE=true
export MINERU_ENABLE_API_CACHE=true
export MINERU_GRADIO_PORT=7861
export MINERU_API_PORT=8001
export MINERU_OPENAI_PORT=30001
export MINERU_PORT_SCAN_SPAN=50
bash scripts/start_mineru_local.sh gradio
```

说明：`start_mineru_local.sh` 默认会设置 `MINERU_HYBRID_BATCH_RATIO=1`（如未手动指定），以降低混合后端在共享 GPU 场景下的 OOM 概率。

缓存开关：

- `MINERU_ENABLE_GRADIO_UI_CACHE`：控制 Gradio 端结果缓存（默认 `true`）。
- `MINERU_ENABLE_API_CACHE`：控制 FastAPI 端解析结果缓存（默认 `true`）。

## 4. 停止方式

- 单服务模式（`gradio/api/openai`）：终端按 `Ctrl+C` 即可停止。
- `all` 模式：终端按 `Ctrl+C` 会同时停止三个子进程。

## 5. 访问地址

- Gradio: `http://127.0.0.1:<gradio_port>`
- FastAPI Docs: `http://127.0.0.1:<api_port>/docs`
- OpenAI-compatible health（示例）: `http://127.0.0.1:<openai_port>/health`

说明：实际端口以启动日志中的 `[start] ... on :<port>` 为准。

## 7. 说明

脚本内部使用 `python -m mineru.cli.*` 启动，因此即使 `mineru-gradio` 命令未加入 PATH，也可以正常运行。

如果你需要构建包含当前本地代码改动的 Docker 镜像（而不是安装已发布版本），请使用仓库根目录作为构建上下文：

```bash
# 构建镜像（使用 docker-compose）
docker compose build --no-cache

# 或手动 Docker 构建
docker build -f docker/china/Dockerfile -t narrativeos/mineru:latest .
docker build -f docker/global/Dockerfile -t narrativeos/mineru:latest .
```

Push 镜像：

```bash
docker push narrativeos/mineru:latest
```
```