from pydantic import BaseModel
from typing import Optional
from enum import Enum
from .api import BrowserTaskStatus

class WebSocketRequestType(str, Enum):
    # request from worker
    WORKER_REGISTER = "register"
    WORKER_TASK_STATUS_UPDATE = "task_status_update"
    WORKER_TASK_SCREENSHOT = "task_screenshot"

    # requests from controller
    CONTROLLER_VIEWER_STATUS_UPDATE = "viewer_status_update"

class WebSocketResponseType(str, Enum):
    REGISTER_SUCCESS = "register_success"

class WebSocketRequest(BaseModel):
    request_type: WebSocketRequestType
    worker_id: str
    viewer_count: Optional[int] = None
    task_id: Optional[str] = None
    task_status: Optional[BrowserTaskStatus] = None
    task_result: Optional[str] = None

class WebSocketResponse(BaseModel):
    request_type: WebSocketResponseType
    worker_id: str 