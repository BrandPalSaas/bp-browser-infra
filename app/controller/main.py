import structlog
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ]
)

from fastapi import FastAPI, HTTPException, Depends
import os
import uuid
import asyncio
from contextlib import asynccontextmanager
from container import ContainerManager, container_manager
from app.common.models import BrowserAction, BrowserTaskRequest, TaskResponse, TaskResult

log = structlog.get_logger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for the application."""
    # Initialize the container manager on startup
    success = await container_manager.initialize()
    if not success:
        # Log the error but continue - we'll handle errors on each request
        log.error("Failed to initialize container manager")
    yield

app = FastAPI(title="Browser Infrastructure API", lifespan=lifespan)

@app.get("/")
async def root():
    return {"message": "Browser Infrastructure API"}

@app.post("/browser/task", response_model=TaskResponse)
async def use_browser(task: BrowserTaskRequest):
    """
    Submit a browser task for execution.
    """
    try:
        # Add task to Redis queue
        result = await container_manager.add_task(task.dict())
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/browser/task/{task_id}", response_model=TaskResult)
async def get_task_result(task_id: str, wait: bool = False):
    """
    Get the result of a browser task.
    
    If wait=True, the request will wait for up to 30 seconds for the task to complete.
    """
    try:
        result = await container_manager.get_result(task_id, timeout=30 if wait else 0)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    """
    Health check endpoint.
    """
    # Try to connect to Redis if needed
    if not container_manager.redis:
        redis_ok = await container_manager.connect_to_redis()
    else:
        try:
            redis_ok = await container_manager.redis.ping()
        except:
            redis_ok = False
    
    status = "healthy" if redis_ok else "unhealthy"
    return {
        "status": status,
        "redis": "connected" if redis_ok else "disconnected"
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("API_PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port) 