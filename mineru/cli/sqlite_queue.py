# SQLite-based persistent task queue for MinerU FastAPI
# Replaces in-memory queue with SQLite for persistence across restarts

import json
import os
import sqlite3
import time
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from loguru import logger


DEFAULT_DB_PATH = os.getenv("MINERU_QUEUE_DB_PATH", "./output/mineru_queue.db")
DEFAULT_MAX_SIZE = int(os.getenv("MINERU_QUEUE_MAX_SIZE", "20"))
DEFAULT_RESULT_TTL = int(os.getenv("MINERU_QUEUE_RESULT_TTL", "86400"))  # 24 hours


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _format_ts(ts: Optional[float]) -> Optional[str]:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%dT%H:%M:%S")


class SQLiteQueueTask:
    """A task stored in SQLite queue."""

    def __init__(
        self,
        task_id: str,
        filename: str,
        file_size: int,
        backend: str = "pipeline",
        parse_method: str = "auto",
        lang_list: Optional[list] = None,
        formula_enable: bool = True,
        table_enable: bool = True,
        image_analysis: bool = True,
        effort: str = "high",
        start_page_id: int = 0,
        end_page_id: int = 99999,
        status: str = "waiting",
        created_at: Optional[float] = None,
        started_at: Optional[float] = None,
        completed_at: Optional[float] = None,
        error: Optional[str] = None,
        result_dir: Optional[str] = None,
        queue_order: Optional[int] = None,
        # Additional fields for FastAPI compatibility
        file_names: Optional[list] = None,
        output_dir: Optional[str] = None,
        return_md: bool = True,
        return_middle_json: bool = False,
        return_model_output: bool = False,
        return_content_list: bool = False,
        return_images: bool = False,
        response_format_zip: bool = False,
        return_original_file: bool = False,
        client_side_output_generation: bool = False,
        server_url: Optional[str] = None,
        upload_names: Optional[list] = None,
        uploads: Optional[list] = None,
        submit_order: int = 0,
        # Progress tracking fields
        progress_percent: int = 0,
        current_page: int = 0,
        total_pages: int = 0,
        current_stage: Optional[str] = None,
    ):
        self.task_id = task_id
        self.filename = filename
        self.file_size = file_size
        self.backend = backend
        self.parse_method = parse_method
        self.lang_list = lang_list or ["ch"]
        self.formula_enable = formula_enable
        self.table_enable = table_enable
        self.image_analysis = image_analysis
        self.effort = effort
        self.start_page_id = start_page_id
        self.end_page_id = end_page_id
        self.status = status
        self.created_at = created_at or time.time()
        self.started_at = started_at
        self.completed_at = completed_at
        self.error = error
        self.result_dir = result_dir
        self.queue_order = queue_order
        self.file_names = file_names or [Path(filename).stem]
        self.output_dir = output_dir
        self.return_md = return_md
        self.return_middle_json = return_middle_json
        self.return_model_output = return_model_output
        self.return_content_list = return_content_list
        self.return_images = return_images
        self.response_format_zip = response_format_zip
        self.return_original_file = return_original_file
        self.client_side_output_generation = client_side_output_generation
        self.server_url = server_url
        self.upload_names = upload_names or [filename]
        self.uploads = uploads or []
        self.submit_order = submit_order
        # Progress tracking
        self.progress_percent = progress_percent
        self.current_page = current_page
        self.total_pages = total_pages
        self.current_stage = current_stage

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "filename": self.filename,
            "file_size": self.file_size,
            "status": self.status,
            "queue_position": self.queue_order,
            "backend": self.backend,
            "parse_method": self.parse_method,
            "lang_list": self.lang_list,
            "formula_enable": self.formula_enable,
            "table_enable": self.table_enable,
            "image_analysis": self.image_analysis,
            "effort": self.effort,
            "start_page_id": self.start_page_id,
            "end_page_id": self.end_page_id,
            "created_at": _format_ts(self.created_at),
            "started_at": _format_ts(self.started_at),
            "completed_at": _format_ts(self.completed_at),
            "error": self.error,
            "result_dir": self.result_dir,
        }

    def to_status_payload(self, request, queued_ahead: int | None = None) -> dict:
        payload = {
            "task_id": self.task_id,
            "status": self.status,
            "backend": self.backend,
            "file_names": self.file_names,
            "created_at": _format_ts(self.created_at) or utc_now_iso(),
            "started_at": _format_ts(self.started_at) or utc_now_iso() if self.started_at else None,
            "completed_at": _format_ts(self.completed_at) or utc_now_iso() if self.completed_at else None,
            "error": self.error,
            "status_url": str(
                request.url_for("get_async_task_status", task_id=self.task_id)
            ),
            "result_url": str(
                request.url_for("get_async_task_result", task_id=self.task_id)
            ),
        }
        # Add progress information
        payload["progress"] = {
            "percent": self.progress_percent,
            "current_page": self.current_page,
            "total_pages": self.total_pages,
            "stage": self.current_stage,
        }
        if queued_ahead is not None:
            payload["queued_ahead"] = queued_ahead
        return payload


