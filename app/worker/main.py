#!/usr/bin/env python3
"""
Browser Worker Main Entry Point
"""
import asyncio
import signal
import os
import structlog
from browser_worker import BrowserWorker
from health import start_health_server

# Configure structlog
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ]
)

log = structlog.get_logger()

async def main():
    """Main entry point for the worker."""
    log.info("Starting Browser Worker")
    
    # Start health check server
    health_runner = await start_health_server()
    log.info("Health check server started")
    
    # Create and start worker
    worker = BrowserWorker()
    
    # Handle shutdown signals
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown(worker, health_runner)))
    
    # Start the worker
    await worker.run()

async def shutdown(worker, health_runner):
    """Gracefully shutdown the worker and health check server."""
    log.info("Shutting down...")
    
    # Stop worker
    await worker.shutdown()
    
    # Cleanup health check server
    await health_runner.cleanup()
    
    log.info("Shutdown complete")

if __name__ == "__main__":
    asyncio.run(main()) 