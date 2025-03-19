import structlog
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ]
)

from fastapi import FastAPI, HTTPException, Depends
import os
from contextlib import asynccontextmanager
from task_manager import TaskManager, task_manager
from app.common.models import BrowserTaskRequest, BrowserTaskResponse, TaskResult

log = structlog.get_logger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for the application."""
    # Initialize the task manager on startup
    success = await task_manager.initialize()
    if not success:
        # Log the error but continue - we'll handle errors on each request
        log.error("Failed to initialize task manager")
    else:
        log.info("Task manager initialized successfully")   
    yield

app = FastAPI(title="Browser Infrastructure API", lifespan=lifespan)

@app.get("/")
async def root():
    return {"message": "Browser Infrastructure API"}

@app.post("/browser/task", response_model=BrowserTaskResponse)
async def start_browser_task(task: BrowserTaskRequest):
    """
    Submit a browser task for execution.
    """
    try:
        # Submit task directly to Redis
        result = await task_manager.submit_task(task)
        log.info("Task submitted successfully", task_id=result["task_id"])

        return BrowserTaskResponse(
            task_id=result["task_id"],
            status=result["status"],
            message=result.get("message", "Task submitted")
        )
    except Exception as e:
        log.error("Error submitting task", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/browser/task/{task_id}", response_model=TaskResult)
async def get_task_result(task_id: str, wait: bool = False):
    """
    Get the result of a browser task.
    
    If wait=True, the request will wait for up to 30 seconds for the task to complete.
    """
    try:
        # Get result with timeout if wait=True
        result = await task_manager.get_task_result(task_id, timeout=30 if wait else 0)
        
        # Convert to TaskResult model
        return TaskResult(
            task_id=task_id,
            status=result.get("status", "unknown"),
            success=result.get("success", None),
            error=result.get("error", None),
            result=result.get("result", None),
            results=result.get("results", None),
            url=result.get("url", None)
        )
    except Exception as e:
        log.error("Error getting task result", task_id=task_id, error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    """
    Health check endpoint.
    """
    # Try to connect to Redis if needed
    if not task_manager.redis:
        redis_ok = await task_manager.connect_to_redis()
    else:
        try:
            redis_ok = await task_manager.redis.ping()
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