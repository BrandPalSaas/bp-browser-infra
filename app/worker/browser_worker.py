from browser_use import BrowserUseAgent
from playwright.async_api import async_playwright
import os
import time
import json
import asyncio
import structlog
import socket
from app.common.models import BrowserTaskStatus, TaskEntry
from app.common.task_manager import TaskManager

from dotenv import load_dotenv
load_dotenv()

# Configure structlog
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ]
)

log = structlog.get_logger()

class BrowserWorker:
    def __init__(self):
        self.playwright = None
        self.browser = None
        self.ready = False
        self.running = True
        self.consumer_name = f"worker-{socket.gethostname()}-{os.getpid()}"
        
        # Task manager for Redis interactions
        self.task_manager = TaskManager()
    
    async def initialize(self):
        """Initialize the worker with a browser instance and Redis connection."""
        if not await self.task_manager.initialize():
            log.error("Failed to connect to Redis. Exiting.")
            return False
        
        try:
            log.info("Initializing Playwright and browser")
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                headless=False,
                args=['--no-sandbox', '--disable-setuid-sandbox']
            )
            self.ready = True
            log.info("Browser initialized and ready")
            return True
        except Exception as e:
            log.error("Failed to initialize browser", error=str(e), exc_info=True)
            return False
    
    async def process_task(self, task_id: str, entry: TaskEntry):

        """Process a browser task."""
        if not entry:
            log.error("Task entry not found", task_id=task_id)
            await self.task_manager.update_task_result(
                task_id, 
                BrowserTaskStatus.FAILED, 
                exception="Task entry not found"
            )
            return
        
        log_ctx = log.bind(task_id=task_id)
        try:
            log_ctx.info("Processing task")
            
            # Update status to running
            await self.task_manager.update_task_result(task_id, BrowserTaskStatus.RUNNING)
            
            # Create a new browser context for this task
            context = await self.browser.new_context()
            
            try:
                # Initialize the BrowserUseAgent
                agent = BrowserUseAgent(
                    browser=context,
                    session_id=task_id
                )
                
                # Process the task
                result = await agent.process_task(entry.request)
                log_ctx.info("Task completed successfully")
                
                # Update task result
                await self.task_manager.update_task_result(
                    task_id, 
                    BrowserTaskStatus.COMPLETED, 
                    response=result
                )
                
            except Exception as e:
                log_ctx.error("Error in browser agent", error=str(e), exc_info=True)
                await self.task_manager.update_task_result(
                    task_id, 
                    BrowserTaskStatus.FAILED, 
                    exception=str(e)
                )
            finally:
                # Always close the context when done
                await context.close()
        
        except Exception as e:
            log_ctx.error("Error processing task", error=str(e), exc_info=True)
            await self.task_manager.update_task_result(
                task_id, 
                BrowserTaskStatus.FAILED, 
                exception=str(e)
            )
    
    async def read_tasks(self):
        """Read tasks from Redis stream and process them."""
        # Ensure consumer group exists
        await self.task_manager.create_consumer_group()
        
        while self.running:
            try:
                if not self.ready:
                    log.warning("Worker not ready, waiting...")
                    await asyncio.sleep(1)
                    continue
                
                # Read from the stream using consumer group
                # This claims the message but doesn't acknowledge it yet
                task_data = await self.task_manager.read_next_task(self.consumer_name)
                
                if not task_data:  # No new messages
                    continue
                
                task_id = task_data.get('task_id', 'unknown')
                message_id = task_data.get('message_id', 'unknown')
                log.info("Received task", task_id=task_id, message_id=message_id)
                
                try:
                    # Process the task
                    await self.process_task(task_data)
                    
                    # Acknowledge only after successful processing
                    ack_success = await self.task_manager.acknowledge_task(task_data)
                    if ack_success:
                        log.info("Task acknowledged after successful processing", task_id=task_id)
                    else:
                        log.error("Failed to acknowledge task", task_id=task_id)
                except Exception as e:
                    log.error("Error processing task", task_id=task_id, error=str(e), exc_info=True)
                    # Don't acknowledge - will be redelivered to another consumer after idle timeout
                
            except Exception as e:
                log.error("Error in read_tasks loop", error=str(e), exc_info=True)
                await asyncio.sleep(1)  # Avoid tight loop on persistent errors

    
    async def shutdown(self):
        """Cleanup and shutdown the worker."""
        self.running = False
        log.info("Shutting down worker")
        
        if self.browser:
            await self.browser.close()
            log.info("Browser closed")
        
        if self.playwright:
            await self.playwright.stop()
            log.info("Playwright stopped")
        
        # Close Redis connection
        if self.task_manager and self.task_manager.redis:
            await self.task_manager.redis.close()
            log.info("Redis connection closed") 