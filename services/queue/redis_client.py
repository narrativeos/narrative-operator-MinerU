# Redis client wrapper for queue service
import json
import os
import time
from typing import Optional

import redis

from .models import QueueTask, TaskStatus, QueueStats


# Redis key prefixes
TASK_KEY_PREFIX = "mineru:queue:task:"
PENDING_LIST = "mineru:queue:pending"
PROCESSING_SET = "mineru:queue:processing"
DONE_SET = "mineru:queue:done"
FAILED_SET = "mineru:queue:failed"


def get_redis_client() -> redis.Redis:
    host = os.getenv("MINERU_REDIS_HOST", "127.0.0.1")
    port = int(os.getenv("MINERU_REDIS_PORT", "6379"))
    db = int(os.getenv("MINERU_REDIS_DB", "0"))
    password = os.getenv("MINERU_REDIS_PASSWORD", None)
    return redis.Redis(host=host, port=port, db=db, password=password, decode_responses=True)


def get_queue_max_size() -> int:
    return int(os.getenv("MINERU_QUEUE_MAX_SIZE", "20"))


def get_result_ttl() -> int:
    return int(os.getenv("MINERU_QUEUE_RESULT_TTL", "86400"))


def get_output_root() -> str:
    return os.getenv("MINERU_QUEUE_OUTPUT_ROOT", "./output")


