import os
import json
import asyncio
import structlog
import websockets
import socket
from typing import Optional, Dict, Any
from browser_use import Browser
from app.common.models import BrowserTaskStatus
from app.worker.browser_worker import get_browser_worker

log = structlog.get_logger(__name__)

# LiveViewManager is a singleton, use get_live_view_manager() to get the LiveViewManager instance instead of LiveViewManager() directly 
class LiveViewManager:
    """Manages the live view capabilities for the browser worker."""
    
    def __init__(self):
        self.screenshot_interval: float = 1.0
        self.running = True

        self.last_screenshot: Optional[bytes] = None
        self.screenshot_task: Optional[asyncio.Task] = None
        self.websocket_task: Optional[asyncio.Task] = None
        self.controller_ws = None

        self.controller_url = os.getenv("CONTROLLER_URL", "ws://localhost:8000/ws/worker").strip()
        self.controller_connected = False
        self.has_live_viewer = False
    
    def initialize(self) -> bool:
        # Connect to controller if URL is provided
        if self.controller_url:
            asyncio.create_task(self.send_heartbeat())
            self.websocket_task = asyncio.create_task(self.connect_to_controller())
            log.info(f"Started controller connection task to {self.controller_url}")
        else:
            log.warning("No CONTROLLER_URL provided - live view will not connect to central controller")
        
        log.info("Live view manager initialized (screenshot capture will start when viewers connect)")
        return True
    
    def update_task_live_view(self, task_id: str, status: BrowserTaskStatus, result: str) -> None:
        if self.has_live_viewer:
            task_info = {
                "type": "task_update",
                "task_id": task_id,
                "status": status.value,
                "result": result
            }
            asyncio.create_task(self.send_to_controller(json.dumps(task_info)))
    
    def get_playwright_browser_page(self, browser: Browser):
        """Helper method to get the current browser page."""
        if browser.playwright_browser:
            playwright_browser = browser.playwright_browser
            contexts = playwright_browser.contexts
            if contexts and len(contexts) > 0 and len(contexts[0].pages) > 0:
                return contexts[0].pages[0]
        return None
    
    async def capture_screenshots(self, browser: Browser):
        log.info("Starting screenshot capture loop")
        while self.running and self.has_live_viewer and self.controller_connected:
            try:
                current_page = self.get_playwright_browser_page(browser)
                if current_page and self.controller_connected and self.controller_ws:
                    screenshot = await current_page.screenshot(full_page=False, type="jpeg", quality=50)
                    
                    # Store the screenshot in memory
                    self.last_screenshot = screenshot
                    
                    # Send to controller
                    try:
                        await self.controller_ws.send(screenshot)
                    except Exception as e:
                        log.exception("Error sending screenshot to controller", error=str(e))
                        self.controller_connected = False
            except Exception as e:
                log.exception("Error capturing screenshot", error=str(e))
            
            await asyncio.sleep(self.screenshot_interval)
    
    async def connect_to_controller(self):
        """Connect to the central controller via WebSocket."""
        # Skip if no controller URL is provided
        if not self.controller_url:
            log.warning("No controller URL provided, skipping controller connection")
            return
            
        reconnect_delay = 5  # seconds
        max_reconnect_delay = 60  # seconds
        
        # Clean up controller URL if needed
        controller_ws_url = self.controller_url
        if not controller_ws_url.startswith(("ws://", "wss://")):
            if controller_ws_url.startswith(("http://", "https://")):
                controller_ws_url = controller_ws_url.replace("http://", "ws://").replace("https://", "wss://")
            else:
                controller_ws_url = f"ws://{controller_ws_url}"
                
        if not controller_ws_url.endswith("/ws/worker"):
            if controller_ws_url.endswith("/"):
                controller_ws_url += "ws/worker"
            else:
                controller_ws_url += "/ws/worker"
        
        log.info(f"Will connect to controller at: {controller_ws_url}")
        
        while self.running:
            try:
                log.info(f"Connecting to controller at {controller_ws_url}")
                
                async with websockets.connect(controller_ws_url) as websocket:
                    self.controller_ws = websocket
                    self.controller_connected = True
                    log.info("Connected to controller")
                    
                    # Register with the controller
                    browser_worker = await get_browser_worker()
                    registration = {
                        "type": "register",
                        "worker_id": browser_worker.id,
                        "info": {
                            "hostname": socket.gethostname(),
                            "status": "READY"
                        }
                    }
                    
                    # Send registration
                    await websocket.send(json.dumps(registration))
                    
                    # Wait for confirmation
                    response = await websocket.recv()
                    data = json.loads(response)
                    
                    if data.get("type") == "registered":
                        log.info(f"Successfully registered with controller as {data.get('worker_id')}")
                        
                        # Handle messages from the controller
                        while self.running:
                            try:
                                message = await websocket.recv()

                                # Handle message based on type
                                try:
                                    data = json.loads(message)
                                    message_type = data.get("type")
                                    if message_type == "viewer_status_update":
                                        # Controller is informing us about viewer status
                                        has_viewers = data.get("has_viewers", False)
                                        viewer_count = data.get("viewer_count", 0)
                                        
                                        log.info(f"Received viewer status update: {has_viewers} ({viewer_count} viewers)")
                                        
                                        # Update our viewer status
                                        self.has_live_viewer = has_viewers
                                        
                                        # Start screenshot task based on viewer status
                                        if has_viewers and (self.screenshot_task is None or self.screenshot_task.done()):
                                            log.info("Starting screenshot task due to active viewers")
                                            browser_instance = (await get_browser_worker()).browser_instance
                                            self.screenshot_task = asyncio.create_task(self.capture_screenshots(browser_instance))
                                    
                                    elif message_type == "heartbeat_ack":
                                        # Update viewer status from heartbeat ack
                                        has_viewers = data.get("has_viewers", False)
                                        if has_viewers != self.has_live_viewer:
                                            log.info(f"Heartbeat shows viewer status changed: {has_viewers}")
                                            self.has_live_viewer = has_viewers
                                            
                                            # Start or stop screenshot task if needed
                                            if has_viewers and (self.screenshot_task is None or self.screenshot_task.done()):
                                                log.info("Starting screenshot task due to active viewers")
                                                browser_instance = (await get_browser_worker()).browser_instance
                                                self.screenshot_task = asyncio.create_task(self.capture_screenshots(browser_instance))
                                        
                                except json.JSONDecodeError:
                                    log.warning(f"Received non-JSON message from controller: {message[:100]}")
                            except Exception as e:
                                log.exception("Error receiving message from controller", error=str(e))
                                break
                    else:
                        log.error(f"Failed to register with controller: {data}")
            
            except (websockets.exceptions.ConnectionClosed, OSError) as e:
                log.warning(f"Controller connection closed: {str(e)}")
            except Exception as e:
                log.exception("Error in controller connection", error=str(e))
            
            # Only try to reconnect if we're still running
            if self.running:
                log.info(f"Reconnecting to controller in {reconnect_delay} seconds")
                self.controller_connected = False
                self.controller_ws = None
                
                # Reset viewer status and cancel screenshot task
                self.has_live_viewer = False

                await asyncio.sleep(reconnect_delay)
                
                # Increase backoff time, but don't exceed max
                reconnect_delay = min(reconnect_delay * 1.5, max_reconnect_delay)
            else:
                break
    
    async def send_to_controller(self, message):
        """Send a message to the central controller if connected."""
        if self.controller_connected and self.controller_ws:
            try:
                await self.controller_ws.send(message)
                return True
            except Exception as e:
                log.error(f"Error sending message to controller", error=str(e))
                self.controller_connected = False
                self.controller_ws = None
        return False
    
    async def send_heartbeat(self):
        """Send a heartbeat to the controller every 30 seconds."""
        while self.running:
            if self.controller_connected and self.controller_ws:
                try:
                    await self.controller_ws.send(json.dumps({"type": "heartbeat"}))
                    log.debug("Sent heartbeat to controller")
                except Exception as e:
                    log.error(f"Error sending heartbeat to controller", error=str(e))
                    self.controller_connected = False
                    self.controller_ws = None
            
            await asyncio.sleep(30)  # 30 second interval
    
    async def shutdown(self):
        """Shutdown the live view manager."""
        log.info("Shutting down live view manager")
        self.running = False
        self.has_live_viewer = False
        
        # Cancel screenshot task
        if self.screenshot_task:
            self.screenshot_task.cancel()
            try:
                await self.screenshot_task
            except asyncio.CancelledError:
                log.info("Screenshot task cancelled")
        
        # Cancel WebSocket connection to controller
        if self.websocket_task:
            self.websocket_task.cancel()
            try:
                await self.websocket_task
            except asyncio.CancelledError:
                log.info("Controller WebSocket task cancelled")
        
        # Close controller connection if open
        if self.controller_ws:
            try:
                await self.controller_ws.close()
            except:
                pass
            self.controller_ws = None
            
        log.info("Live view manager shutdown complete")


# Singleton
_live_view_manager = None

async def get_live_view_manager():
    global _live_view_manager
    if _live_view_manager is None:
        _live_view_manager = LiveViewManager()
        _live_view_manager.initialize()
    return _live_view_manager       

async def shutdown_live_view_manager():
    global _live_view_manager
    if _live_view_manager:
        await _live_view_manager.shutdown()
        _live_view_manager = None