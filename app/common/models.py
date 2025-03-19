from pydantic import BaseModel
from typing import Dict, List, Optional, Any
from datetime import datetime
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
    task_response: str


class TaskEntry(BaseModel):
    task_id: str
    request: BrowserTaskResponse
    response: BrowserTaskResponse
    created_at: str
    start_at: str
    end_at: str
    
    