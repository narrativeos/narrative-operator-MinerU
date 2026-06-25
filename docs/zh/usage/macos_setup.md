# macOS 部署指南

> **重要提示**：MinerU 官方明确说明 Docker 部署不适用于 macOS。本指南提供 macOS 上的最佳部署方案。

## 系统要求

- **操作系统**：macOS 14.0 或以上版本
- **芯片**：Apple Silicon (M1/M2/M3 系列) 推荐，Intel Mac 也支持
- **内存**：最低 16GB，推荐 32GB 以上
- **磁盘空间**：20GB 以上（推荐使用 SSD）
- **Python 版本**：3.10-3.13

## 推荐方案：LM Studio + http-client 后端

此方案通过本地 LM Studio 提供 OpenAI 兼容的 VLM 推理服务，结合 MinerU 的 `http-client` 后端，在 macOS 上获得最佳解析精度（95+ 分）。

### 第一步：安装 LM Studio

1. 访问 https://lmstudio.ai/ 下载并安装 LM Studio
2. 启动 LM Studio
3. 搜索并下载支持的 VLM 模型：
   - 推荐模型：`Qwen2.5-VL-7B-Instruct`、`Qwen2-VL-7B-Instruct` 或其他支持视觉语言的模型
   - 在 "My Models" 标签页中下载模型
4. 加载模型：
   - 在左侧选择下载的模型
   - 点击 "Load" 按钮加载模型到内存
5. 启动本地服务器：
   - 转到 "Local Server" 标签页
   - 点击 "Start Server" 启动 OpenAI 兼容服务器
   - 默认端口为 `1234`，可以在设置中修改

### 第二步：安装 MinerU

```bash
# 升级 pip 并安装 uv
pip install --upgrade pip -i https://mirrors.aliyun.com/pypi/simple
pip install uv -i https://mirrors.aliyun.com/pypi/simple

# 安装 MinerU 完整版本（包括 torch 等依赖）
uv pip install -U "mineru[all]" -i https://mirrors.aliyun.com/pypi/simple
```

> **注意**：`hybrid-http-client` 需要本地安装 `mineru[all]` 以提供 pipeline 依赖（torch、opencv 等）。Apple Silicon (M1/M2/M3) 会自动使用 MPS (Metal Performance Shaders) 加速 pipeline 部分的计算。

### 第三步：配置模型源（可选，国内推荐）

```bash
# 使用 ModelScope 作为模型源（国内访问更快）
export MINERU_MODEL_SOURCE=modelscope
```

### 第四步：检测 LM Studio 是否运行

```bash
# 使用脚本检测 LM Studio
bash scripts/start_mineru_local.sh check-lm-studio

# 自定义端口
export LM_STUDIO_PORT=1234
bash scripts/start_mineru_local.sh check-lm-studio
```

### 第五步：一键启动 MinerU 服务

```bash
# 一键启动所有服务（自动检测 LM Studio）
bash scripts/start_mineru_local.sh start
```

启动后，您可以查看服务状态：

```bash
# 查看服务状态
bash scripts/start_mineru_local.sh status
```

输出示例：
```
[info] MinerU Service Status:
┌─────────────────────────────────────────────────────────────────┐
│  LM Studio              : ✓ (port 1234)                         │
│  MinerU API             : ✓ (port 8000)                         │
│  MinerU Gradio          : ✓ (port 7860)                         │
│  MinerU OpenAI          : ✗ (port 30000)                        │
└─────────────────────────────────────────────────────────────────┘
```

**常用命令：**

| 命令 | 说明 |
|------|------|
| `bash scripts/start_mineru_local.sh start` | 一键启动所有服务 |
| `bash scripts/start_mineru_local.sh stop` | 停止所有服务 |
| `bash scripts/start_mineru_local.sh status` | 查看服务状态 |

### 第六步：使用 http-client 后端进行文档解析

```bash
# 高精度混合模式（推荐，需要本地 pipeline 依赖）
mineru -p <input_path> -o <output_path> -b hybrid-http-client -u http://127.0.0.1:1234

# 轻量远程模式（不需要本地 torch，仅支持中英文）
mineru -p <input_path> -o <output_path> -b vlm-http-client -u http://127.0.0.1:1234
```

## 后端选择指南

| 后端 | 精度 | 本地依赖 | 适用场景 |
|------|------|----------|----------|
| `hybrid-http-client` | 95+ (高精度) | 需要 mineru[all] + torch | 多语言支持，最佳精度 |
| `vlm-http-client` | 95+ (高精度) | **不需要 torch** | 边缘设备，仅中英文 |
| `pipeline` | 85+ | 需要 mineru[pipeline] | 纯 CPU，无需额外服务 |

### hybrid-http-client vs vlm-http-client 选择建议

- **选择 `hybrid-http-client`**：
  - 需要多语言支持（中文、英文、日文、韩文等）
  - 追求最佳解析精度
  - 设备满足 mineru[all] 安装要求

- **选择 `vlm-http-client`**：
  - 仅需要中英文支持
  - 设备资源有限，无法安装 torch
  - 边缘设备部署

### VLM 后端模式架构说明

MinerU 支持两种 VLM 后端模式，理解它们的区别对于正确配置非常重要：

#### 1. `hybrid-http-client` 后端（混合模式）

