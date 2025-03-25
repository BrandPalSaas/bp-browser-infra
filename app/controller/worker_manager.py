import asyncio
import json
import uuid
import structlog
from datetime import datetime
from typing import Dict, Set, Optional, Any, List
from fastapi import WebSocket, WebSocketDisconnect

log = structlog.get_logger(__name__)

class WorkerConnection:
    """Manages connection and state for a single worker."""
    
    def __init__(self, worker_id: str):
        self.worker_id = worker_id
        self.viewer_connections: Set[WebSocket] = set()
        self.worker_connection: Optional[WebSocket] = None
        self.last_screenshot = None
        self.last_updated = datetime.now()
        self.worker_info: Dict[str, Any] = {}
        self.is_streaming = False
    
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
            return
            
        has_viewers = len(self.viewer_connections) > 0
        try:
            await self.worker_connection.send_json({
                "type": "viewer_status_update",
                "has_viewers": has_viewers,
                "viewer_count": len(self.viewer_connections)
            })
            log.info(f"Notified worker {self.worker_id} about viewer status: {has_viewers} viewers")
            self.is_streaming = has_viewers
        except Exception as e:
            log.error(f"Error sending viewer status update to worker", error=str(e))
    
    def set_worker_connection(self, websocket: WebSocket) -> None:
        """Set the worker's WebSocket connection"""
        self.worker_connection = websocket
        self.last_updated = datetime.now()
        log.info(f"Worker {self.worker_id} connected")
        
        # Notify worker about current viewer status when it connects
        if len(self.viewer_connections) > 0:
            asyncio.create_task(self.send_viewer_status_update())
    
    def remove_worker_connection(self) -> None:
        """Remove the worker's WebSocket connection"""
        self.worker_connection = None
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
    
    def update_worker_info(self, info: Dict[str, Any]) -> None:
        """Update the worker's information"""
        self.worker_info.update(info)
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
    
    async def forward_message_to_viewers(self, message: str) -> None:
        """Forward a text message to all connected viewers"""
        for viewer in self.viewer_connections:
            try:
                await viewer.send_text(message)
            except Exception as e:
                log.error(f"Error forwarding message to viewer", error=str(e))


class WorkerManager:
    """Manages all worker connections and their state."""
    
    def __init__(self):
        self.worker_connections: Dict[str, WorkerConnection] = {}
    
    def get_worker_connection(self, worker_id: str) -> WorkerConnection:
        """Get or create a worker connection."""
        if worker_id not in self.worker_connections:
            self.worker_connections[worker_id] = WorkerConnection(worker_id)
        return self.worker_connections[worker_id]
    
    def get_all_workers(self) -> List[Dict[str, Any]]:
        """Get a list of all connected workers and their info."""
        workers = []
        for worker_id, conn in self.worker_connections.items():
            if conn.is_connected():
                worker_data = {
                    "worker_id": worker_id,
                    "is_streaming": conn.is_streaming,
                    "viewer_count": len(conn.viewer_connections),
                    "last_updated": conn.last_updated.isoformat(),
                    **conn.worker_info
                }
                workers.append(worker_data)
        return workers
    
    def get_connected_worker_ids(self) -> List[str]:
        """Get a list of all connected worker IDs."""
        return [worker_id for worker_id, conn in self.worker_connections.items() 
                if conn.is_connected()]
    
    async def handle_worker_registration(self, websocket: WebSocket, registration_data: Dict[str, Any]) -> str:
        """Handle worker registration and return the worker ID."""
        # Extract worker ID and info
        worker_id = registration_data.get("worker_id")
        if not worker_id:
            # Generate a worker ID if none provided
            worker_id = f"worker-{uuid.uuid4().hex[:8]}"
        
        worker_info = registration_data.get("info", {})
        
        # Register the worker
        worker_conn = self.get_worker_connection(worker_id)
        worker_conn.set_worker_connection(websocket)
        worker_conn.update_worker_info(worker_info)
        
        # Send confirmation
        await websocket.send_json({
            "type": "registered",
            "worker_id": worker_id
        })
        
        log.info(f"Worker {worker_id} registered")
        return worker_id
    
    async def handle_worker_message(self, worker_id: str, message: Dict) -> None:
        """Handle a message from a worker."""
        if not worker_id or worker_id not in self.worker_connections:
            log.error(f"Received message for unknown worker: {worker_id}")
            return
        
        worker_conn = self.worker_connections[worker_id]
        
        # Check message type
        message_type = message.get("type")
        
        if message_type == "task_update":
            # Worker is reporting task status, update info
            worker_conn.update_worker_info({
                "current_task_id": message.get("task_id"),
                "task_status": message.get("status")
            })
            
            # Forward to all viewers
            message_json = json.dumps(message)
            await worker_conn.forward_message_to_viewers(message_json)
            
        elif message_type == "status_update":
            # Worker is reporting status changes
            worker_conn.update_worker_info(message.get("info", {}))
        
    async def handle_worker_binary(self, worker_id: str, binary_data: bytes) -> None:
        """Handle binary data (screenshot) from a worker."""
        if not worker_id or worker_id not in self.worker_connections:
            log.error(f"Received binary data for unknown worker: {worker_id}")
            return
        
        worker_conn = self.worker_connections[worker_id]
        await worker_conn.forward_screenshot_to_viewers(binary_data)
    
    async def send_heartbeat_response(self, worker_id: str, websocket: WebSocket) -> None:
        """Send heartbeat response to a worker."""
        if not worker_id or worker_id not in self.worker_connections:
            log.error(f"Heartbeat for unknown worker: {worker_id}")
            return
        
        worker_conn = self.worker_connections[worker_id]
        
        await websocket.send_json({
            "type": "heartbeat_ack",
            "has_viewers": worker_conn.has_active_viewers(),
            "viewer_count": len(worker_conn.viewer_connections)
        })


# Create a singleton instance
worker_manager = WorkerManager()

def get_worker_manager() -> WorkerManager:
    """Get the singleton worker manager instance."""
    return worker_manager 