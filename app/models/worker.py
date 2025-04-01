from pydantic import BaseModel
from typing import Optional
from .api import BrowserTaskRequest, BrowserTaskResponse

class WorkerInfo(BaseModel):
    worker_id: str
    viewer_count: int

class WorkerListPageItem(BaseModel):
    worker_id: str
    viewer_count: int
    current_task_id: Optional[str] = None
    connected_at: Optional[str] = None

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