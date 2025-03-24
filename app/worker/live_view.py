import os
import json
import asyncio
import structlog
import pathlib
import uvicorn
from typing import Optional, Union, Dict, Any, Set
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from browser_use import Browser
from app.common.models import BrowserTaskStatus
log = structlog.get_logger(__name__)

# Create FastAPI app for the live view
app = FastAPI()

# Set up templates directory
templates_dir = pathlib.Path(__file__).parent / "templates"

# Add the templates directory as a static directory
app.mount("/static", StaticFiles(directory=templates_dir), name="static")

# Create Jinja2 templates
templates = Jinja2Templates(directory=str(templates_dir))

class LiveViewManager:
    """Manages the live view capabilities for the browser worker."""
    
    def __init__(self):
        self.viewer_connections: Set[WebSocket] = set()
        self.active_controller: Optional[WebSocket] = None
        self.last_screenshot: Optional[bytes] = None
        self.screenshot_interval: float = 1.0
        self.browser: Optional[Browser] = None
        self.screenshot_task: Optional[asyncio.Task] = None
        self.running: bool = True
        self.current_task_id: Optional[str] = None

    
    def initialize(self, browser: Browser) -> bool:
        """Initialize the live view manager with a browser instance."""
        self.browser = browser
        if self.browser:
            self.screenshot_task = asyncio.create_task(self.capture_screenshots())
            log.info("Live view manager initialized")
            return True
        return False
    
    def update_task_info(self, task_id: str, status: BrowserTaskStatus, result: str = None) -> None:
        # Notify viewers of the task update
        if self.viewer_connections:
            task_info = {
                "type": "task_update",
                "task_id": task_id,
                "task_result": f"Status:{status.value}, Result: {result}"
            }
            # Create a task to send the update to all viewers
            asyncio.create_task(self.broadcast_task_info(task_info))
            
    async def broadcast_task_info(self, task_info):
        """Broadcast task information to all connected viewers."""
        websocket_tasks = []
        for websocket in self.viewer_connections:
            websocket_tasks.append(websocket.send_json(task_info))
        
        if websocket_tasks:
            await asyncio.gather(*websocket_tasks, return_exceptions=True)
    
    def get_playwright_browser_page(self):
        if self.browser and self.browser.playwright_browser:
            playwright_browser = self.browser.playwright_browser
            contexts = playwright_browser.contexts
            if contexts and len(contexts) > 0 and len(contexts[0].pages) > 0:
                return contexts[0].pages[0]

    
    async def capture_screenshots(self):
        """Continuously capture screenshots for live view."""
        log.info("Starting screenshot capture loop")
        while self.running and self.browser:
            if not self.viewer_connections:
                # No viewers connected, sleep to save resources
                await asyncio.sleep(1)
                continue
                
            try:
                # Only capture if viewers are connected
                current_page = self.get_playwright_browser_page()
                if current_page:
                    screenshot = await current_page.screenshot(full_page=False, type="jpeg", quality=50)
                    # Store the screenshot in memory
                    self.last_screenshot = screenshot
                    
                    # Send the screenshot to all connected viewers
                    if self.viewer_connections and screenshot:
                        log.info(f"Sending screenshot to {len(self.viewer_connections)} viewers")
                        websocket_tasks = []
                        for websocket in self.viewer_connections:
                            websocket_tasks.append(websocket.send_bytes(screenshot))
                        
                        if websocket_tasks:
                            await asyncio.gather(*websocket_tasks, return_exceptions=True)
            except Exception as e:
                log.exception("Error capturing screenshot", error=str(e))
            
            await asyncio.sleep(self.screenshot_interval)
    
    async def process_browser_command(self, command_data, websocket):
        """Process browser interaction commands from the live view."""
        try:
            # Only accept commands from the active controller
            if self.active_controller != websocket:
                log.warning("Command rejected - websocket is not the active controller")
                return False
                
            # Get the current page using our helper method
            current_page = self.get_playwright_browser_page()
            if not self.browser or not current_page:
                log.warning("Browser or page not available for command")
                return False
                
            command = command_data.get("type")
            
            if command == "click":
                x = command_data.get("x")
                y = command_data.get("y")
                if x is not None and y is not None:
                    await current_page.mouse.click(x, y)
                    log.debug(f"Mouse click at {x}, {y}")
                    
            elif command == "type":
                text = command_data.get("text")
                if text:
                    await current_page.keyboard.type(text)
                    log.debug(f"Keyboard type: {text}")
                    
            elif command == "key":
                key = command_data.get("key")
                if key:
                    await current_page.keyboard.press(key)
                    log.debug(f"Key press: {key}")
                    
            return True
        except Exception as e:
            log.exception("Error processing browser command", error=str(e), command=command_data)
            return False
    
    async def add_viewer(self, websocket):
        """Add a viewer connection."""
        self.viewer_connections.add(websocket)
        log.info(f"Added viewer, total viewers: {len(self.viewer_connections)}")
        
        # Send the initial screenshot if available
        if self.last_screenshot:
            await websocket.send_bytes(self.last_screenshot)
            
        # Send the current task information if available
        if self.current_task_id:
            await websocket.send_json({
                "type": "task_update",
                "task_id": self.current_task_id,
                "task_result": self.task_result
            })
    
    async def remove_viewer(self, websocket):
        """Remove a viewer connection."""
        if websocket in self.viewer_connections:
            self.viewer_connections.remove(websocket)
            log.info(f"Removed viewer, total viewers: {len(self.viewer_connections)}")
        
        # Release control if this was the controller
        await self.release_control(websocket)
    
    async def request_control(self, websocket):
        """Request control of the browser."""
        # If there's no active controller or the current one is this websocket, grant control
        if self.active_controller is None or self.active_controller == websocket:
            self.active_controller = websocket
            log.info(f"Control granted to viewer")
            return True
        log.info(f"Control request denied, already has controller")
        return False
    
    async def release_control(self, websocket):
        """Release control if this websocket is the controller."""
        if self.active_controller == websocket:
            self.active_controller = None
            log.info(f"Control released")
            return True
        return False
    
    async def shutdown(self):
        """Shutdown the live view manager."""
        self.running = False
        
        # Cancel screenshot task
        if self.screenshot_task:
            self.screenshot_task.cancel()
            try:
                await self.screenshot_task
            except asyncio.CancelledError:
                pass
        
        # Close all WebSocket connections
        for websocket in list(self.viewer_connections):
            try:
                await websocket.close(code=1000, reason="LiveView shutting down")
            except:
                pass
        self.viewer_connections.clear()
        self.active_controller = None
        
        log.info("LiveView manager shutdown complete")

