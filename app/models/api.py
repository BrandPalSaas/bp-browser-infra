from pydantic import BaseModel
from typing import Optional
from enum import Enum
from app.models.tts import TTShop

class TTSTask(BaseModel):
    shop: TTShop

class BrowserTaskStatus(str, Enum):
    WAITING = "waiting"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

class BrowserTaskRequest(BaseModel):
    """Model for a browser task request."""
    task_description: str
    task: TTSTask

    def task_queue_name(self) -> str:
        return self.task.shop.task_queue_name()

class BrowserTaskResponse(BaseModel):
    """Model for a task execution response."""
    task_id: str
    task_status: BrowserTaskStatus
    worker_name: Optional[str] = None
    task_response: Optional[str] = None 