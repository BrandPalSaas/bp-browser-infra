#!/usr/bin/env python3
"""
Browser Worker Main Entry Point
"""
import os
import asyncio
import signal
import sys
from browser_worker import BrowserWorker
from live_view import LiveViewManager, start_live_view_server, UvicornServer
from dotenv import load_dotenv

import structlog
log = structlog.get_logger(__name__)

# Load environment variables
load_dotenv()

class WorkerService:
    """Service class that encapsulates worker and live view functionality."""
    
    def __init__(self):
        self.worker = None
        self.live_view_manager = None
        self.tasks = []
        self.running = True
    
    async def initialize(self):
        """Initialize the worker and live view manager."""
        log.info("Starting Browser Worker")
        
        # Create and initialize worker
        self.worker = BrowserWorker()
        
        # Create live view manager
        self.live_view_manager = LiveViewManager()
        
        # Initialize and run the worker
        if await self.worker.initialize():
            log.info("Worker initialized successfully")
            
            # Initialize the live view manager with the browser instance
            if self.live_view_manager.initialize(self.worker.get_browser()):
                log.info("Live view manager initialized successfully")
                
                # Start live view server
                live_view_port = int(os.getenv("LIVE_VIEW_PORT", 3000))
                log.info(f"Starting live view server on port {live_view_port}")
                log.info(f"Live view available at: http://localhost:{live_view_port}/")
                
                live_view_task = asyncio.create_task(
                    start_live_view_server(
                        live_view_manager=self.live_view_manager, 
                        worker_name=self.worker.consumer_name,
                        port=live_view_port
                    )
                )
                self.tasks.append(live_view_task)
            
            # Start worker task processing
            worker_task = asyncio.create_task(self.worker.read_tasks())
            self.tasks.append(worker_task)
            return True
        else:
            log.error("Worker initialization failed")
            return False
    
    async def shutdown(self):
        """Gracefully shutdown the worker and server."""
        if not self.running:
            return
            
        self.running = False
        log.info("Shutting down services...")
        
        # Cancel all tasks
        for task in self.tasks:
            if not task.done():
                task.cancel()
        
        # Wait briefly for tasks to handle cancellation
        if self.tasks:
            await asyncio.wait(self.tasks, timeout=5.0)
            
        # Shutdown live view manager
        if self.live_view_manager:
            await self.live_view_manager.shutdown()
        
        # Then shutdown worker
        if self.worker:
            await self.worker.shutdown()
        
        log.info("All services shutdown complete")

async def main():
    """Main entry point."""
    service = WorkerService()
    
    # Set up signal handlers
    def handle_signal():
        if service.running:
            log.info("Received signal, initiating shutdown")
            asyncio.create_task(service.shutdown())
    
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, handle_signal)
    
    try:
        # Initialize service
        if await service.initialize():
            log.info("Worker service initialized and running")
            
            # Simply wait for all tasks to complete instead of polling
            # This will be interrupted by task cancellation from signal handler
            done, pending = await asyncio.wait(service.tasks, return_when=asyncio.FIRST_COMPLETED)
            
            # Check if any completed task had an exception
            for task in done:
                if task.exception():
                    log.error(f"Task failed with exception: {task.exception()}")
    except Exception as e:
        log.exception("Unexpected error in main loop", error=str(e))
    finally:
        # Ensure services are properly shut down
        await service.shutdown()

if __name__ == "__main__":
    asyncio.run(main())