class SQLiteQueueManager:
    """Thread-safe SQLite-based queue manager for FastAPI."""

    def __init__(self, db_path: Optional[str] = None):
        self._db_path = db_path or DEFAULT_DB_PATH
        self._local = threading.local()
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self._db_path)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA busy_timeout=5000")
        return self._local.conn

    @property
    def conn(self) -> sqlite3.Connection:
        return self._get_conn()

    def _init_db(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                file_size INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'waiting',
                backend TEXT DEFAULT 'pipeline',
                parse_method TEXT DEFAULT 'auto',
                lang_list TEXT DEFAULT '["ch"]',
                formula_enable INTEGER DEFAULT 1,
                table_enable INTEGER DEFAULT 1,
                image_analysis INTEGER DEFAULT 1,
                effort TEXT DEFAULT 'high',
                start_page_id INTEGER DEFAULT 0,
                end_page_id INTEGER DEFAULT 99999,
                created_at REAL NOT NULL,
                started_at REAL,
                completed_at REAL,
                error TEXT,
                result_dir TEXT,
                queue_order INTEGER,
                file_names TEXT,
                output_dir TEXT,
                return_md INTEGER DEFAULT 1,
                return_middle_json INTEGER DEFAULT 0,
                return_model_output INTEGER DEFAULT 0,
                return_content_list INTEGER DEFAULT 0,
                return_images INTEGER DEFAULT 0,
                response_format_zip INTEGER DEFAULT 0,
                return_original_file INTEGER DEFAULT 0,
                client_side_output_generation INTEGER DEFAULT 0,
                server_url TEXT,
                upload_names TEXT,
                uploads TEXT,
                submit_order INTEGER DEFAULT 0
            )
        """)
        # Schema migration: add columns that may be missing from older databases
        self._ensure_column("submit_order", "INTEGER DEFAULT 0")
        self._ensure_column("file_names", "TEXT")
        self._ensure_column("output_dir", "TEXT")
        self._ensure_column("return_md", "INTEGER DEFAULT 1")
        self._ensure_column("return_middle_json", "INTEGER DEFAULT 0")
        self._ensure_column("return_model_output", "INTEGER DEFAULT 0")
        self._ensure_column("return_content_list", "INTEGER DEFAULT 0")
        self._ensure_column("return_images", "INTEGER DEFAULT 0")
        self._ensure_column("response_format_zip", "INTEGER DEFAULT 0")
        self._ensure_column("return_original_file", "INTEGER DEFAULT 0")
        self._ensure_column("client_side_output_generation", "INTEGER DEFAULT 0")
        self._ensure_column("server_url", "TEXT")
        self._ensure_column("upload_names", "TEXT")
        self._ensure_column("uploads", "TEXT")
        # Progress tracking columns
        self._ensure_column("progress_percent", "INTEGER DEFAULT 0")
        self._ensure_column("current_page", "INTEGER DEFAULT 0")
        self._ensure_column("total_pages", "INTEGER DEFAULT 0")
        self._ensure_column("current_stage", "TEXT")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_status_order ON tasks(status, queue_order)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON tasks(status)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_submit_order ON tasks(submit_order)")
        self.conn.commit()

    def _ensure_column(self, column_name: str, column_def: str) -> None:
        """Add a column if it doesn't exist (schema migration)."""
        try:
            cursor = self.conn.execute(f"PRAGMA table_info(tasks)")
            columns = [row["name"] for row in cursor.fetchall()]
            if column_name not in columns:
                self.conn.execute(f"ALTER TABLE tasks ADD COLUMN {column_name} {column_def}")
        except Exception:
            pass

    def _row_to_task(self, row: sqlite3.Row) -> SQLiteQueueTask:
        d = dict(row)

        def parse_json(val, default=None):
            if isinstance(val, str):
                try:
                    return json.loads(val)
                except json.JSONDecodeError:
                    return default
            return default

        return SQLiteQueueTask(
            task_id=d["task_id"],
            filename=d["filename"],
            file_size=d["file_size"],
            status=d["status"],
            backend=d.get("backend", "pipeline"),
            parse_method=d.get("parse_method", "auto"),
            lang_list=parse_json(d.get("lang_list"), ["ch"]),
            formula_enable=bool(d.get("formula_enable", 1)),
            table_enable=bool(d.get("table_enable", 1)),
            image_analysis=bool(d.get("image_analysis", 1)),
            effort=d.get("effort", "high"),
            start_page_id=d.get("start_page_id", 0),
            end_page_id=d.get("end_page_id", 99999),
            created_at=d.get("created_at"),
            started_at=d.get("started_at"),
            completed_at=d.get("completed_at"),
            error=d.get("error"),
            result_dir=d.get("result_dir"),
            queue_order=d.get("queue_order"),
            file_names=parse_json(d.get("file_names")),
            output_dir=d.get("output_dir"),
            return_md=bool(d.get("return_md", 1)),
            return_middle_json=bool(d.get("return_middle_json", 0)),
            return_model_output=bool(d.get("return_model_output", 0)),
            return_content_list=bool(d.get("return_content_list", 0)),
            return_images=bool(d.get("return_images", 0)),
            response_format_zip=bool(d.get("response_format_zip", 0)),
            return_original_file=bool(d.get("return_original_file", 0)),
            client_side_output_generation=bool(d.get("client_side_output_generation", 0)),
            server_url=d.get("server_url"),
            upload_names=parse_json(d.get("upload_names")),
            uploads=parse_json(d.get("uploads")),
            submit_order=d.get("submit_order", 0),
            progress_percent=d.get("progress_percent", 0) or 0,
            current_page=d.get("current_page", 0) or 0,
            total_pages=d.get("total_pages", 0) or 0,
            current_stage=d.get("current_stage"),
        )

    def _save_task(self, task: SQLiteQueueTask) -> None:
        with self.conn:
            self.conn.execute("""
                INSERT INTO tasks (
                    task_id, filename, file_size, status, backend, parse_method,
                    lang_list, formula_enable, table_enable, image_analysis,
                    effort, start_page_id, end_page_id, created_at, started_at,
                    completed_at, error, result_dir, queue_order, file_names,
                    output_dir, return_md, return_middle_json, return_model_output,
                    return_content_list, return_images, response_format_zip,
                    return_original_file, client_side_output_generation, server_url,
                    upload_names, uploads, submit_order,
                    progress_percent, current_page, total_pages, current_stage
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    filename=excluded.filename, file_size=excluded.file_size,
                    status=excluded.status, backend=excluded.backend,
                    parse_method=excluded.parse_method, lang_list=excluded.lang_list,
                    formula_enable=excluded.formula_enable, table_enable=excluded.table_enable,
                    image_analysis=excluded.image_analysis, effort=excluded.effort,
                    start_page_id=excluded.start_page_id, end_page_id=excluded.end_page_id,
                    created_at=excluded.created_at, started_at=excluded.started_at,
                    completed_at=excluded.completed_at, error=excluded.error,
                    result_dir=excluded.result_dir, queue_order=excluded.queue_order,
                    file_names=excluded.file_names, output_dir=excluded.output_dir,
                    return_md=excluded.return_md, return_middle_json=excluded.return_middle_json,
                    return_model_output=excluded.return_model_output,
                    return_content_list=excluded.return_content_list,
                    return_images=excluded.return_images,
                    response_format_zip=excluded.response_format_zip,
                    return_original_file=excluded.return_original_file,
                    client_side_output_generation=excluded.client_side_output_generation,
                    server_url=excluded.server_url, upload_names=excluded.upload_names,
                    uploads=excluded.uploads, submit_order=excluded.submit_order,
                    progress_percent=excluded.progress_percent,
                    current_page=excluded.current_page,
                    total_pages=excluded.total_pages,
                    current_stage=excluded.current_stage
            """, (
                task.task_id, task.filename, task.file_size, task.status,
                task.backend, task.parse_method,
                json.dumps(task.lang_list), int(task.formula_enable),
                int(task.table_enable), int(task.image_analysis),
                task.effort, task.start_page_id, task.end_page_id,
                task.created_at, task.started_at, task.completed_at,
                task.error, task.result_dir, task.queue_order,
                json.dumps(task.file_names) if task.file_names else None,
                task.output_dir, int(task.return_md), int(task.return_middle_json),
                int(task.return_model_output), int(task.return_content_list),
                int(task.return_images), int(task.response_format_zip),
                int(task.return_original_file), int(task.client_side_output_generation),
                task.server_url,
                json.dumps(task.upload_names) if task.upload_names else None,
                json.dumps(task.uploads) if task.uploads else None,
                task.submit_order,
                task.progress_percent,
                task.current_page,
                task.total_pages,
                task.current_stage,
            ))

    def submit_task(self, task: SQLiteQueueTask) -> int:
        max_size = DEFAULT_MAX_SIZE
        current_waiting = self._count_waiting()

        if current_waiting >= max_size:
            task.status = "failed"
            task.error = f"Queue is full (max {max_size})"
            task.completed_at = time.time()
            self._save_task(task)
            return -1

        cursor = self.conn.execute("SELECT COALESCE(MAX(queue_order), 0) FROM tasks")
        next_order = cursor.fetchone()[0] + 1
        task.queue_order = next_order
        task.submit_order = next_order
        self._save_task(task)
        return self._count_waiting()

    def get_next_task(self) -> Optional[SQLiteQueueTask]:
        with self.conn:
            cursor = self.conn.execute(
                "SELECT * FROM tasks WHERE status='waiting' ORDER BY queue_order ASC LIMIT 1"
            )
            row = cursor.fetchone()
            if not row:
                return None

            task = self._row_to_task(row)
            self.conn.execute(
                "UPDATE tasks SET status='processing', started_at=? WHERE task_id=?",
                (time.time(), task.task_id),
            )
            task.status = "processing"
            task.started_at = time.time()
            self._save_task(task)
            return task

    def complete_task(self, task: SQLiteQueueTask, result_dir: str) -> None:
        task.status = "completed"
        task.completed_at = time.time()
        task.result_dir = result_dir
        self._save_task(task)

    def fail_task(self, task: SQLiteQueueTask, error: str) -> None:
        task.status = "failed"
        task.completed_at = time.time()
        task.error = error
        self._save_task(task)

    def get_task(self, task_id: str) -> Optional[SQLiteQueueTask]:
        cursor = self.conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_task(row)

    def get_all_tasks(self) -> list[SQLiteQueueTask]:
        cursor = self.conn.execute("SELECT * FROM tasks ORDER BY queue_order DESC")
        tasks = []
        waiting_tasks = []
        for row in cursor.fetchall():
            task = self._row_to_task(row)
            if task.status == "waiting":
                waiting_tasks.append(task)
            tasks.append(task)

        waiting_tasks.sort(key=lambda t: t.queue_order or 0)
        for idx, task in enumerate(waiting_tasks):
            task.queue_order = idx + 1
        return tasks

    def get_stats(self) -> dict:
        stats = {"pending": 0, "processing": 0, "completed": 0, "failed": 0}
        cursor = self.conn.execute("SELECT status, COUNT(*) as cnt FROM tasks GROUP BY status")
        for row in cursor.fetchall():
            status = row[0]
            count = row[1]
            if status == "waiting":
                stats["pending"] = count
            elif status == "processing":
                stats["processing"] = count
            elif status == "completed":
                stats["completed"] = count
            elif status == "failed":
                stats["failed"] = count
            elif status == "cancelled":
                stats["failed"] += count
        return stats

    def cancel_task(self, task_id: str) -> bool:
        with self.conn:
            cursor = self.conn.execute(
                "SELECT status FROM tasks WHERE task_id=? AND status='waiting'",
                (task_id,),
            )
            row = cursor.fetchone()
            if not row:
                return False
            self.conn.execute(
                "UPDATE tasks SET status='cancelled', completed_at=? WHERE task_id=?",
                (time.time(), task_id),
            )
        return True

    def delete_task(self, task_id: str) -> bool:
        with self.conn:
            self.conn.execute("DELETE FROM tasks WHERE task_id=?", (task_id,))
        return True

    def clear_all_tasks(self) -> int:
        cursor = self.conn.execute("SELECT COUNT(*) FROM tasks")
        count = cursor.fetchone()[0]
        with self.conn:
            self.conn.execute("DELETE FROM tasks")
        return count

    def cleanup_expired(self, ttl: int = DEFAULT_RESULT_TTL) -> int:
        cutoff = time.time() - ttl
        cleaned = 0
        with self.conn:
            for status in ["completed", "failed", "cancelled"]:
                cursor = self.conn.execute(
                    "SELECT task_id FROM tasks WHERE status=? AND completed_at<?",
                    (status, cutoff),
                )
                for row in cursor.fetchall():
                    self.conn.execute("DELETE FROM tasks WHERE task_id=?", (row[0],))
                    cleaned += 1
        return cleaned

    def _count_waiting(self) -> int:
        cursor = self.conn.execute("SELECT COUNT(*) FROM tasks WHERE status='waiting'")
        return cursor.fetchone()[0]

    def get_queued_ahead(self, task_id: str) -> int | None:
        task = self.get_task(task_id)
        if task is None:
            return None
        if task.status != "waiting":
            return 0
        return sum(
            1
            for t in self.get_all_tasks()
            if t.status == "waiting" and t.task_id != task_id and (t.submit_order or 0) < task.submit_order
        )


# Global queue manager instance
queue_manager = SQLiteQueueManager()