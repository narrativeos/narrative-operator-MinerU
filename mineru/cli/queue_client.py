# Queue client for Gradio integration
# Supports two modes:
# 1. Embedded mode (default): uses SQLiteQueueManager directly in-process
# 2. HTTP mode: when MINERU_QUEUE_SERVICE_URL is set, proxies to remote queue service

import asyncio
import json
import os
import shutil
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Optional

import httpx
import logging

logger = logging.getLogger(__name__)


def get_queue_service_url() -> Optional[str]:
    """Get the queue service URL from environment."""
    return os.getenv("MINERU_QUEUE_SERVICE_URL")


def is_queue_enabled() -> bool:
    """Check if queue mode is enabled. Always enabled for embedded mode."""
    return True  # Embedded mode is always available


def is_http_mode() -> bool:
    """Check if using HTTP mode (remote queue service)."""
    return bool(get_queue_service_url())


# ---- Embedded mode: direct SQLite access ----
# Lazy initialization to avoid DB creation on import
_queue_manager = None
_consumer_thread = None
_consumer_started = False


def _get_queue_manager():
    """Get or create the embedded queue manager singleton."""
    global _queue_manager
    if _queue_manager is None:
        # Import here to avoid issues when services/queue is not installed
        try:
            from services.queue.sqlite_queue import SQLiteQueueManager, queue_manager as _qm
            _queue_manager = _qm
        except ImportError:
            # Fallback: try relative import
            try:
                from services.queue.sqlite_queue import SQLiteQueueManager, queue_manager as _qm
                _queue_manager = _qm
            except ImportError:
                logger.error("Cannot import SQLiteQueueManager - queue service unavailable")
                return None
    return _queue_manager


def _start_consumer():
    """Start the embedded consumer thread."""
    global _consumer_thread, _consumer_started
    if _consumer_started:
        return
    try:
        from services.queue.consumer import start_consumer_thread
        _consumer_thread = start_consumer_thread()
        _consumer_started = True
        logger.info("Embedded queue consumer started")
    except ImportError:
        logger.error("Cannot import consumer - queue processing unavailable")
    except Exception as e:
        logger.error(f"Failed to start embedded consumer: {e}")


def _ensure_consumer():
    """Ensure the consumer thread is running."""
    if not _consumer_started:
        _start_consumer()


# ---- Embedded mode functions ----

def _get_tmp_dir() -> Path:
    tmp_dir = Path(os.getenv("MINERU_QUEUE_TMP_DIR", "./input"))
    tmp_dir.mkdir(parents=True, exist_ok=True)
    return tmp_dir


def _get_output_root() -> Path:
    output_root = Path(os.getenv("MINERU_QUEUE_OUTPUT_ROOT", "./output"))
    output_root.mkdir(parents=True, exist_ok=True)
    return output_root


def _format_ts(ts: Optional[float]) -> Optional[str]:
    if ts is None:
        return None
    from datetime import datetime
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%dT%H:%M:%S")


def _task_to_dict(task) -> dict:
    """Convert a QueueTask to a response dict."""
    if task is None:
        return None
    return {
        "task_id": task.task_id,
        "filename": task.filename,
        "file_size": task.file_size,
        "status": task.status,
        "queue_position": task.queue_position,
        "backend": task.backend,
        "parse_method": task.parse_method,
        "lang_list": task.lang_list,
        "formula_enable": task.formula_enable,
        "table_enable": task.table_enable,
        "image_analysis": task.image_analysis,
        "effort": task.effort,
        "start_page_id": task.start_page_id,
        "end_page_id": task.end_page_id,
        "created_at": _format_ts(task.created_at),
        "started_at": _format_ts(task.started_at),
        "completed_at": _format_ts(task.completed_at),
        "error": task.error,
        "result_dir": task.result_dir,
    }


