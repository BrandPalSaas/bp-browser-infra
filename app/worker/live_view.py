import os
import json
import asyncio
import structlog
import pathlib
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from browser_use import Browser
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
        self.viewer_connections = set()
        self.active_controller = None
        self.last_screenshot = None
        self.screenshot_interval = 0.5
        self.browser = None
        self.screenshot_task = None
        self.running = True
    
    def initialize(self, browser: Browser):
        """Initialize the live view manager with a browser instance."""
        self.browser = browser
        if self.browser:
            self.screenshot_task = asyncio.create_task(self.capture_screenshots())
            log.info("Live view manager initialized")
            return True
        return False
    
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
                if self.browser and self.browser.page:
                    screenshot = await self.browser.playwright_browser.page.screenshot(full_page=False, type="jpeg", quality=70)
                    # Store the screenshot in memory
                    self.last_screenshot = screenshot
                    
                    # Send the screenshot to all connected viewers
                    if self.viewer_connections and screenshot:
                        log.debug(f"Sending screenshot to {len(self.viewer_connections)} viewers")
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
                
            if not self.browser or not self.browser.page:
                log.warning("Browser not available for command")
                return False
                
            command = command_data.get("type")
            
            if command == "click":
                x = command_data.get("x")
                y = command_data.get("y")
                if x is not None and y is not None:
                    await self.browser.page.mouse.click(x, y)
                    log.debug(f"Mouse click at {x}, {y}")
                    
            elif command == "type":
                text = command_data.get("text")
                if text:
                    await self.browser.page.keyboard.type(text)
                    log.debug(f"Keyboard type: {text}")
                    
            elif command == "key":
                key = command_data.get("key")
                if key:
                    await self.browser.page.keyboard.press(key)
                    log.debug(f"Key press: {key}")
                    
            elif command == "navigate":
                url = command_data.get("url")
                if url:
                    await self.browser.page.goto(url)
                    log.debug(f"Navigate to: {url}")
                    
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
        if worker_id != worker_name:
            return HTMLResponse(f"Worker {worker_id} not found", status_code=404)
        
        return templates.TemplateResponse(
            "live_view.html", 
            {"request": request, "worker_name": worker_name}
        )

    @app.websocket("/ws/live/{worker_id}")
    async def websocket_live_view(websocket: WebSocket, worker_id: str):
        """WebSocket endpoint for live view."""
        if worker_id != worker_name:
            await websocket.close(code=1008, reason=f"Worker {worker_id} not found")
            return
        
        await websocket.accept()
        log.info(f"WebSocket connection established", worker_id=worker_id)
        
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