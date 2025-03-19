#!/usr/bin/env python3
"""
Browser Worker Main Entry Point
"""
import asyncio
import signal
import os
import structlog
from browser_worker import BrowserWorker
from fastapi import FastAPI, HTTPException
import uvicorn

# Configure structlog
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ]
)

log = structlog.get_logger()

# Create a FastAPI app for health checks
app = FastAPI(title="Browser Worker Health API")

# Worker instance
worker = None

@app.get("/")
async def root():
    return {"message": "Browser Worker Health API"}

@app.get("/health")
async def health():
    """Health check endpoint."""
    global worker
    if worker and worker.ready:
        # Try to check Redis connection
        try:
            redis_ok = await worker.redis.ping()
        except:
            redis_ok = False
        
        return {
            "status": "healthy",
            "browser": "ready",
            "redis": "connected" if redis_ok else "disconnected"
        }
    else:
        return {
            "status": "unhealthy",
            "browser": "not ready" if worker else "not initialized"
        }

async def start_worker():
    """Start the worker process."""
    global worker
    worker = BrowserWorker()
    
    # Set up signal handlers
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown()))
    
    # Initialize and run the worker
    if await worker.initialize():
        # Start the task processing loop
        await worker.read_tasks()
    else:
        log.error("Worker initialization failed")

async def shutdown():
    """Shutdown the worker and web server."""
    global worker
    if worker:
        await worker.shutdown()

async def run_health_server():
    """Run the health check server."""
    # Get port for health server
    port = int(os.getenv("HEALTH_PORT", 3000))
    
    # Use uvicorn to run the server
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()

async def main():
    """Main entry point."""
    # Start the health server in the background
    health_server = asyncio.create_task(run_health_server())
    
    # Start the worker
    worker_task = asyncio.create_task(start_worker())
    
    # Wait for both tasks
    await asyncio.gather(health_server, worker_task)

if __name__ == "__main__":
    asyncio.run(main()) 