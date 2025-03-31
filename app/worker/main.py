#!/usr/bin/env python3
"""
Browser Worker Main Entry Point
"""
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
import asyncio
import signal
import structlog
from dotenv import load_dotenv
from app.common.task_manager import get_task_manager, shutdown_task_manager
from app.worker.browser_worker import get_browser_worker, shutdown_browser_worker
from app.worker.live_view import get_live_view_manager, shutdown_live_view_manager
# Set up logging
log = structlog.get_logger(__name__)

# Load environment variables
load_dotenv()

# Global flag for shutdown
running = True

def signal_handler(signum, frame):
    """Handle termination signals."""
    global running
    log.info("Received shutdown signal")
    running = False

async def main():
    """Main entry point for the worker."""
    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    tasks = []
    try:
        # Initialize worker and task manager
        task_manager = await get_task_manager()
        browser_worker = await get_browser_worker()
        live_view_manager = await get_live_view_manager()  # also starts the socket connection with controller
        
        task_manager.add_status_listener(live_view_manager.update_task_live_view)
        log.info("Starting worker", worker_id=browser_worker.id)

        # Start task processing
        tasks.append(asyncio.create_task(browser_worker.read_tasks()))

        # Wait for shutdown signal
        global running
        while running:
            await asyncio.sleep(1)
            
    except Exception as e:
        log.exception("Error in main loop", error=str(e))
    finally:
        # Clean shutdown
        log.info("Shutting down...")
        
        # Cancel tasks
        for task in tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        
        # Shutdown components
        await shutdown_live_view_manager()
        await shutdown_browser_worker()
        await shutdown_task_manager()
        
        log.info("Shutdown complete")

if __name__ == "__main__":
    asyncio.run(main())
    print("Worker started")