class RedisQueueManager:
    def __init__(self):
        self._client: Optional[redis.Redis] = None

    @property
    def client(self) -> redis.Redis:
        if self._client is None:
            self._client = get_redis_client()
        return self._client

    def submit_task(self, task: QueueTask) -> int:
        """Submit a task to the queue. Returns queue position (1-based)."""
        max_size = get_queue_max_size()
        current_size = self.client.llen(PENDING_LIST)
        
        if current_size >= max_size:
            task.status = TaskStatus.failed.value
            task.error = f"Queue is full (max {max_size})"
            self._save_task(task)
            return -1

        task_key = f"{TASK_KEY_PREFIX}{task.task_id}"
        result_ttl = get_result_ttl()
        
        # Save task info
        self._save_task(task)
        
        # Add to pending queue
        self.client.rpush(PENDING_LIST, task.task_id)
        self.client.expire(task_key, result_ttl)
        
        # Return position in queue
        position = self.client.llen(PENDING_LIST)
        return position

    def get_next_task(self) -> Optional[QueueTask]:
        """Get the next task from the pending queue."""
        task_id = self.client.lpop(PENDING_LIST)
        if not task_id:
            return None
        
        task = self._get_task(task_id)
        if not task:
            return None
        
        # Update status
        task.status = TaskStatus.parsing.value
        task.started_at = time.time()
        self._save_task(task)
        
        # Move to processing set
        self.client.sadd(PROCESSING_SET, task_id)
        
        return task

    def complete_task(self, task: QueueTask, result_dir: str) -> None:
        """Mark a task as completed."""
        task.status = TaskStatus.done.value
        task.completed_at = time.time()
        task.result_dir = result_dir
        self._save_task(task)
        
        # Move sets
        self.client.srem(PROCESSING_SET, task.task_id)
        self.client.sadd(DONE_SET, task.task_id)

    def fail_task(self, task: QueueTask, error: str) -> None:
        """Mark a task as failed."""
        task.status = TaskStatus.failed.value
        task.completed_at = time.time()
        task.error = error
        self._save_task(task)
        
        # Move sets
        self.client.srem(PROCESSING_SET, task.task_id)
        self.client.sadd(FAILED_SET, task.task_id)

    def cancel_task(self, task_id: str) -> bool:
        """Cancel a waiting task."""
        # Try to remove from pending list
        removed = self.client.lrem(PENDING_LIST, 1, task_id)
        if removed:
            task = self._get_task(task_id)
            if task:
                task.status = TaskStatus.cancelled.value
                task.completed_at = time.time()
                self._save_task(task)
            return True
        return False

    def delete_task(self, task_id: str) -> bool:
        """Delete a task completely."""
        task_key = f"{TASK_KEY_PREFIX}{task_id}"
        self.client.delete(task_key)
        self.client.lrem(PENDING_LIST, 1, task_id)
        self.client.srem(PROCESSING_SET, task_id)
        self.client.srem(DONE_SET, task_id)
        self.client.srem(FAILED_SET, task_id)
        return True

    def get_task(self, task_id: str) -> Optional[QueueTask]:
        """Get a single task by ID."""
        return self._get_task(task_id)

    def get_all_tasks(self) -> list[QueueTask]:
        """Get all tasks with their current queue positions."""
        all_task_ids = set()
        
        # Collect all task IDs from all sets/lists
        for task_id in self.client.lrange(PENDING_LIST, 0, -1):
            all_task_ids.add(task_id)
        for task_id in self.client.smembers(PROCESSING_SET):
            all_task_ids.add(task_id)
        for task_id in self.client.smembers(DONE_SET):
            all_task_ids.add(task_id)
        for task_id in self.client.smembers(FAILED_SET):
            all_task_ids.add(task_id)
        
        tasks = []
        pending_list = self.client.lrange(PENDING_LIST, 0, -1)
        
        for idx, task_id in enumerate(pending_list):
            task = self._get_task(task_id)
            if task:
                task.queue_position = idx + 1
                tasks.append(task)
        
        # Add processing tasks
        for task_id in self.client.smembers(PROCESSING_SET):
            if task_id not in pending_list:
                task = self._get_task(task_id)
                if task:
                    tasks.append(task)
        
        # Add done/failed tasks
        for task_id in self.client.smembers(DONE_SET) | self.client.smembers(FAILED_SET):
            if task_id not in pending_list and task_id not in self.client.smembers(PROCESSING_SET):
                task = self._get_task(task_id)
                if task:
                    tasks.append(task)
        
        # Sort by created_at descending
        tasks.sort(key=lambda t: t.created_at, reverse=True)
        return tasks

    def get_stats(self) -> QueueStats:
        """Get queue statistics."""
        pending = self.client.llen(PENDING_LIST)
        processing = self.client.scard(PROCESSING_SET)
        done = self.client.scard(DONE_SET)
        failed = self.client.scard(FAILED_SET)
        
        return QueueStats(
            pending=pending,
            processing=processing,
            done=done,
            failed=failed,
            total=pending + processing + done + failed,
            queue_size=pending,
        )

    def _save_task(self, task: QueueTask) -> None:
        """Save task to Redis."""
        task_key = f"{TASK_KEY_PREFIX}{task.task_id}"
        result_ttl = get_result_ttl()
        self.client.set(task_key, json.dumps(task.to_dict(), ensure_ascii=False), ex=result_ttl)

    def _get_task(self, task_id: str) -> Optional[QueueTask]:
        """Get task from Redis."""
        task_key = f"{TASK_KEY_PREFIX}{task_id}"
        data = self.client.get(task_key)
        if not data:
            return None
        try:
            return QueueTask.from_dict(json.loads(data))
        except Exception:
            return None

    def clear_all_tasks(self) -> int:
        """Clear all tasks from the queue. Returns number of cleared tasks."""
        all_task_ids = set()
        # Collect all task IDs
        all_task_ids.update(self.client.lrange(PENDING_LIST, 0, -1))
        all_task_ids.update(self.client.smembers(PROCESSING_SET))
        all_task_ids.update(self.client.smembers(DONE_SET))
        all_task_ids.update(self.client.smembers(FAILED_SET))
        
        # Clear all collections
        self.client.delete(PENDING_LIST)
        self.client.delete(PROCESSING_SET)
        self.client.delete(DONE_SET)
        self.client.delete(FAILED_SET)
        
        # Delete all task keys
        for task_id in all_task_ids:
            self.client.delete(f"{TASK_KEY_PREFIX}{task_id}")
        
        return len(all_task_ids)

    def cleanup_expired(self) -> int:
        """Clean up expired tasks. Returns number of cleaned tasks."""
        cleaned = 0
        for task_set in [DONE_SET, FAILED_SET]:
            for task_id in list(self.client.smembers(task_set)):
                task_key = f"{TASK_KEY_PREFIX}{task_id}"
                if self.client.ttl(task_key) == -1 or self.client.ttl(task_key) == -2:
                    self.client.srem(task_set, task_id)
                    self.client.delete(task_key)
                    cleaned += 1
        return cleaned


# Global queue manager instance
queue_manager = RedisQueueManager()