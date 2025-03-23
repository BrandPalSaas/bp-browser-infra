from pydantic import BaseModel
from typing import Dict, List, Optional, Any
from enum import Enum

# Session and Profile models (controller-only)
class BrowserTaskDomain(str, Enum):
    TTS = "tiktokshop"

# Task status
class BrowserTaskStatus(str, Enum):
    WAITING = "waiting"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

class BrowserTaskRequest(BaseModel):
    """Model for a browser task request."""
    task_description: str
    task_domain: BrowserTaskDomain

class BrowserTaskResponse(BaseModel):
    """Model for a task execution response."""
    task_id: str
    task_status: BrowserTaskStatus
    worker_name: Optional[str] = None
    task_response: Optional[str] = None

class RawResponse(BaseModel):
    total_duration_seconds: float
    total_input_tokens: int
    num_of_steps: int
    is_successful: bool
    has_errors: bool
    final_result: Optional[str] = None


class TaskEntry(BaseModel):
    task_id: str
    request: BrowserTaskRequest
    response: BrowserTaskResponse
    created_at: str
    start_at: Optional[str] = None
    end_at: Optional[str] = None
    
    