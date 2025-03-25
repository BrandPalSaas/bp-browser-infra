import os
import json
import asyncio
import uuid
import structlog
from datetime import datetime
from typing import Dict, Set, List, Optional, Any
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware

from app.common.models import BrowserTaskRequest, BrowserTaskResponse, BrowserTaskDetail
from app.common.task_manager import TaskManager
from app.controller.worker_manager import worker_manager, get_worker_manager, WorkerManager
from app.common.dep_locator import dep_locator, get_dep_locator
from app.common.worker_manager import WorkerConnection
from app.common.redis_client import get_redis_client

# Set up logging
log = structlog.get_logger(__name__)

# Create the FastAPI app
app = FastAPI(title="Browser Infrastructure Controller")

# Mount static files directory
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")

# Create Jinja2 templates
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

# Set up task manager
task_manager = TaskManager()

# Register dependencies
dep_locator.register("task_manager", task_manager)
dep_locator.register("worker_manager", WorkerManager())

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Dependency injection
def get_task_manager() -> TaskManager:
    return dep_locator.get("task_manager")

def get_worker_manager() -> WorkerManager:
    return dep_locator.get("worker_manager")

@app.get("/")
async def root():
    return {"message": "Browser Infrastructure API"}

@app.get("/live", response_class=HTMLResponse)
async def list_workers(
    request: Request, 
    task_manager: TaskManager = Depends(get_task_manager),
    worker_manager: WorkerManager = Depends(get_worker_manager)
):
    """Show a list of active workers."""
    # Get workers from both Redis registry and direct connections
    redis_workers = await task_manager.get_active_workers()
    
    # Add any direct-connected workers not in Redis
    all_workers = []
    for worker in redis_workers:
        worker_id = worker["worker_id"]
        # Ensure worker_name is consistent with worker_id
        if "worker_name" not in worker:
            worker["worker_name"] = worker_id
        
        # Check if we have a direct connection
        conn = worker_manager.get_worker_connection(worker_id)
        if conn.is_connected():
            worker["direct_connected"] = True
            # Update with any additional info from the direct connection
            worker.update(conn.worker_info)
            worker["streaming"] = conn.is_streaming
            worker["viewer_count"] = len(conn.viewer_connections)
        else:
            worker["direct_connected"] = False
            
        all_workers.append(worker)
    
    # Add any workers that are directly connected but not in Redis
    connected_worker_ids = worker_manager.get_connected_worker_ids()
    for worker_id in connected_worker_ids:
        if not any(w["worker_id"] == worker_id for w in all_workers):
            conn = worker_manager.get_worker_connection(worker_id)
            worker = {
                "worker_id": worker_id,
                "worker_name": worker_id,
                "direct_connected": True,
                "streaming": conn.is_streaming,
                "viewer_count": len(conn.viewer_connections),
                **conn.worker_info
            }
            all_workers.append(worker)
    
    return templates.TemplateResponse("live_list.html", {
        "request": request,
        "workers": all_workers
    })

@app.get("/live/{worker_id}", response_class=HTMLResponse)
async def live_view(
    request: Request, 
    worker_id: str,
    worker_manager: WorkerManager = Depends(get_worker_manager)
):
    """Show live view for a worker."""
    # Check if the worker exists and is connected
    worker_conn = worker_manager.get_worker_connection(worker_id)
    if not worker_conn.is_connected():
        raise HTTPException(status_code=404, detail="Worker not found or not connected")
    
    # Render the live view template
    return templates.TemplateResponse("live_view.html", {
        "request": request,
        "worker_id": worker_id
    })

@app.get("/api/workers", response_model=List[Dict[str, Any]])
async def get_active_workers(
    worker_manager: WorkerManager = Depends(get_worker_manager),
    task_manager: TaskManager = Depends(get_task_manager)
):
    """Get a list of all active workers."""
    redis_workers = await task_manager.get_active_workers()
    connected_workers = worker_manager.get_all_workers()
    
    # Combine the two sources
    all_workers = {}
    
    # Add Redis workers
    for worker in redis_workers:
        worker_id = worker["worker_id"]
        all_workers[worker_id] = worker
    
    # Update with directly connected workers
    for worker in connected_workers:
        worker_id = worker["worker_id"]
        if worker_id in all_workers:
            all_workers[worker_id].update(worker)
            all_workers[worker_id]["direct_connected"] = True
        else:
            worker["direct_connected"] = True
            all_workers[worker_id] = worker
    
    return list(all_workers.values())

