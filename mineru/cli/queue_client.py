# Queue service client for Gradio integration
import os
from typing import Optional

import httpx


def get_queue_service_url() -> Optional[str]:
    """Get the queue service URL from environment."""
    return os.getenv("MINERU_QUEUE_SERVICE_URL")


def is_queue_enabled() -> bool:
    """Check if queue mode is enabled."""
    return bool(get_queue_service_url())


async def queue_health(client: httpx.AsyncClient) -> Optional[dict]:
    """Check queue service health."""
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


import logging

logger = logging.getLogger(__name__)


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
    """Submit a file to the queue service."""
    url = get_queue_service_url()
    if not url:
        logger.error("Queue service URL not set (MINERU_QUEUE_SERVICE_URL)")
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
            logger.info(f"Submitting to queue service: {url}/tasks")
            resp = await client.post(f"{url}/tasks", files=files, data=data, timeout=60.0)
            logger.info(f"Queue response: {resp.status_code} {resp.text[:200]}")
            if resp.status_code == 202:
                return resp.json()
            else:
                logger.error(f"Queue submit failed: {resp.status_code} {resp.text}")
    except Exception as e:
        logger.error(f"Queue submit exception: {e}")
    return None


async def queue_list_tasks(client: httpx.AsyncClient) -> list[dict]:
    """Get all tasks from the queue service."""
    url = get_queue_service_url()
    if not url:
        return []
    try:
        resp = await client.get(f"{url}/tasks", timeout=10.0)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return []


async def queue_get_task(client: httpx.AsyncClient, task_id: str) -> Optional[dict]:
    """Get a single task from the queue service."""
    url = get_queue_service_url()
    if not url:
        return None
    try:
        resp = await client.get(f"{url}/tasks/{task_id}", timeout=10.0)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


async def queue_download_result(
    client: httpx.AsyncClient, task_id: str
) -> Optional[bytes]:
    """Download the result ZIP for a completed task."""
    url = get_queue_service_url()
    if not url:
        return None
    try:
        resp = await client.get(f"{url}/tasks/{task_id}/result", timeout=120.0)
        if resp.status_code == 200:
            return resp.content
    except Exception:
        pass
    return None


async def queue_delete_task(client: httpx.AsyncClient, task_id: str) -> bool:
    """Delete a task from the queue service."""
    url = get_queue_service_url()
    if not url:
        return False
    try:
        resp = await client.delete(f"{url}/tasks/{task_id}", timeout=10.0)
        return resp.status_code == 204
    except Exception:
        pass
    return False


async def queue_cancel_task(client: httpx.AsyncClient, task_id: str) -> bool:
    """Cancel a waiting task."""
    url = get_queue_service_url()
    if not url:
        return False
    try:
        resp = await client.post(f"{url}/tasks/{task_id}/cancel", timeout=10.0)
        return resp.status_code == 200
    except Exception:
        pass
    return False


async def queue_stats(client: httpx.AsyncClient) -> Optional[dict]:
    """Get queue statistics."""
    url = get_queue_service_url()
    if not url:
        return None
    try:
        resp = await client.get(f"{url}/stats", timeout=5.0)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None