# Copyright (c) Opendatalab. All rights reserved.
import click
import sys

from loguru import logger


def vllm_server():
    try:
        from mineru.model.vlm.vllm_server import main
        main()
    except Exception as e:
        error_msg = str(e).lower()
        if "torchaudio" in error_msg or "torch" in error_msg or "symbol not found" in error_msg:
            logger.warning(
                "VLM server failed due to torch/torchaudio compatibility issue. "
                "This is a known issue when torch and torchaudio versions mismatch. "
                "Try: pip install torch torchaudio --force-reinstall"
            )
        else:
            logger.error(f"VLM server failed: {e}")
        return


def lmdeploy_server():
    try:
        from mineru.model.vlm.lmdeploy_server import main
        main()
    except Exception as e:
        logger.error(f"VLM server (lmdeploy) failed: {e}")
        return


def mlx_server():
    try:
        from mineru.model.vlm.mlx_server import main
        main()
    except Exception as e:
        logger.error(f"VLM server (mlx) failed: {e}")
        return


@click.command(context_settings=dict(ignore_unknown_options=True, allow_extra_args=True))
@click.option(
    '-e',
    '--engine',
    'inference_engine',
    type=click.Choice(['auto', 'vllm', 'lmdeploy', 'mlx']),
    default='auto',
    help='Select the inference engine used to accelerate VLM inference, default is "auto".',
)
@click.pass_context
def openai_server(ctx, inference_engine):
    sys.argv = [sys.argv[0]] + ctx.args
    if inference_engine == 'auto':
        # Platform-specific engine selection
        import sys as _sys
        if _sys.platform == 'darwin':
            # macOS: prefer mlx (native Apple Silicon) or vllm with metal
            inference_engine = _select_mac_server_engine()
        elif _sys.platform == 'win32':
            # Windows: prefer lmdeploy
            try:
                import lmdeploy
                inference_engine = 'lmdeploy'
                logger.info("Using LMDeploy as the inference engine for VLM server.")
            except ImportError:
                try:
                    import vllm
                    inference_engine = 'vllm'
                    logger.info("Using vLLM as the inference engine for VLM server.")
                except ImportError:
                    logger.warning(
                        "Neither vLLM nor LMDeploy is installed. "
                        "VLM server will not be available."
                    )
                    return
        else:
            # Linux: prefer vllm
            try:
                import vllm
                inference_engine = 'vllm'
                logger.info("Using vLLM as the inference engine for VLM server.")
            except ImportError:
                try:
                    import lmdeploy
                    inference_engine = 'lmdeploy'
                    logger.info("Using LMDeploy as the inference engine for VLM server.")
                except ImportError:
                    logger.warning(
                        "Neither vLLM nor LMDeploy is installed. "
                        "VLM server will not be available. "
                        "To enable VLM: pip install vllm (Linux/NVIDIA)."
                    )
                    return

    if inference_engine == 'vllm':
        try:
            import vllm
        except ImportError:
            logger.warning("vLLM is not installed. VLM server will not be available.")
            return
        vllm_server()
    elif inference_engine == 'lmdeploy':
        try:
            import lmdeploy
        except ImportError:
            logger.warning("LMDeploy is not installed. VLM server will not be available.")
            return
        lmdeploy_server()
    elif inference_engine == 'mlx':
        try:
            from mlx_vlm import load
        except ImportError:
            logger.warning("mlx-vlm is not installed. VLM server will not be available.")
            return
        mlx_server()


def _select_mac_server_engine() -> str:
    """Select the best server engine for macOS.
    
    On macOS, vLLM falls back to CPU mode (vllm_metal 0.1.0 is incompatible
    with vLLM 0.11+). The vllm_server.py has a built-in fix that adds
    --max-num-batched-tokens=8192 to work around CPU mode limitations.
    
    mlx-vlm does not have a built-in OpenAI-compatible server, so we use vLLM
    for server mode and rely on the fix in vllm_server.py.
    """
    try:
        import vllm
        inference_engine = 'vllm'
        logger.info("Using vLLM as the inference engine for VLM server (macOS).")
        return inference_engine
    except ImportError:
        pass
    logger.warning(
        "No suitable VLM inference engine found on macOS. "
        "Install vllm ('pip install vllm') for server support."
    )
    return 'none'

if __name__ == "__main__":
    openai_server()