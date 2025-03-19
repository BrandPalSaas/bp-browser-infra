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
    task_response: str
    task_status: BrowserTaskStatus
    wait_time_in_seconds: int
    execution_time_in_seconds: int


class ProfileStatus(str, Enum):
    RUNNING = "running"
    STOPPED = "stopped"

class ProfileRequest(BaseModel):
    name: str
    proxy: Optional[str] = None
    user_agent: Optional[str] = None
    session_id: str  # Reference to existing session

class Profile(ProfileRequest):
    id: str
    created_at: datetime
    status: ProfileStatus = ProfileStatus.STOPPED

class BrowserSession(BaseModel):
    id: str
    started_at: datetime
    status: SessionStatus = SessionStatus.RUNNING
    container_id: Optional[str] = None
    live_view_url: Optional[str] = None
    port: Optional[int] = None

class ActionResult(BaseModel):
    """Model for an action result."""
    type: str
    success: bool
    selector: Optional[str] = None
    data: Optional[str] = None
    text: Optional[str] = None
    error: Optional[str] = None
    result: Optional[Any] = None
    format: Optional[str] = None
    path: Optional[str] = None
    duration: Optional[int] = None

class TaskResult(BaseModel):
    """Model for a task result."""
    task_id: str
    result: Optional[Any] = None
    status: str
    success: Optional[bool] = None
    url: Optional[str] = None
    results: Optional[List[ActionResult]] = None
    error: Optional[str] = None 