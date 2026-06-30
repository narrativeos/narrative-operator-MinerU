# SQLite-based queue manager for queue service
# Replaces Redis with SQLite for local development (no Docker required)

import json
import os
import sqlite3
import time
import threading
from pathlib import Path
from typing import Optional

from .models import QueueTask, TaskStatus, QueueStats


# Database file path
DEFAULT_DB_PATH = os.getenv("MINERU_QUEUE_DB_PATH", "./output/mineru_queue.db")


def get_db_path() -> str:
    return os.getenv("MINERU_QUEUE_DB_PATH", "./output/mineru_queue.db")


def get_queue_max_size() -> int:
    return int(os.getenv("MINERU_QUEUE_MAX_SIZE", "20"))


def get_result_ttl() -> int:
    return int(os.getenv("MINERU_QUEUE_RESULT_TTL", "86400"))


def get_output_root() -> str:
    return os.getenv("MINERU_QUEUE_OUTPUT_ROOT", "./output")


def init_db(conn: sqlite3.Connection) -> None:
    """Initialize the SQLite database schema."""
    conn.execute("PRAGMA journal_mode=WAL")  # Better concurrency
    conn.execute("PRAGMA busy_timeout=5000")  # Wait up to 5s for locks
    conn.execute("""
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
            queue_order INTEGER
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_status_order ON tasks(status, queue_order)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON tasks(status)")
    conn.commit()


class SQLiteQueueManager:
    """Thread-safe SQLite-based queue manager.
    
    Each thread gets its own database connection to avoid SQLite's
    "objects created in a thread can only be used in that same thread" error.
    """

    def __init__(self, db_path: Optional[str] = None):
        self._db_path = db_path or get_db_path()
        self._local = threading.local()
        # Ensure the directory exists
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        # Initialize DB in the current thread (creates schema if needed)
        _conn = self._get_conn()
        init_db(_conn)

    def _get_conn(self) -> sqlite3.Connection:
        """Get a thread-local database connection."""
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = sqlite3.connect(self._db_path)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA busy_timeout=5000")
        return self._local.conn

    @property
    def conn(self) -> sqlite3.Connection:
        return self._get_conn()

    def _row_to_task(self, row: sqlite3.Row) -> QueueTask:
        """Convert a database row to a QueueTask."""
        d = dict(row)
        # Map queue_order from DB to _queue_order on the model
        if 'queue_order' in d:
            d['_queue_order'] = d.pop('queue_order')
        # Parse lang_list from JSON string
        if isinstance(d.get('lang_list'), str):
            try:
                d['lang_list'] = json.loads(d['lang_list'])
            except json.JSONDecodeError:
                d['lang_list'] = ["ch"]
        # Convert boolean fields
        for field in ['formula_enable', 'table_enable', 'image_analysis']:
            if d.get(field) is not None:
                d[field] = bool(d[field])
        return QueueTask.from_dict(d)

    def _task_to_values(self, task: QueueTask) -> dict:
        """Convert a QueueTask to values for database storage."""
        return {
            'task_id': task.task_id,
            'filename': task.filename,
            'file_size': task.file_size,
            'status': task.status,
            'backend': task.backend,
            'parse_method': task.parse_method,
            'lang_list': json.dumps(task.lang_list, ensure_ascii=False),
            'formula_enable': int(task.formula_enable),
            'table_enable': int(task.table_enable),
            'image_analysis': int(task.image_analysis),
            'effort': task.effort,
            'start_page_id': task.start_page_id,
            'end_page_id': task.end_page_id,
            'created_at': task.created_at,
            'started_at': task.started_at,
            'completed_at': task.completed_at,
            'error': task.error,
            'result_dir': task.result_dir,
        }

    def submit_task(self, task: QueueTask) -> int:
        """Submit a task to the queue. Returns queue position (1-based)."""
        max_size = get_queue_max_size()
        current_size = self._count_waiting()

        if current_size >= max_size:
            task.status = TaskStatus.failed.value
            task.error = f"Queue is full (max {max_size})"
            self._save_task(task)
            return -1

        # Get the next queue_order
        cursor = self.conn.execute("SELECT COALESCE(MAX(queue_order), 0) FROM tasks")
        next_order = cursor.fetchone()[0] + 1

        task._queue_order = next_order
        self._save_task(task)

        # Return position in queue (number of waiting tasks)
        position = self._count_waiting()
        return position

    def get_next_task(self) -> Optional[QueueTask]:
        """Get the next task from the pending queue (atomic)."""
        with self.conn:  # Transaction
            cursor = self.conn.execute(
                "SELECT * FROM tasks WHERE status='waiting' ORDER BY queue_order ASC LIMIT 1"
            )
            row = cursor.fetchone()
            if not row:
                return None

            task = self._row_to_task(row)
            # Atomically update status
            self.conn.execute(
                "UPDATE tasks SET status='parsing', started_at=? WHERE task_id=?",
                (time.time(), task.task_id)
            )
            task.status = TaskStatus.parsing.value
            task.started_at = time.time()
            self._save_task(task)
            return task

    def complete_task(self, task: QueueTask, result_dir: str) -> None:
        """Mark a task as completed."""
        task.status = TaskStatus.done.value
        task.completed_at = time.time()
        task.result_dir = result_dir
        self._save_task(task)

    def fail_task(self, task: QueueTask, error: str) -> None:
        """Mark a task as failed."""
        task.status = TaskStatus.failed.value
        task.completed_at = time.time()
        task.error = error
        self._save_task(task)

    def cancel_task(self, task_id: str) -> bool:
        """Cancel a waiting task."""
        with self.conn:
            cursor = self.conn.execute(
                "SELECT status FROM tasks WHERE task_id=? AND status='waiting'",
                (task_id,)
            )
            row = cursor.fetchone()
            if not row:
                return False
            self.conn.execute(
                "UPDATE tasks SET status='cancelled', completed_at=? WHERE task_id=?",
                (time.time(), task_id)
            )
        return True

    def delete_task(self, task_id: str) -> bool:
        """Delete a task completely."""
        with self.conn:
            self.conn.execute("DELETE FROM tasks WHERE task_id=?", (task_id,))
        return True

    def get_task(self, task_id: str) -> Optional[QueueTask]:
        """Get a single task by ID."""
        cursor = self.conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_task(row)

    def get_all_tasks(self) -> list[QueueTask]:
        """Get all tasks with their current queue positions."""
        cursor = self.conn.execute(
            "SELECT * FROM tasks ORDER BY queue_order DESC"
        )
        tasks = []
        waiting_tasks = []

        for row in cursor.fetchall():
            task = self._row_to_task(row)
            if task.status == TaskStatus.waiting.value:
                waiting_tasks.append(task)
            tasks.append(task)

        # Set queue positions for waiting tasks (FIFO order)
        waiting_tasks.sort(key=lambda t: t._queue_order or 0)
        for idx, task in enumerate(waiting_tasks):
            task.queue_position = idx + 1

        return tasks

    def get_stats(self) -> QueueStats:
        """Get queue statistics."""
        cursor = self.conn.execute(
            "SELECT status, COUNT(*) as cnt FROM tasks GROUP BY status"
        )
        stats = {'pending': 0, 'processing': 0, 'done': 0, 'failed': 0}
        for row in cursor.fetchall():
            status = row[0]
            count = row[1]
            if status == 'waiting':
                stats['pending'] = count
            elif status == 'parsing':
                stats['processing'] = count
            elif status == 'done':
                stats['done'] = count
            elif status == 'failed':
                stats['failed'] = count
            elif status == 'cancelled':
                stats['failed'] += count  # Count cancelled as failed for stats

        total = sum(stats.values())
        return QueueStats(
            pending=stats['pending'],
            processing=stats['processing'],
            done=stats['done'],
            failed=stats['failed'],
            total=total,
            queue_size=stats['pending'],
        )

    def clear_all_tasks(self) -> int:
        """Clear all tasks from the queue. Returns number of cleared tasks."""
        cursor = self.conn.execute("SELECT COUNT(*) FROM tasks")
        count = cursor.fetchone()[0]
        with self.conn:
            self.conn.execute("DELETE FROM tasks")
        return count

    def cleanup_expired(self) -> int:
        """Clean up expired tasks. Returns number of cleaned tasks."""
        ttl = get_result_ttl()
        cutoff = time.time() - ttl
        cleaned = 0
        with self.conn:
            for status in ['done', 'failed', 'cancelled']:
                cursor = self.conn.execute(
                    "SELECT task_id FROM tasks WHERE status=? AND completed_at<?",
                    (status, cutoff)
                )
                for row in cursor.fetchall():
                    self.conn.execute("DELETE FROM tasks WHERE task_id=?", (row[0],))
                    cleaned += 1
        return cleaned

    def _count_waiting(self) -> int:
        """Count the number of waiting tasks."""
        cursor = self.conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE status='waiting'"
        )
        return cursor.fetchone()[0]

    def _save_task(self, task: QueueTask) -> None:
        """Save task to SQLite."""
        values = self._task_to_values(task)
        with self.conn:
            self.conn.execute("""
                INSERT INTO tasks (
                    task_id, filename, file_size, status, backend, parse_method,
                    lang_list, formula_enable, table_enable, image_analysis,
                    effort, start_page_id, end_page_id, created_at, started_at,
                    completed_at, error, result_dir, queue_order
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    filename=excluded.filename,
                    file_size=excluded.file_size,
                    status=excluded.status,
                    backend=excluded.backend,
                    parse_method=excluded.parse_method,
                    lang_list=excluded.lang_list,
                    formula_enable=excluded.formula_enable,
                    table_enable=excluded.table_enable,
                    image_analysis=excluded.image_analysis,
                    effort=excluded.effort,
                    start_page_id=excluded.start_page_id,
                    end_page_id=excluded.end_page_id,
                    created_at=excluded.created_at,
                    started_at=excluded.started_at,
                    completed_at=excluded.completed_at,
                    error=excluded.error,
                    result_dir=excluded.result_dir,
                    queue_order=excluded.queue_order
            """, (
                values['task_id'], values['filename'], values['file_size'],
                values['status'], values['backend'], values['parse_method'],
                values['lang_list'], values['formula_enable'], values['table_enable'],
                values['image_analysis'], values['effort'], values['start_page_id'],
                values['end_page_id'], values['created_at'], values['started_at'],
                values['completed_at'], values['error'], values['result_dir'],
                task._queue_order,
            ))


# Global queue manager instance
queue_manager = SQLiteQueueManager()