# Setup routes
def setup_routes(app: FastAPI, live_view_manager: LiveViewManager, worker_name: str):
    """Setup the FastAPI routes for the live view."""

    @app.get("/")
    async def get_root():
        """Root endpoint that shows worker status and health information."""
        is_ready = live_view_manager.browser is not None
        
        response = {
            "status": "healthy" if is_ready else "initializing",
            "worker_name": worker_name,
            "live_view_url": f"/live/{worker_name}",
            "ready": is_ready
        }
        
        status_code = 200 if is_ready else 503
        return JSONResponse(response, status_code=status_code)

    @app.get("/live/{worker_id}", response_class=HTMLResponse)
    async def get_live_view(request: Request, worker_id: str):
        """Serve the live view HTML page."""
        # Allow any worker ID as long as we have a browser
        if not live_view_manager.browser:
            return HTMLResponse("Browser not ready", status_code=503)
        
        return templates.TemplateResponse(
            "live_view.html", 
            {"request": request, "worker_name": worker_name}
        )

    @app.websocket("/ws/live/{worker_id}")
    async def websocket_live_view(websocket: WebSocket, worker_id: str):
        """WebSocket endpoint for live view."""
        # Allow any worker ID as the worker instance is global
        # but log the attempted worker_id for debugging
        log.info(f"WebSocket connection requested for worker", requested_id=worker_id, actual_id=worker_name)
        
        await websocket.accept()
        log.info("WebSocket connection established")
        
        # Add this connection to the manager's set of connections
        await live_view_manager.add_viewer(websocket)
        
        # Request control of the browser
        is_controller = await live_view_manager.request_control(websocket)
        
        try:
            # Tell the client if they have control
            await websocket.send_json({
                "type": "control_status",
                "has_control": is_controller
            })
            
            # Listen for commands from the client
            while True:
                data = await websocket.receive_text()
                try:
                    command_data = json.loads(data)
                    
                    # Handle control request commands
                    if command_data.get("type") == "request_control":
                        is_controller = await live_view_manager.request_control(websocket)
                        await websocket.send_json({
                            "type": "control_status",
                            "has_control": is_controller
                        })
                        continue
                    
                    # Process browser commands only if client has control
                    success = await live_view_manager.process_browser_command(command_data, websocket)
                    
                    # Optional: Send command result back to client
                    if "id" in command_data:
                        await websocket.send_json({
                            "type": "command_result",
                            "id": command_data.get("id"),
                            "success": success
                        })
                        
                except json.JSONDecodeError:
                    log.error(f"Invalid JSON received: {data}")
                except Exception as e:
                    log.exception(f"Error processing command: {e}")
        
        except WebSocketDisconnect:
            log.info(f"WebSocket disconnected")
        except Exception as e:
            log.exception(f"WebSocket error: {e}")
        finally:
            # Remove the connection from the manager's set
            await live_view_manager.remove_viewer(websocket)

# Custom Uvicorn Server class that ignores signal handling
# Without this, the live view server will not be able to handle TERM signals
# and will not exit cleanly.
class UvicornServer(uvicorn.Server):
    """Custom Uvicorn Server that doesn't install signal handlers.
    This allows the main application to handle signals (like Ctrl+C) itself.
    """
    def install_signal_handlers(self) -> None:
        # Do nothing, allowing our main process to handle signals
        pass


async def start_live_view_server(live_view_manager: LiveViewManager, worker_name: str, port: int):
    """Start the live view server."""
    log.info("Starting live view server", worker_name=worker_name, port=port)
    setup_routes(app, live_view_manager, worker_name)
    
    # Configure the server
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")
    server = UvicornServer(config)  # Use our custom server class
    
    try:
        # Start the server
        await server.serve()
    except asyncio.CancelledError:
        log.info("Live view server task cancelled")
        # Signal the server to exit
        server.should_exit = True
        # Allow a brief moment for cleanup
        await asyncio.sleep(0.1)
        # Re-raise to notify the parent task
        raise 