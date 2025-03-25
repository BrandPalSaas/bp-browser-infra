import asyncio
import json
import uuid
import structlog
from datetime import datetime
from typing import Dict, Set, Optional, Any, List
from fastapi import WebSocket
from app.common.models import WorkerInfo, WebSocketRequest,\
      WebSocketRequestType, WebSocketResponse, WebSocketResponseType, BrowserTaskStatus, WorkerListPageItem
      

log = structlog.get_logger(__name__)

class WorkerConnection:
    """Manages connection and state for a single worker."""
    
    def __init__(self, worker_id: str):
        self.worker_id = worker_id
        self.viewer_connections: Set[WebSocket] = set()
        self.worker_connection: Optional[WebSocket] = None
        self.last_screenshot = None
        self.connected_at = None
        self.last_updated = datetime.now()
        self.is_streaming = False

        # Task related fields
        self.current_task_id = ""
        self.task_status = BrowserTaskStatus.WAITING
        self.task_response = ""
    
    
    # convert to worker list html page item
    def to_worker_list_page_item(self) -> WorkerListPageItem:
        return WorkerListPageItem(
            worker_id=self.worker_id,
            viewer_count=len(self.viewer_connections),
            current_task_id=self.current_task_id,
            connected_at=self.connected_at.isoformat() if self.connected_at else None
        )
    
    def add_viewer(self, websocket: WebSocket) -> None:
        """Add a client viewer connection"""
        was_empty = len(self.viewer_connections) == 0
        self.viewer_connections.add(websocket)
        log.info(f"Added viewer for worker {self.worker_id}, total viewers: {len(self.viewer_connections)}")
        
        # If this is the first viewer, notify worker to start streaming
        if was_empty and self.worker_connection:
            asyncio.create_task(self.send_viewer_status_update())
    
    def remove_viewer(self, websocket: WebSocket) -> None:
        """Remove a client viewer connection"""
        if websocket in self.viewer_connections:
            self.viewer_connections.remove(websocket)
            log.info(f"Removed viewer for worker {self.worker_id}, total viewers: {len(self.viewer_connections)}")
            
            # If no more viewers, notify worker to stop streaming
            if len(self.viewer_connections) == 0 and self.worker_connection:
                asyncio.create_task(self.send_viewer_status_update())
    
    async def send_viewer_status_update(self) -> None:
        """Send viewer status update to worker"""
        if not self.worker_connection:
            log.warning(f"Worker {self.worker_id} not connected, skipping viewer status update")
            return
            
        has_viewers = len(self.viewer_connections) > 0
        try:
            request = WebSocketRequest(
                request_type=WebSocketRequestType.CONTROLLER_VIEWER_STATUS_UPDATE, 
                worker_id=self.worker_id,
                viewer_count=len(self.viewer_connections))

            await self.worker_connection.send_json(request.model_dump())
            log.info(f"Notified worker {self.worker_id} about viewer status: {has_viewers} viewers")
            self.is_streaming = has_viewers
        except Exception as e:
            log.error(f"Error sending viewer status update to worker", error=str(e))
    
    def set_worker_connection(self, websocket: WebSocket) -> None:
        """Set the worker's WebSocket connection"""
        self.worker_connection = websocket
        self.last_updated = datetime.now()
        self.connected_at = datetime.now()
        log.info(f"Worker {self.worker_id} connected")
        
        # Notify worker about current viewer status when it connects
        if len(self.viewer_connections) > 0:
            asyncio.create_task(self.send_viewer_status_update())
    
    def remove_worker_connection(self) -> None:
        """Remove the worker's WebSocket connection"""
        self.worker_connection = None
        self.connected_at = None
        log.info(f"Worker {self.worker_id} disconnected")
    
    def update_screenshot(self, screenshot_data: bytes) -> None:
        """Update the worker's screenshot"""
        self.last_screenshot = screenshot_data
        self.last_updated = datetime.now()
    
    def has_active_viewers(self) -> bool:
        """Check if there are active viewers for this worker"""
        return len(self.viewer_connections) > 0
    
    def is_connected(self) -> bool:
        """Check if the worker is connected"""
        return self.worker_connection is not None
    
    def update_task_status(self, request: WebSocketRequest) -> None:
        """Update task status from a WebSocketRequest"""
        self.current_task_id = request.task_id if request.task_id else ""
        self.task_status = request.task_status if request.task_status else BrowserTaskStatus.WAITING
        self.task_response = request.task_result if request.task_result else ""
            
        # Update last_updated timestamp
        self.last_updated = datetime.now()
    
    async def forward_screenshot_to_viewers(self, screenshot_data: bytes) -> None:
        """Forward screenshot to all connected viewers"""
        # Update our stored screenshot
        self.update_screenshot(screenshot_data)
        
        # Forward to all viewers
        for viewer in self.viewer_connections:
            try:
                await viewer.send_bytes(screenshot_data)
            except Exception as e:
                log.error(f"Error sending screenshot to viewer", error=str(e))
    
    async def forward_task_update_to_viewers(self, request: WebSocketRequest) -> None:
        """Forward task update to all connected viewers"""
        # First update our task status
        self.update_task_status(request)
        
        # Now send a task update message to all viewers
        task_update = {
            "type": "task_update",
            "current_task_id": self.current_task_id,
            "status": self.task_status,
            "task_response": self.task_response,
        }
        
        for viewer in self.viewer_connections:
            try:
                await viewer.send_json(task_update)
            except Exception as e:
                log.error(f"Error sending task update to viewer", error=str(e))
    
    async def forward_message_to_viewers(self, message: str) -> None:
        """Forward a text message to all connected viewers"""
        for viewer in self.viewer_connections:
            try:
                await viewer.send_text(message)
            except Exception as e:
                log.error(f"Error forwarding message to viewer", error=str(e))