@app.get("/api/workers/{worker_id}/screenshot")
async def get_worker_screenshot(
    worker_id: str, 
    worker_manager: WorkerManager = Depends(get_worker_manager)
):
    """Get the latest screenshot for a worker."""
    worker_conn = worker_manager.get_worker_connection(worker_id)
    
    if not worker_conn.is_connected():
        raise HTTPException(status_code=404, detail="Worker not found or not connected")
    
    if not worker_conn.last_screenshot:
        raise HTTPException(status_code=404, detail="No screenshot available for this worker")
    
    return StreamingResponse(
        content=iter([worker_conn.last_screenshot]),
        media_type="image/jpeg"
    )

@app.websocket("/ws/live/{worker_id}")
async def websocket_viewer_connection(
    websocket: WebSocket, 
    worker_id: str,
    worker_manager: WorkerManager = Depends(get_worker_manager)
):
    """WebSocket endpoint for viewers to connect to a worker."""
    # Accept the connection
    await websocket.accept()
    log.info(f"Viewer WebSocket connected for worker {worker_id}")
    
    # Get or create worker connection
    worker_conn = worker_manager.get_worker_connection(worker_id)
    worker_conn.add_viewer(websocket)
    
    # For now, we're not implementing control functionality
    await websocket.send_json({
        "type": "view_only_mode",
        "message": "Interactive control is currently disabled"
    })
    
    # If we have a screenshot, send it immediately
    if worker_conn.last_screenshot:
        await websocket.send_bytes(worker_conn.last_screenshot)
    
    try:
        # Process messages from the viewer - for now, we just keep the connection open
        while True:
            # We still need to receive messages to keep the connection alive
            await websocket.receive_text()
            # Just send an acknowledgement
            await websocket.send_json({
                "type": "message",
                "message": "Interactive control is currently disabled"
            })
    except WebSocketDisconnect:
        log.info(f"Viewer WebSocket disconnected for worker {worker_id}")
    finally:
        # Remove viewer
        worker_conn.remove_viewer(websocket)

@app.websocket("/ws/worker")
async def websocket_worker_connection(
    websocket: WebSocket,
    worker_manager: WorkerManager = Depends(get_worker_manager)
):
    """WebSocket endpoint for workers to connect."""
    worker_id = None
    
    try:
        # Accept the connection
        await websocket.accept()
        
        # First message must be registration
        registration = await websocket.receive_json()
        if registration.get("type") != "register":
            await websocket.close(code=1008, reason="First message must be registration")
            return
        
        # Handle registration
        worker_id = await worker_manager.handle_worker_registration(websocket, registration)
        
        # Loop to handle worker messages
        while True:
            # Read next message
            message = await websocket.receive()
            
            # Check if binary (screenshot) or text (command response)
            if "bytes" in message:
                # It's a screenshot
                await worker_manager.handle_worker_binary(worker_id, message["bytes"])
                        
            elif "text" in message:
                # It's a text message
                try:
                    data = json.loads(message["text"])
                    message_type = data.get("type")
                    
                    if message_type == "heartbeat":
                        # Respond to heartbeat with current viewer status
                        await worker_manager.send_heartbeat_response(worker_id, websocket)
                    else:
                        # Handle other message types
                        await worker_manager.handle_worker_message(worker_id, data)
                            
                except json.JSONDecodeError:
                    log.error(f"Invalid JSON received from worker: {message['text']}")
                except Exception as e:
                    log.error(f"Error processing worker message", error=str(e))
    
    except WebSocketDisconnect:
        log.info(f"Worker WebSocket disconnected: {worker_id}")
    except Exception as e:
        log.error(f"Error in worker WebSocket connection", worker_id=worker_id, error=str(e))
    finally:
        # Clean up
        if worker_id:
            worker_conn = worker_manager.get_worker_connection(worker_id)
            worker_conn.remove_worker_connection()

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
        log.exception("Error submitting task", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/browser/task/{task_id}", response_model=BrowserTaskDetail)
async def get_task_status(
    task_id: str,
    task_manager: TaskManager = Depends(get_task_manager)
):
    """
    Get the status of a task.
    """
    try:
        task = await task_manager.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        return task
    except HTTPException:
        raise
    except Exception as e:
        log.exception("Error getting task status", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check(
    task_manager: TaskManager = Depends(get_task_manager)
):
    """
    Health check endpoint.
    """
    try:
        # Check Redis connection
        redis_ok = await task_manager.check_redis_connection()
        
        # Calculate overall health
        health_status = {
            "status": "healthy" if redis_ok else "degraded",
            "redis": "connected" if redis_ok else "disconnected",
        }
        
        return health_status
    except Exception as e:
        log.exception("Health check failed", error=str(e))
        return {
            "status": "unhealthy",
            "error": str(e)
        }

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("API_PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port) 