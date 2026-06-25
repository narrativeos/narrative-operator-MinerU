# Task consumer for queue service
# This module processes tasks from the Redis queue using MinerU's parsing engine

import asyncio
import json
import os
import shutil
import sys
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger

from .models import QueueTask
from .redis_client import queue_manager, get_output_root


# Import MinerU parsing functions
# These imports may fail if MinerU is not installed, handled gracefully
try:
    from mineru.cli.common import aio_do_parse
    MINERU_AVAILABLE = True
except ImportError:
    MINERU_AVAILABLE = False
    logger.warning("MinerU not available in this environment. Consumer will not process tasks.")


def format_timestamp(ts: Optional[float]) -> Optional[str]:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


async def process_single_task(task: QueueTask) -> str:
    """Process a single task using MinerU. Returns result directory path."""
    if not MINERU_AVAILABLE:
        raise RuntimeError("MinerU is not installed in this environment")

    output_root = get_output_root()
    task_output_dir = Path(output_root) / task.task_id
    task_output_dir.mkdir(parents=True, exist_ok=True)

    # Read the uploaded file from temp storage
    temp_file_dir = Path(os.getenv("MINERU_QUEUE_TMP_DIR", "/tmp/mineru-queue"))
    temp_file_dir.mkdir(parents=True, exist_ok=True)
    file_path = temp_file_dir / f"{task.task_id}_{task.filename}"

    if not file_path.exists():
        raise FileNotFoundError(f"Uploaded file not found: {file_path}")

    file_bytes = file_path.read_bytes()

    # Build parse options
    parse_options = {
        "backend": task.backend,
        "parse_method": task.parse_method,
        "lang_list": task.lang_list,
        "formula_enable": task.formula_enable,
        "table_enable": task.table_enable,
        "image_analysis": task.image_analysis,
        "effort": task.effort,
        "start_page_id": task.start_page_id,
        "end_page_id": task.end_page_id,
    }

    # Call MinerU to parse
    result = await aio_do_parse(
        pdf_bytes=file_bytes,
        pdf_name=task.filename,
        parse_dir=str(task_output_dir),
        **parse_options,
    )

    # Create a ZIP archive of the results
    result_zip_path = task_output_dir / "result.zip"
    with zipfile.ZipFile(result_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in task_output_dir.iterdir():
            if item == result_zip_path:
                continue
            if item.is_file():
                zf.write(item, item.name)
            elif item.is_dir():
                for subfile in item.rglob("*"):
                    if subfile.is_file():
                        arcname = str(subfile.relative_to(task_output_dir))
                        zf.write(subfile, arcname)

    return str(task_output_dir)


def run_consumer_loop():
    """Run the consumer loop that processes tasks from the queue."""
    if not MINERU_AVAILABLE:
        logger.error("MinerU is not available. Cannot start consumer.")
        return

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    poll_interval = float(os.getenv("MINERU_QUEUE_POLL_INTERVAL", "1.0"))

    logger.info("Queue consumer started. Polling for tasks...")

    while True:
        try:
            task = queue_manager.get_next_task()
            if task is None:
                time.sleep(poll_interval)
                continue

            logger.info(f"Processing task {task.task_id}: {task.filename}")

            try:
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