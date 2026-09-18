# macOS 部署指南

> **重要提示**：MinerU 官方明确说明 Docker 部署不适用于 macOS。本指南提供 macOS 上的最佳部署方案（MinerU 4.0）。

## 系统要求

- **操作系统**：macOS 14.0 或以上版本
- **芯片**：Apple Silicon (M1/M2/M3 系列) 推荐，Intel Mac 也支持
- **内存**：最低 16GB，推荐 32GB 以上
- **磁盘空间**：20GB 以上（推荐使用 SSD）
- **Python 版本**：3.10-3.13

## 4.0 架构概览

MinerU 4.0 在 macOS 上有两条推理路径：

1. **本地引擎（推荐）**：小模型（ONNX/Torch）+ 本地 VLM 引擎（Apple Silicon 上
   `auto` 默认选择 llama.cpp，也可显式选择 `mlx`）。无需任何外部服务，
   模型按档位自动下载（Basic 只需小模型包，Standard 还需要 VLM 模型）。
2. **远程 VLM 服务（可选）**：用 LM Studio 等 OpenAI 兼容服务承载 VLM 推理，
   通过 `model.vlm.server_url` 配置。小模型仍由所选档位决定，本地照常运行。

解析档位（tier）：`flash`（纯文本提取，无模型）、`basic`（小模型）、
`standard` / `advanced`（小模型 + VLM）。

## 第一步：安装 MinerU

```bash
# 升级 pip 并安装 uv
pip install --upgrade pip -i https://mirrors.aliyun.com/pypi/simple
pip install uv -i https://mirrors.aliyun.com/pypi/simple

# 安装 MinerU 完整版本（包括 torch 等依赖）
uv pip install -U "mineru[all]" -i https://mirrors.aliyun.com/pypi/simple
```

> **注意**：Standard/Advanced 档位需要本地小模型依赖（torch、opencv 等），
> 由 `mineru[all]` 提供。Apple Silicon 会自动使用 MPS (Metal Performance Shaders) 加速。

## 第二步：配置模型源（可选，国内推荐）

```bash
# 使用 ModelScope 作为模型源（国内访问更快）
export MINERU_MODEL_SOURCE=modelscope
```

模型下载、检查与离线使用见[模型下载与配置](./model_source.md)。

## 第三步（可选）：使用 LM Studio 作为远程 VLM 服务

如果不想在本地运行 VLM 引擎，可以用 LM Studio 提供 OpenAI 兼容的 VLM 推理服务：

1. 访问 https://lmstudio.ai/ 下载并安装 LM Studio
2. 搜索并下载支持的 VLM 模型（如 `Qwen2.5-VL-7B-Instruct` 或其他支持视觉语言的模型）
3. 加载模型后，在 "Local Server" 标签页启动 OpenAI 兼容服务器（默认端口 `1234`）
4. 将 MinerU 指向该服务（环境变量或 `config.yaml` 的 `model.vlm` 字段）：

```bash
export MINERU_MODEL_VLM_SERVER_URL=http://127.0.0.1:1234/v1
# 如 LM Studio 服务暴露的模型名与自动发现不一致，可显式指定：
export MINERU_MODEL_VLM_MODEL=<LM Studio 中的模型名>
```