```
┌─────────────────────────────────────────────────────────────────┐
│                        hybrid-http-client                       │
│                                                                 │
│   MinerU API                                                    │
│   ├── 本地 MinerU 模型 (MinerU2.5-Pro)                          │
│   │    ├── 布局分析 (Layout Analysis)                           │
│   │    ├── OCR 文字识别                                         │
│   │    ├── 公式识别 (Formula Recognition)                       │
│   │    └── 表格识别 (Table Recognition)                         │
│   │         ↓ 复杂页面需要 VLM 辅助时                            │
│   └──→ LM Studio (http://127.0.0.1:1234)                       │
│         └── VLM 模型 (如 Qwen2.5-VL-7B)                        │
│                                                                 │
│   特点：                                                        │
│   - 本地模型：MinerU2.5-Pro（自动下载）                          │
│   - 运行引擎：mlx-engine（Apple Silicon GPU 加速）               │
│   - LM Studio：辅助复杂页面分析                                  │
│   - 精度：最高（95+）                                            │
│   - 内存需求：较高（需同时加载本地模型 + LM Studio 模型）         │
└─────────────────────────────────────────────────────────────────┘
```

**工作流程：**
1. MinerU 加载本地模型（MinerU2.5-Pro），使用 mlx-engine 在 Apple Silicon 上加速
2. 对于标准页面，本地模型独立完成布局分析、OCR、公式/表格识别
3. 对于复杂页面（如图表、特殊排版），调用 LM Studio 的 VLM 模型进行辅助分析
4. 合并本地模型和 VLM 的结果，输出最终解析结果

#### 2. `vlm-http-client` 后端（纯远程模式）

```
┌─────────────────────────────────────────────────────────────────┐
│                      vlm-http-client                            │
│                                                                 │
│   MinerU API                                                    │
│   └──→ LM Studio (http://127.0.0.1:1234)                       │
│         └── VLM 模型 (如 Qwen2.5-VL-7B)                        │
│                                                                 │
│   特点：                                                        │
│   - 本地模型：不使用                                              │
│   - 运行引擎：完全依赖 LM Studio                                  │
│   - 内存需求：较低（仅需 LM Studio 模型）                         │
│   - 精度：高（95+）                                              │
│   - 限制：仅支持中英文                                            │
└─────────────────────────────────────────────────────────────────┘
```

**工作流程：**
1. MinerU 不加载任何本地模型
2. 所有页面分析请求直接发送到 LM Studio
3. LM Studio 的 VLM 模型独立完成所有分析任务
4. 返回结果给 MinerU 进行后处理

#### 模型运行位置对比

| 组件 | hybrid-http-client | vlm-http-client |
|------|-------------------|-----------------|
| MinerU2.5-Pro 模型 | ✅ MinerU 代码驱动（mlx-engine） | ❌ 不加载 |
| LM Studio 模型 | ✅ LM Studio 驱动（辅助） | ✅ LM Studio 驱动（主要） |
| 模型下载位置 | `~/.cache/modelscope/hub/models/OpenDataLab/MinerU2.5-Pro-*` | N/A |
| GPU 加速 | Apple Silicon MPS (mlx-engine) | LM Studio 自行管理 |

> **重要提示**：MinerU2.5-Pro 模型是由 **MinerU 代码驱动**的，使用 `mlx-engine` 在 Apple Silicon 上运行。LM Studio 模型是由 **LM Studio 软件驱动**的。两者是独立的模型，在不同的进程中运行。

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

# LM Studio 端口（可选，默认 1234）
export LM_STUDIO_PORT=1234

# GPU 显存利用率（Apple Silicon 可调低以避免内存压力）
export MINERU_GPU_MEMORY_UTILIZATION=0.35

# 批处理配置
export MINERU_HYBRID_BATCH_RATIO=1

# 缓存配置
export MINERU_ENABLE_GRADIO_UI_CACHE=true
export MINERU_ENABLE_API_CACHE=true
```

## 常见问题

### Q1: LM Studio 无法启动服务器

**解决方案**：
1. 确保已加载模型（在 "My Models" 中选择模型并点击 Load）
2. 检查端口是否被占用（默认 1234）
3. 尝试更改端口：在 LM Studio 设置中修改端口号

### Q2: 解析速度慢

**解决方案**：
1. 调整 `MINERU_GPU_MEMORY_UTILIZATION` 参数（默认 0.4，可适当调高）
2. 确保使用 Apple Silicon 芯片的 MPS 加速
3. 减少并发任务数

### Q3: 内存不足

**解决方案**：
1. 降低 `MINERU_GPU_MEMORY_UTILIZATION` 到 0.2-0.3
2. 设置 `MINERU_HYBRID_BATCH_RATIO=1`
3. 关闭其他占用内存的应用
4. 考虑使用 `vlm-http-client` 后端减少本地内存占用

### Q4: 无法访问 ModelScope

**解决方案**：
1. 检查网络连接
2. 尝试切换到 huggingface：`export MINERU_MODEL_SOURCE=huggingface`
3. 或使用本地模型：`export MINERU_MODEL_SOURCE=local`

### Q5: Intel Mac 是否支持 GPU 加速？

**答案**：Intel Mac 不支持 MPS 加速，只能使用 CPU 运行。建议使用 `pipeline` 后端或 `http-client` 后端配合 LM Studio。

## 性能优化建议

1. **使用 Apple Silicon**：M1/M2/M3 系列芯片支持 MPS 加速，性能显著优于 Intel
2. **调整显存利用率**：根据设备内存调整 `MINERU_GPU_MEMORY_UTILIZATION`
3. **启用缓存**：设置 `MINERU_ENABLE_API_CACHE=true` 避免重复解析
4. **批量处理**：使用目录作为输入，一次性处理多个文件

## 服务管理

### 启动服务

```bash
# 一键启动（推荐）
bash scripts/start_mineru_local.sh start
```

### 查看状态

```bash
bash scripts/start_mineru_local.sh status
```

### 停止服务

```bash
bash scripts/start_mineru_local.sh stop
```

## 相关文档

- [快速入门](../quick_start/index.md)
- [命令行工具](./cli_tools.md)
- [FAQ](../faq/index.md)
