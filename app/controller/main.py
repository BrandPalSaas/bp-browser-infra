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


@app.post("/browser/task/kolDetail", response_model=BrowserTaskResponse)
async def start_kol_detail_task(
    kolId: str,
    task_manager: TaskManager = Depends(get_task_manager)
):
    """
    根据传入的kolId获取kol的详细信息
    1. 提交浏览器任务
    2. 轮询任务状态
    3. 任务完成后调用外部API
    4. 返回最终结果
    """
    MAX_RETRIES = 3
    POLL_INTERVAL = 5  # 轮询间隔 1秒
    TIMEOUT = 300  # 超时时间 300秒

    try:
        # 提交任务
        task_response = await task_manager.submit_task(BrowserTaskRequest(
            task={
                "description": f"Open 'https://affiliate-us.tiktok.com/connection/creator?shop_region=US', and click Find creators. In the search box, type in: {kolId}, remember to click the magnifier button to execute the search. In search result, find the row that has name exactly same as what you typed in search. Return the influencer name as name, GMV as gmv, Item Sold as item_sold, Avg video views as avg_video_views, and Engagement Rate as engagement_rate, in json format.",
                "shop": {
                    "shop": "ShopperInc",
                    "bind_user_email": "dengjie200@gmail.com",
                },
            }
        ))

        task_id = task_response.task_id

        # 轮询任务状态
        start_time = asyncio.get_event_loop().time()
        while True:
            # 检查超时
            if asyncio.get_event_loop().time() - start_time > TIMEOUT:
                raise HTTPException(status_code=504, detail="Task timeout")

            # 获取任务状态
            task_status = await task_manager.get_task_result(task_id)

            if task_status.task_status == BrowserTaskStatus.COMPLETED:
                # 任务完成，调用外部API
                try:
                    # TODO: 添加实际的外部API调用逻辑
                    # external_api_response = await call_external_api(task_status.task_response)
                    return task_status.task_response
                except Exception as e:
                    log.error("Error calling external API", error=str(e))
                    raise HTTPException(status_code=502, detail="External API call failed")

            elif task_status.task_status == BrowserTaskStatus.FAILED:
                raise HTTPException(status_code=500, detail=task_status.task_response)

            await asyncio.sleep(POLL_INTERVAL)

    except HTTPException:
        raise
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
