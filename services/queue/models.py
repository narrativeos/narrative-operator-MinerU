'''
Author: Future Meng futuremeng@gmail.com
Date: 2026-06-25 20:42:22
LastEditors: Future Meng futuremeng@gmail.com
LastEditTime: 2026-06-25 20:42:35
FilePath: /narrative-operator-MinerU/services/queue/models.py
Description: 这是默认设置,请设置`customMade`, 打开koroFileHeader查看配置 进行设置: https://github.com/OBKoro1/koro1FileHeader/wiki/%E9%85%8D%E7%BD%AE
'''
# Queue service data models
import enum
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Optional


class TaskStatus(str, enum.Enum):
    waiting = "waiting"
    parsing = "parsing"
    done = "done"
    failed = "failed"
    cancelled = "cancelled"


@dataclass
class QueueTask:
    task_id: str
    filename: str
    file_size: int
    status: str = TaskStatus.waiting.value
    # Parse options
    backend: str = "pipeline"
    parse_method: str = "auto"
    lang_list: list = field(default_factory=lambda: ["ch"])
    formula_enable: bool = True
    table_enable: bool = True
    image_analysis: bool = True
    effort: str = "high"
    start_page_id: int = 0
    end_page_id: int = 99999
    # Timestamps
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    # Results
    error: Optional[str] = None
    result_dir: Optional[str] = None
    # Queue position (computed on demand)
    queue_position: Optional[int] = None
    # Internal queue order (used by SQLite backend for FIFO ordering)
    _queue_order: Optional[int] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "QueueTask":
        # Handle fields that might be missing from older data
        defaults = {
            "effort": "high",
            "image_analysis": True,
            "formula_enable": True,
            "table_enable": True,
            "start_page_id": 0,
            "end_page_id": 99999,
            "queue_position": None,
        }
        for key, value in defaults.items():
            data.setdefault(key, value)
        return cls(**data)

    @staticmethod
    def generate_id() -> str:
        return uuid.uuid4().hex[:16]


@dataclass
class QueueStats:
    pending: int = 0
    processing: int = 0
    done: int = 0
    failed: int = 0
    total: int = 0
    queue_size: int = 0