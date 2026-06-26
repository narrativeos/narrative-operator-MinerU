'''
Author: Future Meng futuremeng@gmail.com
Date: 2026-05-20 10:02:55
LastEditors: Future Meng futuremeng@gmail.com
LastEditTime: 2026-06-26 11:47:39
FilePath: /narrative-operator-MinerU/mineru/model/vlm/vllm_server.py
Description: 这是默认设置,请设置`customMade`, 打开koroFileHeader查看配置 进行设置: https://github.com/OBKoro1/koro1FileHeader/wiki/%E9%85%8D%E7%BD%AE
'''
# Copyright (c) Opendatalab. All rights reserved.
import os
import sys

from loguru import logger

from mineru.backend.vlm.utils import set_default_gpu_memory_utilization, enable_custom_logits_processors, \
    mod_kwargs_by_device_type
from mineru.utils.models_download_utils import auto_download_and_get_model_root_path

from vllm.entrypoints.cli.main import main as vllm_main


def _is_mac_cpu_mode() -> bool:
    """Check if running on macOS without GPU acceleration (CPU mode).
    
    On macOS, even if vllm_metal is installed, it may not work properly
    with certain vLLM versions, causing vLLM to fall back to CPU platform.
    We check by looking at vLLM's actual platform detection.
    """
    if sys.platform != "darwin":
        return False
    # Check if vLLM has already detected a non-CPU platform
    # by checking the environment or vLLM's internal state
    try:
        from vllm import logger as vllm_logger
        # If vllm_metal is properly working, the platform should be 'metal'
        # Check via environment variable that can be set by users
        platform_env = os.environ.get("VLLM_PLATFORM", "")
        if platform_env == "metal":
            return False
    except Exception:
        pass
    # On macOS, vLLM often falls back to CPU even with vllm_metal installed
    # due to version incompatibility. Be conservative and assume CPU mode.
    return True


def main():
    args = sys.argv[1:]

    has_port_arg = False
    has_gpu_memory_utilization_arg = False
    has_logits_processors_arg = False
    has_max_num_batched_tokens_arg = False
    model_path = None
    model_arg_indices = []

    # 检查现有参数
    for i, arg in enumerate(args):
        if arg == "--port" or arg.startswith("--port="):
            has_port_arg = True
        if arg == "--gpu-memory-utilization" or arg.startswith("--gpu-memory-utilization="):
            has_gpu_memory_utilization_arg = True
        if arg == "--logits-processors" or arg.startswith("--logits-processors="):
            has_logits_processors_arg = True
        if arg == "--max-num-batched-tokens" or arg.startswith("--max-num-batched-tokens="):
            has_max_num_batched_tokens_arg = True
        if arg == "--model":
            if i + 1 < len(args):
                model_path = args[i + 1]
                model_arg_indices.extend([i, i + 1])
        elif arg.startswith("--model="):
            model_path = arg.split("=", 1)[1]
            model_arg_indices.append(i)

    # 从参数列表中移除 --model 参数
    if model_arg_indices:
        for index in sorted(model_arg_indices, reverse=True):
            args.pop(index)

    custom_logits_processors = enable_custom_logits_processors()

    # 添加默认参数
    if not has_port_arg:
        args.extend(["--port", "30000"])
    if not has_gpu_memory_utilization_arg:
        gpu_memory_utilization = str(set_default_gpu_memory_utilization())
        args.extend(["--gpu-memory-utilization", gpu_memory_utilization])
    if not model_path:
        model_path = auto_download_and_get_model_root_path("/", "vlm")
    if (not has_logits_processors_arg) and custom_logits_processors:
        args.extend(["--logits-processors", "mineru_vl_utils:MinerULogitsProcessor"])

    # On macOS CPU mode, vLLM defaults to max_num_batched_tokens=2048 which is too small
    # for the model's max_model_len=8192. Set it to match max_model_len.
    if _is_mac_cpu_mode() and not has_max_num_batched_tokens_arg:
        args.extend(["--max-num-batched-tokens", "8192"])
        logger.info("macOS CPU mode detected, setting max_num_batched_tokens=8192")

    args = mod_kwargs_by_device_type(args, vllm_mode="server")

    # 重构参数，将模型路径作为位置参数
    sys.argv = [sys.argv[0]] + ["serve", model_path] + args

    if os.getenv('OMP_NUM_THREADS') is None:
        os.environ["OMP_NUM_THREADS"] = "1"

    # 启动vllm服务器
    print(f"start vllm server: {sys.argv}")
    vllm_main()


if __name__ == "__main__":
    main()