async def queue_health(client: httpx.AsyncClient) -> Optional[dict]:
    """Check queue health. For embedded mode, return status directly."""
    if is_http_mode():
        url = get_queue_service_url()
        if not url:
            return None
        try:
            resp = await client.get(f"{url}/health", timeout=5.0)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        return None

    # Embedded mode
    qm = _get_queue_manager()
    if not qm:
        return None
    stats = qm.get_stats()
    return {
        "status": "healthy",
        "service": "mineru-queue-embedded",
        "queue_size": stats.queue_size,
        "pending": stats.pending,
        "processing": stats.processing,
        "done": stats.done,
        "failed": stats.failed,
    }


async def queue_submit(
    client: httpx.AsyncClient,
    file_path: str,
    filename: str,
    backend: str = "pipeline",
    parse_method: str = "auto",
    lang_list: str = "ch",
    formula_enable: bool = True,
    table_enable: bool = True,
    image_analysis: bool = True,
    effort: str = "high",
    start_page_id: int = 0,
    end_page_id: int = 99999,
) -> Optional[dict]:
    """Submit a file to the queue."""
    if is_http_mode():
        url = get_queue_service_url()
        if not url:
            return None
        try:
            with open(file_path, "rb") as f:
                files = {"files": (filename, f, "application/pdf")}
                data = {
                    "backend": backend,
                    "parse_method": parse_method,
                    "lang_list": lang_list,
                    "formula_enable": str(formula_enable).lower(),
                    "table_enable": str(table_enable).lower(),
                    "image_analysis": str(image_analysis).lower(),
                    "effort": effort,
                    "start_page_id": str(start_page_id),
                    "end_page_id": str(end_page_id),
                }
                resp = await client.post(f"{url}/tasks", files=files, data=data, timeout=60.0)
                if resp.status_code == 202:
                    return resp.json()
        except Exception as e:
            logger.error(f"Queue submit exception: {e}")
        return None

    # Embedded mode
    qm = _get_queue_manager()
    if not qm:
        return None

    from services.queue.models import QueueTask

    _ensure_consumer()

    # Copy file to temp
    tmp_dir = _get_tmp_dir()
    safe_filename = filename.replace(" ", "_")
    tmp_file = tmp_dir / safe_filename
    shutil.copy2(file_path, tmp_file)
    file_size = os.path.getsize(file_path)

    lang_list_parsed = [lang.strip() for lang in lang_list.split(",") if lang.strip()]

    task = QueueTask(
        task_id=QueueTask.generate_id(),
        filename=filename,
        file_size=file_size,
        backend=backend,
        parse_method=parse_method,
        lang_list=lang_list_parsed,
        formula_enable=formula_enable,
        table_enable=table_enable,
        image_analysis=image_analysis,
        effort=effort,
        start_page_id=start_page_id,
        end_page_id=end_page_id,
    )

    # Move to task-named file
    task_file = tmp_dir / f"{task.task_id}_{safe_filename}"
    tmp_file.rename(task_file)

    position = qm.submit_task(task)
    if position < 0:
        return None

    result = _task_to_dict(task)
    result["queued_ahead"] = position - 1
    result["message"] = "Task submitted successfully"
    return result


async def queue_list_tasks(client: httpx.AsyncClient = None) -> list[dict]:
    """Get all tasks from the queue."""
    if is_http_mode():
        url = get_queue_service_url()
        if not url or not client:
            return []
        try:
            resp = await client.get(f"{url}/tasks", timeout=10.0)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        return []

    # Embedded mode
    qm = _get_queue_manager()
    if not qm:
        return []
    tasks = qm.get_all_tasks()
    return [_task_to_dict(t) for t in tasks if t]


async def queue_get_task(client: httpx.AsyncClient = None, task_id: str = None) -> Optional[dict]:
    """Get a single task from the queue."""
    if is_http_mode():
        url = get_queue_service_url()
        if not url or not client or not task_id:
            return None
        try:
            resp = await client.get(f"{url}/tasks/{task_id}", timeout=10.0)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        return None

    # Embedded mode
    qm = _get_queue_manager()
    if not qm or not task_id:
        return None
    task = qm.get_task(task_id)
    return _task_to_dict(task)


