import structlog
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ]
)

from fastapi import FastAPI, HTTPException, Depends
import os
from task_manager import TaskManager, get_task_manager
from app.common.models import BrowserTaskRequest, BrowserTaskResponse

log = structlog.get_logger(__name__)

app = FastAPI(title="Browser Infrastructure API")

@app.get("/")
async def root():
    return {"message": "Browser Infrastructure API"}

@app.post("/browser/task", response_model=BrowserTaskResponse)
async def start_browser_task(
    task: BrowserTaskRequest, 
    task_manager: TaskManager = Depends(get_task_manager)
):
    """
    Submit a browser task for execution.
    """
    try:
        return await task_manager.submit_task(task)
    except Exception as e:
        log.error("Error submitting task", task=task, error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/browser/task/{task_id}", response_model=BrowserTaskResponse)
async def get_task_result(
    task_id: str,
    task_manager: TaskManager = Depends(get_task_manager)
):
    """
    Get the result of a browser task.
    """
    try:
        return await task_manager.get_task_result(task_id)
    except Exception as e:
        log.error("Error getting task result", task_id=task_id, error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check(task_manager: TaskManager = Depends(get_task_manager)):
    """
    Health check endpoint.
    """
    # Check Redis connection
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