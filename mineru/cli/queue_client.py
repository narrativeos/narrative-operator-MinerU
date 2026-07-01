# Queue client for Gradio integration
# Now uses the FastAPI service (8401) directly with SQLite persistence
# No separate queue service needed

import os
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
import logging

logger = logging.getLogger(__name__)


def get_queue_service_url() -> Optional[str]:
    """Get the queue service URL from environment (for remote mode)."""
    return os.getenv("MINERU_QUEUE_SERVICE_URL")


def is_queue_enabled() -> bool:
    """Check if queue mode is enabled. Always enabled - FastAPI has built-in SQLite queue."""
    return True


def is_http_mode() -> bool:
    """Check if using HTTP mode (remote queue service)."""
    return bool(get_queue_service_url())


# Local FastAPI server URL (default port 8401)
_LOCAL_FASTAPI_URL = os.getenv("MINERU_LOCAL_API_URL", "http://127.0.0.1:8401")


def get_local_fastapi_url() -> str:
    """Get the local FastAPI server URL."""
    return _LOCAL_FASTAPI_URL


def _format_ts(ts: Optional[float]) -> Optional[str]:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%dT%H:%M:%S")


def _get_base_url(client: httpx.AsyncClient) -> str:
    """Get the base URL to use: remote queue service or local FastAPI."""
    if is_http_mode():
        return get_queue_service_url() or ""
    return get_local_fastapi_url()


# ---- Queue functions (embedded mode uses local FastAPI) ----

async def queue_health(client: httpx.AsyncClient) -> Optional[dict]:
    """Check queue health via FastAPI."""
    base_url = _get_base_url(client)
    if not base_url:
        return None
    try:
        resp = await client.get(f"{base_url}/health", timeout=5.0)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


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
    """Submit a file to the queue via FastAPI."""
    base_url = _get_base_url(client)
    if not base_url:
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
                "return_middle_json": "true",
                "response_format_zip": "true",
                "return_md": "true",
                "return_content_list": "true",
                "return_images": "true",
                "return_model_output": "true",
                "return_original_file": "true",
            }
            resp = await client.post(f"{base_url}/tasks", files=files, data=data, timeout=60.0)
            if resp.status_code == 202:
                result = resp.json()
                result["message"] = "Task submitted successfully"
                return result
    except Exception as e:
        logger.error(f"Queue submit exception: {e}")
    return None


async def queue_list_tasks(client: httpx.AsyncClient = None) -> list[dict]:
    """Get all tasks from FastAPI."""
    if not client:
        return []
    base_url = _get_base_url(client)
    if not base_url:
        return []
    try:
        resp = await client.get(f"{base_url}/tasks", timeout=10.0)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return []


async def queue_get_task(client: httpx.AsyncClient = None, task_id: str = None) -> Optional[dict]:
    """Get a single task from FastAPI."""
    if not client or not task_id:
        return None
    base_url = _get_base_url(client)
    if not base_url:
        return None
    try:
        resp = await client.get(f"{base_url}/tasks/{task_id}", timeout=10.0)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


async def queue_download_result(client: httpx.AsyncClient = None, task_id: str = None) -> Optional[bytes]:
    """Download the result ZIP from FastAPI."""
    if not client or not task_id:
        return None
    base_url = _get_base_url(client)
    if not base_url:
        return None
    try:
        resp = await client.get(f"{base_url}/tasks/{task_id}/result", timeout=120.0)
        if resp.status_code == 200:
            return resp.content
    except Exception:
        pass
    return None


async def queue_delete_task(client: httpx.AsyncClient = None, task_id: str = None) -> bool:
    """Delete a task from FastAPI."""
    if not client or not task_id:
        return False
    base_url = _get_base_url(client)
    if not base_url:
        return False
    try:
        resp = await client.delete(f"{base_url}/tasks/{task_id}", timeout=10.0)
        if resp.status_code == 200:
            return resp.json().get("success", False)
    except Exception:
        pass
    return False


async def queue_cancel_task(client: httpx.AsyncClient = None, task_id: str = None) -> bool:
    """Cancel a waiting task via FastAPI."""
    if not client or not task_id:
        return False
    base_url = _get_base_url(client)
    if not base_url:
        return False
    try:
        resp = await client.post(f"{base_url}/tasks/{task_id}/cancel", timeout=10.0)
        if resp.status_code == 200:
            return resp.json().get("success", False)
    except Exception:
        pass
    return False


async def queue_clear_all(client: httpx.AsyncClient = None) -> bool:
    """Clear all tasks via FastAPI."""
    if not client:
        return False
    base_url = _get_base_url(client)
    if not base_url:
        return False
    try:
        resp = await client.post(f"{base_url}/tasks/clear", timeout=10.0)
        if resp.status_code == 200:
            return resp.json().get("success", False)
    except Exception:
        pass
    return False


async def queue_stats(client: httpx.AsyncClient = None) -> Optional[dict]:
    """Get queue statistics from FastAPI health endpoint."""
    if not client:
        return None
    base_url = _get_base_url(client)
    if not base_url:
        return None
    try:
        resp = await client.get(f"{base_url}/health", timeout=5.0)
        if resp.status_code == 200:
            data = resp.json()
            return {
                "pending": data.get("queued_tasks", 0),
                "processing": data.get("processing_tasks", 0),
                "done": data.get("completed_tasks", 0),
                "failed": data.get("failed_tasks", 0),
                "total": sum([
                    data.get("queued_tasks", 0),
                    data.get("processing_tasks", 0),
                    data.get("completed_tasks", 0),
                    data.get("failed_tasks", 0),
                ]),
                "queue_size": data.get("queued_tasks", 0),
                "max_queue_size": 20,
            }
    except Exception:
        pass
    return None


def init_embedded_queue():
    """Initialize the embedded queue (no-op now, FastAPI handles everything)."""
    pass