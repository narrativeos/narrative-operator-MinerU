# Queue service FastAPI application
import os
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from loguru import logger

from .consumer import start_consumer_thread
from .models import QueueTask, TaskStatus, QueueStats
from .sqlite_queue import queue_manager, get_output_root, get_queue_max_size


app = FastAPI(
    title="MinerU Queue Service",
    description="SQLite-backed task queue service for MinerU PDF parsing",
    version="1.0.0",
)

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Ensure temp and output directories exist
TMP_DIR = Path(os.getenv("MINERU_QUEUE_TMP_DIR", "/tmp/mineru-queue"))
TMP_DIR.mkdir(parents=True, exist_ok=True)

OUTPUT_ROOT = Path(get_output_root())
OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)


def format_ts(ts: Optional[float]) -> Optional[str]:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%dT%H:%M:%S")


def task_to_response(task: QueueTask) -> dict:
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
        "created_at": format_ts(task.created_at),
        "started_at": format_ts(task.started_at),
        "completed_at": format_ts(task.completed_at),
        "error": task.error,
        "result_dir": task.result_dir,
    }


@app.on_event("startup")
async def startup_event():
    logger.info("MinerU Queue Service starting...")
    # Start the consumer thread
    start_consumer_thread()
    logger.info("Queue service ready")


@app.get("/health")
async def health_check():
    stats = queue_manager.get_stats()
    return {
        "status": "healthy",
        "service": "mineru-queue",
        "queue_size": stats.queue_size,
        "max_queue_size": get_queue_max_size(),
        "pending": stats.pending,
        "processing": stats.processing,
        "done": stats.done,
        "failed": stats.failed,
    }


@app.get("/stats")
async def get_stats():
    stats = queue_manager.get_stats()
    return {
        "pending": stats.pending,
        "processing": stats.processing,
        "done": stats.done,
        "failed": stats.failed,
        "total": stats.total,
        "queue_size": stats.queue_size,
        "max_queue_size": get_queue_max_size(),
    }


@app.post("/tasks", status_code=202)
async def submit_task(
    files: list[UploadFile],
    backend: str = "pipeline",
    parse_method: str = "auto",
    lang_list: str = "ch",
    formula_enable: bool = True,
    table_enable: bool = True,
    image_analysis: bool = True,
    effort: str = "high",
    start_page_id: int = 0,
    end_page_id: int = 99999,
):
    """Submit a new parsing task to the queue."""
    if not files:
        raise HTTPException(status_code=400, detail="At least one file is required")

    # For now, only support single file uploads
    upload = files[0]
    filename = upload.filename or "unknown.pdf"
    file_content = await upload.read()
    file_size = len(file_content)

    # Save uploaded file to temp
    file_path = TMP_DIR / f"{filename.replace(' ', '_')}"
    file_path.write_bytes(file_content)

    # Parse lang_list from comma-separated string
    lang_list_parsed = [lang.strip() for lang in lang_list.split(",") if lang.strip()]

    # Create task
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

    # Move temp file to task-named file
    task_file_path = TMP_DIR / f"{task.task_id}_{filename.replace(' ', '_')}"
    file_path.rename(task_file_path)

    # Submit to queue
    position = queue_manager.submit_task(task)

    if position < 0:
        raise HTTPException(
            status_code=503,
            detail=f"Queue is full (max {get_queue_max_size()})"
        )

    response = task_to_response(task)
    response["queued_ahead"] = position - 1  # 0-based ahead count
    response["message"] = "Task submitted successfully"

    return JSONResponse(status_code=202, content=response)


@app.delete("/tasks", status_code=204)
async def clear_all_tasks():
    """Clear all tasks from the queue."""
    queue_manager.clear_all_tasks()
    return None


@app.get("/tasks")
async def list_tasks():
    """Get all tasks in the queue."""
    tasks = queue_manager.get_all_tasks()
    return [task_to_response(task) for task in tasks]


@app.get("/tasks/{task_id}")
async def get_task(task_id: str):
    """Get a single task by ID."""
    task = queue_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return task_to_response(task)


@app.get("/tasks/{task_id}/result")
async def get_task_result(task_id: str):
    """Download the result ZIP for a completed task."""
    task = queue_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    if task.status != TaskStatus.done.value:
        raise HTTPException(
            status_code=400,
            detail=f"Task is not completed (status: {task.status})"
        )
    if not task.result_dir:
        raise HTTPException(status_code=404, detail="Result directory not found")

    result_zip = Path(task.result_dir) / "result.zip"
    if not result_zip.exists():
        # Try to create it on the fly
        result_dir = Path(task.result_dir)
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

    return FileResponse(
        path=str(result_zip),
        media_type="application/zip",
        filename=f"{task.filename}_result.zip",
    )


@app.delete("/tasks/{task_id}", status_code=204)
async def delete_task(task_id: str):
    """Delete/cancel a task."""
    task = queue_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    if task.status == TaskStatus.waiting.value:
        queue_manager.cancel_task(task_id)
    else:
        queue_manager.delete_task(task_id)
        # Also clean up files
        if task.result_dir:
            shutil.rmtree(task.result_dir, ignore_errors=True)

    # Clean up temp file
    temp_file = TMP_DIR / f"{task_id}_{task.filename.replace(' ', '_')}"
    if temp_file.exists():
        temp_file.unlink()

    return None


@app.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str):
    """Cancel a waiting task."""
    task = queue_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    if task.status != TaskStatus.waiting.value:
        raise HTTPException(
            status_code=400,
            detail=f"Can only cancel waiting tasks (current status: {task.status})"
        )

    success = queue_manager.cancel_task(task_id)
    return {"cancelled": success}


def run_server(host: str = "0.0.0.0", port: int = 8403):
    """Run the queue service."""
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    port = int(os.getenv("MINERU_QUEUE_PORT", "8403"))
    host = os.getenv("MINERU_QUEUE_HOST", "0.0.0.0")
    run_server(host=host, port=port)