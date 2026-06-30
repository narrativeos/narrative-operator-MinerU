# Task consumer for queue service
# This module processes tasks from the SQLite queue by calling the MinerU FastAPI service

import asyncio
import httpx
import json
import os
import shutil
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger

from .models import QueueTask
from .sqlite_queue import queue_manager, get_output_root


def format_timestamp(ts: Optional[float]) -> Optional[str]:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def get_mineru_api_url() -> str:
    """Get the MinerU FastAPI URL from environment variable.
    
    Default to localhost:8401 for local development (Gradio's built-in FastAPI).
    Use host.docker.internal when running in Docker.
    """
    return os.getenv("MINERU_API_URL", "http://localhost:8401")


async def process_single_task(task: QueueTask) -> str:
    """Process a single task by calling the MinerU FastAPI service. Returns result directory path."""
    api_url = get_mineru_api_url()
    output_root = get_output_root()
    task_output_dir = Path(output_root) / task.task_id
    task_output_dir.mkdir(parents=True, exist_ok=True)

    # Read the uploaded file from temp storage
    # Default matches embedded mode (./input), Docker uses /tmp/mineru-queue via env
    temp_file_dir = Path(os.getenv("MINERU_QUEUE_TMP_DIR", "./input"))
    file_path = temp_file_dir / f"{task.task_id}_{task.filename}"

    if not file_path.exists():
        raise FileNotFoundError(f"Uploaded file not found: {file_path}")

    file_bytes = file_path.read_bytes()

    logger.info(f"Submitting task {task.task_id} to MinerU API at {api_url}")

    # Build the request form data (same as Gradio's _run_to_markdown_job)
    form_data = {
        "backend": task.backend,
        "parse_method": task.parse_method,
        "formula_enable": str(task.formula_enable).lower(),
        "table_enable": str(task.table_enable).lower(),
        "image_analysis": str(task.image_analysis).lower(),
        "effort": task.effort,
        "start_page_id": str(task.start_page_id),
        "end_page_id": str(task.end_page_id),
        "return_md": "true",
        "return_middle_json": "true",
        "return_model_output": "true",
        "return_content_list": "true",
        "return_images": "true",
        "response_format_zip": "true",
        "return_original_file": "true",
    }
    
    # Add lang_list as comma-separated string
    if task.lang_list:
        form_data["lang_list"] = ",".join(task.lang_list)

    # Submit to MinerU API
    async with httpx.AsyncClient(timeout=1800.0) as client:
        # Upload file and submit task
        files = {
            "files": (task.filename, file_bytes, "application/pdf")
        }
        
        submit_response = await client.post(
            f"{api_url}/tasks",
            files=files,
            data=form_data,
        )
        submit_response.raise_for_status()
        submit_json = submit_response.json()
        task_id = submit_json.get("task_id", "")
        
        logger.info(f"Task {task.task_id} submitted to API as {task_id}")
        
        # Poll for task completion
        while True:
            status_response = await client.get(
                f"{api_url}/tasks/{task_id}"
            )
            status_response.raise_for_status()
            status_json = status_response.json()
            status = status_json.get("status", "")
            
            if status == "completed":
                logger.info(f"Task {task.task_id} completed, downloading result...")
                break
            elif status == "failed":
                error_msg = status_json.get("error", "Unknown error")
                raise RuntimeError(f"API task failed: {error_msg}")
            else:
                # pending or processing
                await asyncio.sleep(2.0)
        
        # Download result ZIP
        download_response = await client.get(
            f"{api_url}/tasks/{task_id}/result"
        )
        download_response.raise_for_status()
        
        # Save ZIP to task output dir
        result_zip_path = task_output_dir / "result.zip"
        result_zip_path.write_bytes(download_response.content)
        
        # Extract ZIP to task output dir
        with zipfile.ZipFile(result_zip_path, "r") as zf:
            zf.extractall(task_output_dir)
        
        logger.info(f"Task {task.task_id} result extracted to {task_output_dir}")
        return str(task_output_dir)


def run_consumer_loop():
    """Run the consumer loop that processes tasks from the queue."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    poll_interval = float(os.getenv("MINERU_QUEUE_POLL_INTERVAL", "1.0"))

    logger.info("Queue consumer started. Polling for tasks...")
    logger.info(f"MinerU API URL: {get_mineru_api_url()}")

    while True:
        try:
            task = queue_manager.get_next_task()
            if task is None:
                time.sleep(poll_interval)
                continue

            logger.info(f"Processing task {task.task_id}: {task.filename}")

            try:
                task.status = "processing"
                task.started_at = time.time()
                queue_manager._save_task(task)
                
                result_dir = loop.run_until_complete(process_single_task(task))
                queue_manager.complete_task(task, result_dir)
                logger.info(f"Task {task.task_id} completed: {result_dir}")
            except Exception as e:
                error_msg = f"{type(e).__name__}: {str(e)}"
                logger.error(f"Task {task.task_id} failed: {error_msg}")
                queue_manager.fail_task(task, error_msg)

        except KeyboardInterrupt:
            logger.info("Consumer received interrupt, shutting down...")
            break
        except Exception as e:
            logger.error(f"Consumer error: {e}")
            time.sleep(poll_interval)

    loop.close()


def start_consumer_thread():
    """Start the consumer in a background thread."""
    import threading

    consumer_thread = threading.Thread(
        target=run_consumer_loop,
        name="mineru-queue-consumer",
        daemon=True,
    )
    consumer_thread.start()
    logger.info("Queue consumer thread started")
    return consumer_thread