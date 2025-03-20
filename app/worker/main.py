#!/usr/bin/env python3
"""
Browser Worker Main Entry Point
"""
import asyncio
import os
import signal
from browser_worker import BrowserWorker

from dotenv import load_dotenv
load_dotenv()

import structlog
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ]
)

log = structlog.get_logger(__name__)

async def main():
    """Main entry point."""
    log.info("Starting Browser Worker")
    
    # Create and initialize worker
    worker = BrowserWorker()
    
    # Set up signal handlers for graceful shutdown
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(worker.shutdown()))
    
    # Initialize and run the worker
    if await worker.initialize():
        log.info("Worker initialized successfully")
        await worker.read_tasks()
    else:
        log.error("Worker initialization failed")

if __name__ == "__main__":
    asyncio.run(main()) 