async def queue_download_result(client: httpx.AsyncClient = None, task_id: str = None) -> Optional[bytes]:
    """Download the result ZIP for a completed task."""
    if is_http_mode():
        url = get_queue_service_url()
        if not url or not client or not task_id:
            return None
        try:
            resp = await client.get(f"{url}/tasks/{task_id}/result", timeout=120.0)
            if resp.status_code == 200:
                return resp.content
        except Exception:
            pass
        return None

    # Embedded mode
    qm = _get_queue_manager()
    if not qm or not task_id:
        return None
    task = qm.get_task(task_id)
    if not task or not task.result_dir:
        return None

    result_dir = Path(task.result_dir)
    result_zip = result_dir / "result.zip"

    # Create zip if it doesn't exist
    if not result_zip.exists():
        with zipfile.ZipFile(result_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            for item in result_dir.iterdir():
                if item == result_zip:
                    continue
                if item.is_file():
                    zf.write(item, item.name)
                elif item.is_dir():
                    for subfile in item.rglob("*"):
                        if subfile.is_file():
                            arcname = str(subfile.relative_to(result_dir))
                            zf.write(subfile, arcname)

    return result_zip.read_bytes()


async def queue_delete_task(client: httpx.AsyncClient = None, task_id: str = None) -> bool:
    """Delete a task from the queue."""
    if is_http_mode():
        url = get_queue_service_url()
        if not url or not client or not task_id:
            return False
        try:
            resp = await client.delete(f"{url}/tasks/{task_id}", timeout=10.0)
            return resp.status_code == 204
        except Exception:
            pass
        return False

    # Embedded mode
    qm = _get_queue_manager()
    if not qm or not task_id:
        return False
    task = qm.get_task(task_id)
    if task and task.result_dir:
        shutil.rmtree(task.result_dir, ignore_errors=True)
    tmp_file = _get_tmp_dir() / f"{task_id}_{task.filename.replace(' ', '_')}" if task else None
    if tmp_file and tmp_file.exists():
        tmp_file.unlink()
    return qm.delete_task(task_id)


async def queue_cancel_task(client: httpx.AsyncClient = None, task_id: str = None) -> bool:
    """Cancel a waiting task."""
    if is_http_mode():
        url = get_queue_service_url()
        if not url or not client or not task_id:
            return False
        try:
            resp = await client.post(f"{url}/tasks/{task_id}/cancel", timeout=10.0)
            return resp.status_code == 200
        except Exception:
            pass
        return False

    # Embedded mode
    qm = _get_queue_manager()
    if not qm or not task_id:
        return False
    return qm.cancel_task(task_id)


async def queue_clear_all(client: httpx.AsyncClient = None) -> bool:
    """Clear all tasks from the queue."""
    if is_http_mode():
        url = get_queue_service_url()
        if not url or not client:
            return False
        try:
            resp = await client.delete(f"{url}/tasks", timeout=10.0)
            return resp.status_code == 204
        except Exception:
            pass
        return False

    # Embedded mode
    qm = _get_queue_manager()
    if not qm:
        return False
    qm.clear_all_tasks()
    return True


async def queue_stats(client: httpx.AsyncClient = None) -> Optional[dict]:
    """Get queue statistics."""
    if is_http_mode():
        url = get_queue_service_url()
        if not url or not client:
            return None
        try:
            resp = await client.get(f"{url}/stats", timeout=5.0)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        return None

    # Embedded mode
    qm = _get_queue_manager()
    if not qm:
        return None
    stats = qm.get_stats()
    from services.queue.sqlite_queue import get_queue_max_size
    return {
        "pending": stats.pending,
        "processing": stats.processing,
        "done": stats.done,
        "failed": stats.failed,
        "total": stats.total,
        "queue_size": stats.queue_size,
        "max_queue_size": get_queue_max_size(),
    }


def init_embedded_queue():
    """Initialize the embedded queue (call once at startup)."""
    _ensure_consumer()