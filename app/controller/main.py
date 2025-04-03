import sys
import asyncio
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
import json
import structlog
from typing import Dict, Set, List, Optional, Any
from pathlib import Path
from fastapi import (
    FastAPI,
    WebSocket,
    WebSocketDisconnect,
    Depends,
    Request,
    HTTPException,
)
from pydantic import BaseModel
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware

from app.models import (
    BrowserTaskRequest,
    BrowserTaskResponse,
    WebSocketRequest,
    WebSocketRequestType,
)
from app.common.task_manager import get_task_manager, TaskManager
from app.controller.worker_manager import get_worker_manager, WorkerManager
from app.playwright.get_kol_GMV import poll_task_status

from dotenv import load_dotenv

from app.models.api import BrowserTaskStatus

load_dotenv()


# Set up logging
log = structlog.get_logger(__name__)

# Create the FastAPI app
app = FastAPI(title="Browser Infrastructure Controller")

# Mount static files directory
app.mount(
    "/static",
    StaticFiles(directory=str(Path(__file__).parent / "static")),
    name="static",
)

# Create Jinja2 templates
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {"message": "Browser Infrastructure API"}


@app.get("/live", response_class=HTMLResponse)
async def list_workers(
    request: Request, worker_manager: WorkerManager = Depends(get_worker_manager)
):
    """Display list of active workers."""
    all_workers = []
    connected_worker_ids = worker_manager.get_connected_worker_ids()
    for worker_id in connected_worker_ids:
        if not any(w["worker_id"] == worker_id for w in all_workers):
            conn = worker_manager.get_worker_connection(worker_id)
            all_workers.append(conn.to_worker_list_page_item().model_dump())

    return templates.TemplateResponse(
        "worker_list.html",
        {
            "request": request,
            "title": "Browser Worker Dashboard",
            "workers": all_workers,
        },
    )


@app.get("/live/{worker_id}", response_class=HTMLResponse)
async def live_view(
    request: Request,
    worker_id: str,
    worker_manager: WorkerManager = Depends(get_worker_manager),
):
    """Show live view for a worker."""
    # Check if the worker exists and is connected
    worker_conn = worker_manager.get_worker_connection(worker_id)
    if not worker_conn.is_connected():
        raise HTTPException(status_code=404, detail="Worker not found or not connected")

    # Render the live view template
    return templates.TemplateResponse(
        "live_view.html", {"request": request, "worker_id": worker_id}
    )


@app.websocket("/ws/live/{worker_id}")
async def websocket_viewer_connection(
    websocket: WebSocket,
    worker_id: str,
    worker_manager: WorkerManager = Depends(get_worker_manager),
):
    """WebSocket endpoint for viewers to connect to a worker."""
    # Accept the connection
    await websocket.accept()
    log.info(f"Viewer WebSocket connected for worker {worker_id}")

    # Get or create worker connection
    worker_conn = worker_manager.get_worker_connection(worker_id)
    worker_conn.add_viewer(websocket)

    # For now, we're not implementing control functionality
    await websocket.send_json(
        {
            "type": "view_only_mode",
            "message": "Interactive control is currently disabled",
        }
    )

    # Send initial task status if available
    if worker_conn.current_task_id:
        await websocket.send_json(
            {
                "type": "task_update",
                "current_task_id": worker_conn.current_task_id,
                "status": worker_conn.task_status,
                "task_response": worker_conn.task_response,
            }
        )

    # If we have a screenshot, send it immediately
    if worker_conn.last_screenshot:
        await websocket.send_bytes(worker_conn.last_screenshot)

    try:
        # Process messages from the viewer - for now, we just keep the connection open
        while True:
            # We still need to receive messages to keep the connection alive
            await websocket.receive_text()
            # Just send an acknowledgement
            await websocket.send_json(
                {
                    "type": "message",
                    "message": "Interactive control is currently disabled",
                }
            )
    except WebSocketDisconnect:
        log.info(f"Viewer WebSocket disconnected for worker {worker_id}")
    finally:
        # Remove viewer
        worker_conn.remove_viewer(websocket)


