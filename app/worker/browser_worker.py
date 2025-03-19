from browser_use import Agent
from playwright.async_api import async_playwright
import os
import time
import json
import asyncio
import structlog
import socket
from app.common.models import BrowserTaskStatus, TaskEntry
from app.common.task_manager import TaskManager
from langchain_openai import ChatOpenAI
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
    
    async def process_task(self, entry: TaskEntry) -> bool:
        
        task_id = entry.task_id
        log_ctx = log.bind(task_id=task_id)
        try:
            log_ctx.info("Processing task", entry=entry)
            
            # Update status to running
            await self.task_manager.update_task_result(task_id, BrowserTaskStatus.RUNNING)
            
            # Initialize the BrowserUse Agent
            agent = Agent(
                browser=self.browser,
                task=entry.request.task_description,
                llm=ChatOpenAI(model="gpt-4o")
            )
            
            # Process the task
            result = await agent.run()
            log_ctx.info("Task completed successfully", result=result)
            
            # Update task result
            await self.task_manager.update_task_result(task_id, BrowserTaskStatus.COMPLETED, response=json.dumps(result.model_dump()))
            return True
        
        except Exception as e:
            log_ctx.error("Error processing task", error=str(e), exc_info=True)
            await self.task_manager.update_task_result(task_id, BrowserTaskStatus.FAILED, exception=str(e))
            return False

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
                
                # This claims the message but doesn't acknowledge it yet
                task_data = await self.task_manager.read_next_task(self.consumer_name)
                
                if not task_data:  # No new messages
                    continue
                
                message_id, entry = task_data
                log_ctx = log.bind(task_id=entry.task_id)
                log_ctx.info("Received task", message_id=message_id)
                try:
                    process_success = await self.process_task(entry=entry)
                    log_ctx.info("Task processed", process_success=process_success)
                    if process_success:
                        await self.task_manager.acknowledge_task(message_id=message_id):
                except Exception as e:
                    log_ctx.error("Error processing task", error=str(e), exc_info=True)
                
            except Exception as e:
                log_ctx.error("Error in read_tasks loop", error=str(e), exc_info=True)
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