from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from enum import Enum

class SessionStatus(str, Enum):
    RUNNING = "running"
    STOPPED = "stopped"

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