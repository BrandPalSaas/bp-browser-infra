from browser_use import Agent, BrowserConfig, Browser
import os
import json
import asyncio
import structlog
import socket
from langchain_openai import ChatOpenAI

from app.common.models import BrowserTaskStatus, TaskEntry, RawResponse
from app.common.task_manager import TaskManager
from dotenv import load_dotenv
load_dotenv()

log = structlog.get_logger(__name__)

class BrowserWorker:
    def __init__(self):
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
            log.info("Initializing browser")
            self.browser = Browser(config=BrowserConfig(headless=False, disable_security=True))
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
            raw_response = RawResponse(
                total_duration_seconds=result.total_duration_seconds(),
                total_input_tokens=result.total_input_tokens(),
                num_of_steps=result.number_of_steps(),
                is_successful=result.is_successful(),
                has_errors=result.has_errors(),
                final_result=result.final_result())

            log_ctx.info("Task completed successfully", result=raw_response)
            
            # Update task result
            await self.task_manager.update_task_result(task_id, BrowserTaskStatus.COMPLETED, response=json.dumps(raw_response.model_dump()))
            return True
        
        except Exception as e:
            log_ctx.exception("Error processing task", error=str(e), exc_info=True)
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
                        await self.task_manager.acknowledge_task(message_id=message_id)
                except Exception as e:
                    log_ctx.exception("Error processing task", error=str(e), exc_info=True)
                
            except Exception as e:
                log_ctx.exception("Error in read_tasks loop", error=str(e), exc_info=True)
                await asyncio.sleep(1)  # Avoid tight loop on persistent errors

    
    async def shutdown(self):
        """Cleanup and shutdown the worker."""
        self.running = False
        log.info("Shutting down worker")
        
        if self.browser:
            await self.browser.close()
            log.info("Browser closed")
        
        # Close Redis connection
        if self.task_manager and self.task_manager.redis:
            await self.task_manager.redis.close()
            log.info("Redis connection closed") 