# Use get_worker_manager() to get the WorkerManager instance instead of WorkerManager() directly 
# This ensures that the WorkerManager instance is a singleton
class WorkerManager:
    """Manages all worker connections and their state."""
    
    def __init__(self):
        # woker_id -> WorkerConnection
        self.worker_connections: Dict[str, WorkerConnection] = {}
    
    def get_worker_connection(self, worker_id: str) -> WorkerConnection:
        """Get or create a worker connection."""
        if worker_id not in self.worker_connections:
            self.worker_connections[worker_id] = WorkerConnection(worker_id)
        return self.worker_connections[worker_id]
    
    def get_all_workers(self) -> List[Dict[str, Any]]:
        """Get a list of all connected workers and their info."""
        workers_info = []
        for worker_id, conn in self.worker_connections.items():
            if conn.is_connected():
                workers_info.append(WorkerInfo(worker_id=worker_id, viewer_count=len(conn.viewer_connections)))
        return workers_info
    
    def get_connected_worker_ids(self) -> List[str]:
        """Get a list of all connected worker IDs."""
        return [worker_id for worker_id, conn in self.worker_connections.items() 
                if conn.is_connected()]
    
    async def handle_worker_registration(self, websocket: WebSocket, request: WebSocketRequest) -> str:
        """Handle worker registration and return the worker ID."""
        # Extract worker ID and info
        if not request.worker_id or not request.request_type == WebSocketRequestType.WORKER_REGISTER:
            raise RuntimeError(f"Worker ID is required in registration data: {request.model_dump()}")

        worker_id = request.worker_id
        worker_conn = self.get_worker_connection(worker_id)
        worker_conn.set_worker_connection(websocket)
        
        # Send confirmation
        response = WebSocketResponse(request_type=WebSocketResponseType.REGISTER_SUCCESS, worker_id=worker_id)
        await websocket.send_json(response.model_dump())
        
        log.info(f"Worker {worker_id} registered")
        return worker_id
    
    async def handle_worker_message(self, worker_id: str, message: WebSocketRequest) -> None:
        """Handle a message from a worker."""
        if not worker_id or worker_id not in self.worker_connections:
            log.error(f"Received message for unknown worker: {worker_id}")
            return
        
        worker_conn = self.worker_connections[worker_id]
        
        # Check message type
        if message.request_type == WebSocketRequestType.WORKER_TASK_STATUS_UPDATE:
            # Update worker's task status and forward to viewers
            log.info(f"Received task status update for worker {worker_id}, task {message.task_id}, status {message.task_status}")
            await worker_conn.forward_task_update_to_viewers(message)
            
    async def handle_worker_binary(self, worker_id: str, binary_data: bytes) -> None:
        """Handle binary data (screenshot) from a worker."""
        if not worker_id or worker_id not in self.worker_connections:
            log.error(f"Received binary data for unknown worker: {worker_id}")
            return
        
        worker_conn = self.worker_connections[worker_id]
        await worker_conn.forward_screenshot_to_viewers(binary_data)


# Create a singleton instance
_worker_manager = WorkerManager()

# factory method
def get_worker_manager() -> WorkerManager:
    """Get the singleton worker manager instance."""
    return _worker_manager 