@app.websocket("/ws/worker")
async def websocket_worker_connection(
    websocket: WebSocket, worker_manager: WorkerManager = Depends(get_worker_manager)
):
    """WebSocket endpoint for workers to connect."""
    worker_id = None

    try:
        # Accept the connection
        await websocket.accept()

        # First message must be registration
        registration_json = await websocket.receive_json()
        registration_request = WebSocketRequest(**registration_json)

        if registration_request.request_type != WebSocketRequestType.WORKER_REGISTER:
            await websocket.close(
                code=1008, reason="First message must be registration"
            )
            return

        # Handle registration
        worker_id = await worker_manager.handle_worker_registration(
            websocket, registration_request
        )

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
                    request = WebSocketRequest(**data)
                    # Handle other message types
                    await worker_manager.handle_worker_message(worker_id, request)

                except json.JSONDecodeError:
                    log.error(f"Invalid JSON received from worker: {message['text']}")
                except Exception as e:
                    log.error(f"Error processing worker message", error=str(e))

    except WebSocketDisconnect:
        log.info(f"Worker WebSocket disconnected: {worker_id}")
    except Exception as e:
        log.error(
            f"Error in worker WebSocket connection", worker_id=worker_id, error=str(e)
        )
    finally:
        # Clean up
        if worker_id:
            worker_conn = worker_manager.get_worker_connection(worker_id)
            worker_conn.remove_worker_connection()


@app.post("/browser/task", response_model=BrowserTaskResponse)
async def start_browser_task(
    task: BrowserTaskRequest, task_manager: TaskManager = Depends(get_task_manager)
):
    """
    Submit a browser task for execution.
    """
    try:
        return await task_manager.submit_task(task)
    except Exception as e:
        log.exception("Error submitting task", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


class KolDetailRequest(BaseModel):
    uniqueId: str


@app.post("/browser/task/kolDetail")
async def start_kol_detail_task(
    data: KolDetailRequest,
    task_manager: TaskManager = Depends(get_task_manager),
):
    """
    根据传入的kolId启动获取kol详细信息的任务
    1. 提交浏览器任务
    2. 立即返回taskId
    """
    try:
        # 提交任务
        task_response = await task_manager.submit_task(
            BrowserTaskRequest(
                task={
                    # "description": f"Open 'https://affiliate-us.tiktok.com/connection/creator?shop_region=US', and click Find creators. In the search box, type in: {data.uniqueId}, remember to press enter to search. In search result, find the row that has name exactly same as what you typed in search. Return the influencer name as name, GMV as gmv, Item Sold as item_sold, Avg video views as avg_video_views, and Engagement Rate as engagement_rate, in json format. 'final_result' is returned to me in JSON format, and it is not allowed to add any description",
                    "description": f"Open 'https://affiliate-us.tiktok.com/connection/creator?shop_region=US', wait for the page to finish rendering. If there is a pop-up window or dialog box on the open page, find the close button to close it, the close button is usually in the top right corner, it's small in size and has an x symbol in it. Then click on 'Find creators'. In the search box, type in: {data.uniqueId}, then press enter to search. In search result, find the row that has name exactly same as what you typed in search. Return the influencer name as name, GMV as gmv, Item Sold as item_sold, Avg video views as avg_video_views, and Engagement Rate as engagement_rate, in json format. 'final_result' is returned to me in JSON format, and it is not allowed to add any description",
                    "shop": {
                        "shop": "ShopperInc",
                        "bind_user_email": "dengjie200@gmail.com",
                    },
                }
            )
        )

        # 启动轮询
        asyncio.create_task(poll_task_status(task_response.task_id, task_manager))

        # 返回taskId
        return task_response

    except Exception as e:
        log.exception("Error in kol detail task", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/browser/task/{task_id}", response_model=BrowserTaskResponse)
async def get_task_status(
    task_id: str, task_manager: TaskManager = Depends(get_task_manager)
):
    """
    Get the status of a task.
    """
    try:
        task = await task_manager.get_task_result(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        return task
    except HTTPException:
        raise
    except Exception as e:
        log.exception("Error getting task status", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health_check(task_manager: TaskManager = Depends(get_task_manager)):
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
        return {"status": "unhealthy", "error": str(e)}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("API_PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
