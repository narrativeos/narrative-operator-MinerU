# ADR-0035: macOS 本地部署 VLM 引擎选择（mlx 独立服务）

状态: Accepted
日期: 2026-09-18
相关文档: ../model-assets.md, ../cli/mineru-kit-vlm-server.md, ../cli/mineru-kit-api-server.md, 0017-mineru-kit-api-server-command.md, 0018-mineru-kit-vlm-server-command.md

## 背景

`scripts/start_mineru_local.sh` 是 fork 特有的一键本地部署脚本（upstream `opendatalab/MinerU` 无等价物）。其 `api` 模式需要为 Standard/Advanced 档位提供 VLM 推理。

最初设想沿用 vLLM（高吞吐、全精度），但 `vllm-metal 0.29.0` 没有 Qwen2-VL 的多模态 adapter（仅支持 Qwen3-VL 家族与 PaddleOCR-VL），而 MinerU 2.5 Pro 模型解析出的架构是 `Qwen2VLForConditionalGeneration`。因此 vLLM 在 macOS 上无法完成图像推理（报 `adapter is missing or not forward_ready`）。

需要在 macOS 上为"独立 VLM 服务 + api-server"这一 API 部署形态选择一个可用的 VLM 引擎。

## 决策

- `api` / `all` / `openai` 模式在 Apple Silicon 上默认 `VLM_ENGINE=mlx`（可用 `MINERU_VLM_ENGINE` 覆盖）。
- 部署形态为**独立 VLM 服务**：`mineru-kit vlm-server --engine mlx` 提供 OpenAI 兼容端点，`mineru-kit api-server --vlm-server-url http://127.0.0.1:<port>/v1` 连接该端点。
- mlx 使用**原始全精度权重** `MinerU2.5-Pro-2605-1.2B`（与 vLLM/lmdeploy 同一份权重），依赖 `mlx-vlm>=0.7.0,<0.8.0`。
- 脚本在 macOS 上自动安装 `mlx-vlm==0.7.1`（upstream 的 `full` extra 在 darwin/arm64 上不装 mlx-vlm，只装 `mineru[torch]`）。
- `vlm-server` 的 vllm 专属调度参数（`--data-parallel-size` / `--gpu-memory-utilization`）在 mlx 下不传，由脚本的 `build_vlm_server_args` 按引擎条件化。

## 替代方案

### llama.cpp（内联，upstream macOS 默认）——未选

- 使用 **Q8_0 量化** GGUF（`MinerU2.5-Pro-2605-1.2B-GGUF` + mmproj），非全精度。
- 只能作为**内联解析后端**运行：`api-server` 不传 `--vlm-server-url` 时，`get_vlm_predictor` 走本地引擎，macOS 上 `resolve_vlm_engine` 默认 `llama-cpp`。**没有独立的 llama.cpp 服务**（`mineru/kit/vlm_server/` 只有 vllm/lmdeploy/mlx），`vlm-server --engine` 也不接受 `llama-cpp`。
- 优点：单进程、更简单、下载更小、贴 upstream 默认。
- 未选原因：本 fork 的 `api` 模式需要**独立 VLM 服务**（OpenAI 兼容端点、进程分离、`max_concurrency` 高并发、可被多实例共享）。llama.cpp 无法提供独立服务，只能内联，与该部署形态不匹配；且 Q8_0 量化相对全精度是质量降级。

### vLLM——未选（不可用）

- `vllm-metal 0.29.0` 无 Qwen2-VL 多模态 adapter，macOS 上无法完成图像推理。
- 另与 `mlx-vlm 0.7.x` 存在依赖冲突（vllm-metal 锁定 `mlx==0.32.1` + `mlx-vlm<0.7.0`，二者互斥）。

### lmdeploy——未选

- 非 macOS 目标路径（upstream 仅在 win32 装 lmdeploy），且需 `qwen_vl_utils`。

## 影响

- 环境需安装 `mlx-vlm>=0.7.0,<0.8.0`（脚本自动处理）；`full` extra 不覆盖，属 fork 额外依赖。
- 推理为全精度（与 vLLM 路径一致），非 Q8_0 量化。
- 运行时为**双进程**（vlm-server + api-server），并暴露 OpenAI 兼容端点。
- 与 upstream 的 macOS 默认（llama.cpp 内联）不同；`start_mineru_local.sh` 为 fork 独有，rebase upstream 时需单独维护。
- 引擎代码（`mlx_vlm_server.py` 等）与 upstream 逐字节一致，无实现分叉。

## 后续动作

- 若未来某场景只需"简单本地解析"（不需要 API / OpenAI 端点），可改用内联 llama.cpp：不启 vlm-server、`api-server` 不传 `--vlm-server-url`、安装 `mineru-llama-cpp`。
- 跟踪 upstream 对 macOS VLM 引擎的默认选择与 `mlx-vlm` 版本范围变化，同步脚本。
