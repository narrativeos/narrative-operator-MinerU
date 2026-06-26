# Copyright (c) Opendatalab. All rights reserved.
import os
import sys

from loguru import logger

from mineru.utils.models_download_utils import auto_download_and_get_model_root_path


def main():
    args = sys.argv[1:]

    has_port_arg = False
    model_path = None
    model_arg_indices = []

    # Parse existing arguments
    for i, arg in enumerate(args):
        if arg == "--port" or arg.startswith("--port="):
            has_port_arg = True
        if arg == "--model":
            if i + 1 < len(args):
                model_path = args[i + 1]
                model_arg_indices.extend([i, i + 1])
        elif arg.startswith("--model="):
            model_path = arg.split("=", 1)[1]
            model_arg_indices.append(i)

    # Remove --model arguments
    if model_arg_indices:
        for index in sorted(model_arg_indices, reverse=True):
            args.pop(index)

    # Set defaults
    if not has_port_arg:
        port = 30000
    else:
        for i, arg in enumerate(args):
            if arg == "--port" and i + 1 < len(args):
                port = int(args[i + 1])
            elif arg.startswith("--port="):
                port = int(arg.split("=", 1)[1])
        port = 30000

    if not model_path:
        model_path = auto_download_and_get_model_root_path("/", "vlm")

    if os.getenv("OMP_NUM_THREADS") is None:
        os.environ["OMP_NUM_THREADS"] = "1"

    logger.info(f"Start MLX VLM server with model: {model_path}, port: {port}")
    _run_mlx_server(model_path, port)


def _run_mlx_server(model_path: str, port: int):
    """Run an OpenAI-compatible API server using mlx-vlm."""
    try:
        from flask import Flask, jsonify, request
    except ImportError:
        logger.error("Flask is required for MLX server. Install with: pip install flask")
        return

    app = Flask(__name__)

    # Load model lazily on first request to avoid long startup
    model = None
    processor = None

    def load_model():
        nonlocal model, processor
        if model is None:
            logger.info(f"Loading MLX model from {model_path}...")
            from mlx_vlm import load as mlx_load, generate
            model, processor = mlx_load(model_path)
            logger.info("MLX model loaded successfully")

    @app.route("/v1/chat/completions", methods=["POST"])
    def chat_completions():
        load_model()
        data = request.json
        messages = data.get("messages", [])

        # Build prompt from messages
        prompt = _build_prompt_from_messages(messages)

        # Generate response
        from mlx_vlm import generate
        response = generate(model, processor, prompt, max_tokens=2048)

        return jsonify({
            "id": "chatcmpl-mlx-001",
            "object": "chat.completion",
            "created": 0,
            "model": model_path,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": response},
                "finish_reason": "stop"
            }],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        })

    @app.route("/v1/models", methods=["GET"])
    def list_models():
        return jsonify({
            "data": [{
                "id": model_path,
                "object": "model",
                "created": 0,
                "owned_by": "mineru"
            }]
        })

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({"status": "ok"})

    logger.info(f"Starting MLX VLM server on port {port}...")
    app.run(host="0.0.0.0", port=port, threaded=True)


def _build_prompt_from_messages(messages: list) -> str:
    """Build a prompt from chat messages."""
    parts = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "system":
            parts.append(f"System: {content}")
        elif role == "user":
            parts.append(f"User: {content}")
        elif role == "assistant":
            parts.append(f"Assistant: {content}")
    parts.append("Assistant:")
    return "\n".join(parts)


if __name__ == "__main__":
    main()