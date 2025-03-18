from fastapi import FastAPI, HTTPException
from typing import List, Dict, Any
import uuid
from datetime import datetime
from pydantic import BaseModel

from models import (
    Profile, ProfileRequest, BrowserSession,
    SessionStatus, ProfileStatus
)
from container import container_manager

app = FastAPI(
    title="Browser Management API",
    description="API for managing browser-use instances",
    version="1.0.0"
)

# In-memory storage
profiles: Dict[str, Profile] = {}
sessions: Dict[str, BrowserSession] = {}

# Model for task execution requests
class TaskRequest(BaseModel):
    session_id: str
    task: str

# Model for task execution responses
class TaskResponse(BaseModel):
    success: bool
    result: str = None
    error: str = None

@app.get("/")
async def root():
    return {"message": "Browser Management API"}

@app.post("/sessions", response_model=BrowserSession)
async def start_session():
    session_id = str(uuid.uuid4())
    
    # Create actual container
    container_id, port, live_view_url = await container_manager.create_browser_container()
    
    new_session = BrowserSession(
        id=session_id,
        started_at=datetime.now(),
        container_id=container_id,
        port=port,
        live_view_url=live_view_url
    )
    sessions[session_id] = new_session
    return new_session

@app.post("/tasks", response_model=TaskResponse)
async def execute_task(task_request: TaskRequest):
    # Verify session exists
    if task_request.session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Get the session
    session = sessions[task_request.session_id]
    
    # Check if session is running
    if session.status == SessionStatus.STOPPED:
        raise HTTPException(status_code=400, detail="Session is stopped")
    
    # Execute the task on the worker
    result = await container_manager.execute_task(
        session_id=task_request.session_id,
        task=task_request.task
    )
    
    return TaskResponse(**result)

@app.post("/profiles", response_model=Profile)
async def create_profile(profile: ProfileRequest):
    # Verify session exists and is running
    if profile.session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    session = sessions[profile.session_id]
    if session.status == SessionStatus.STOPPED:
        raise HTTPException(status_code=400, detail="Cannot create profile for stopped session")

    profile_id = str(uuid.uuid4())
    new_profile = Profile(
        id=profile_id,
        created_at=datetime.now(),
        **profile.model_dump()
    )
    profiles[profile_id] = new_profile
    return new_profile

@app.get("/profiles", response_model=List[Profile])
async def list_profiles():
    return list(profiles.values())

@app.get("/profiles/{profile_id}", response_model=Profile)
async def get_profile(profile_id: str):
    if profile_id not in profiles:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profiles[profile_id]

@app.delete("/profiles/{profile_id}")
async def delete_profile(profile_id: str):
    if profile_id not in profiles:
        raise HTTPException(status_code=404, detail="Profile not found")
    del profiles[profile_id]
    return {"message": "Profile deleted successfully"}

@app.get("/sessions", response_model=List[BrowserSession])
async def list_sessions():
    return list(sessions.values())

@app.get("/sessions/{session_id}", response_model=BrowserSession)
async def get_session(session_id: str):
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    return sessions[session_id]

@app.delete("/sessions/{session_id}")
async def stop_session(session_id: str):
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session = sessions[session_id]
    if session.status == SessionStatus.STOPPED:
        raise HTTPException(status_code=400, detail="Session is already stopped")
    
    # Stop the actual container
    await container_manager.stop_container(session.container_id)
    session.status = SessionStatus.STOPPED
    return {"message": "Session stopped successfully"} 