> **注意**：`model.vlm.server_url` 是模型推理接口，不是 MinerU V1 文档解析 API；
> 配置后 Standard/Advanced 的 VLM 推理走 LM Studio，小模型仍在本地运行。
> 完整字段说明见[模型下载与配置](./model_source.md#远程-vlm-服务)。

## 第四步：启动服务

一键脚本支持的模式（4.0 起统一通过 `mineru-kit` 子命令启动）：

| 命令 | 说明 |
|------|------|
| `bash scripts/start_mineru_local.sh gradio` | 启动 Web UI（`mineru-kit webui`，默认 8400，自动托管 V1 API server） |
| `bash scripts/start_mineru_local.sh api` | 启动 V1 解析 API（`mineru-kit api-server`，默认 8401） |
| `bash scripts/start_mineru_local.sh openai` | 启动 OpenAI 兼容 VLM 服务（`mineru-kit vlm-server`，默认 8402） |
| `bash scripts/start_mineru_local.sh all` | 同时启动 VLM 服务与 Web UI |

端口被占用时脚本会自动向后寻找可用端口；实际端口以启动日志中的
`[start] ... on :<port>` 为准。更多说明见仓库根目录 `LOCAL_START.md`。

## 第五步：解析文档

```bash
# 标准档位（小模型 + VLM，推荐）
mineru-kit parse <input_path> -o <output_path> --tier standard

# 基础档位（仅小模型，CPU 可运行）
mineru-kit parse <input_path> -o <output_path> --tier basic

# 快速文本提取（无模型）
mineru-kit parse <input_path> -o <output_path> --tier flash
```

## 档位选择指南

| 档位 | 模型依赖 | 适用场景 |
|------|----------|----------|
| `flash` | 无 | 纯文本提取，快速预览 |
| `basic` | 小模型包 | CPU 可运行，日常文档 |
| `standard` / `advanced` | 小模型包 + VLM 模型（或远程 VLM 服务） | 复杂版面、公式、表格，最佳精度 |

### 本地引擎 vs 远程 VLM 服务选择建议

- **选择本地引擎（默认）**：
  - 无需额外服务，开箱即用
  - Apple Silicon 上 `auto` 默认使用 llama.cpp（CPU 推理），也可显式选择 `mlx`（需 `mlx-vlm`）
  - 首次运行按档位自动下载模型

- **选择远程 VLM 服务（LM Studio）**：
  - 本地内存有限，无法同时承载小模型与 VLM
  - 希望复用 LM Studio 中已加载的模型
  - 注意：小模型仍由档位决定并在本地运行，`server_url` 只替换 VLM 推理

## 备选方案：纯 CPU 运行

如果不想安装 LM Studio，可以使用 `pipeline` 后端在纯 CPU 环境下运行：

```bash
# 安装 MinerU
uv pip install -U "mineru[all]" -i https://mirrors.aliyun.com/pypi/simple

# 使用 pipeline 后端（纯 CPU）
mineru -p <input_path> -o <output_path> -b pipeline
```

> **注意**：`pipeline` 后端精度约为 85+，适合对精度要求不高的场景或快速测试。

## 环境变量配置

```bash
# 模型源配置（国内推荐）
export MINERU_MODEL_SOURCE=modelscope

# 远程 VLM 服务（可选，如 LM Studio）
export MINERU_MODEL_VLM_SERVER_URL=http://127.0.0.1:1234/v1

# 本地 VLM 引擎（可选：auto/llama-cpp/vllm/lmdeploy/mlx，MLX 仅显式使用）
export MINERU_MODEL_VLM_ENGINE=auto

# 小模型后端（可选：auto/onnx/torch）
export MINERU_MODEL_SMALL_BACKEND=auto
```

## 常见问题

### Q1: LM Studio 无法启动服务器

**解决方案**：
1. 确保已加载模型（在 "My Models" 中选择模型并点击 Load）
2. 检查端口是否被占用（默认 1234）
3. 尝试更改端口：在 LM Studio 设置中修改端口号，并同步更新 `MINERU_MODEL_VLM_SERVER_URL`

### Q2: 解析速度慢

**解决方案**：
1. 确保使用 Apple Silicon 芯片的 MPS 加速
2. 显式选择 `mlx` 引擎（需安装 `mlx-vlm>=0.7.0,<0.8.0`）：`export MINERU_MODEL_VLM_ENGINE=mlx`
3. 减少并发任务数

### Q3: 内存不足

**解决方案**：
1. 关闭其他占用内存的应用
2. 改用远程 VLM 服务（LM Studio）承载 VLM 推理，降低本地内存占用
3. 使用 `basic` 档位（不加载 VLM）

### Q4: 无法访问 ModelScope

**解决方案**：
1. 检查网络连接
2. 尝试切换到 huggingface：`export MINERU_MODEL_SOURCE=huggingface`
3. 或使用本地模型：`export MINERU_MODEL_SOURCE=local`（需先完成下载）

### Q5: Intel Mac 是否支持 GPU 加速？

**答案**：Intel Mac 不支持 MPS 加速，只能使用 CPU 运行。建议使用 `basic` 档位，或配合 LM Studio 远程 VLM 服务使用 `standard` 档位。

## 性能优化建议

1. **使用 Apple Silicon**：M1/M2/M3 系列芯片支持 MPS 加速，性能显著优于 Intel
2. **选择合适的档位**：日常文档用 `basic`，复杂文档再用 `standard`/`advanced`
3. **批量处理**：使用目录作为输入，一次性处理多个文件

## 服务管理

### 启动服务

```bash
# 一键启动（推荐）
bash scripts/start_mineru_local.sh all
```

### 停止服务

- 单服务模式（`gradio/api/openai`）：终端按 `Ctrl+C` 即可停止。
- `all` 模式：终端按 `Ctrl+C` 会同时停止所有子进程。

## 相关文档

- [快速入门](../quick_start/index.md)
- [命令行工具](./cli_tools.md)
- [FAQ](../faq/index.md)
