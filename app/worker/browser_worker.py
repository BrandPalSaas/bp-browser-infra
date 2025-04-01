from browser_use import Agent, BrowserConfig, Browser
import os
import json
import asyncio
import structlog
import socket
from langchain_openai import ChatOpenAI
import random
import string
import traceback

from browser_use.browser.context import BrowserContextConfig

from app.models import BrowserTaskStatus, TaskEntry, RawResponse, TTShop, TTSPlaywrightTaskType, TTSBrowserUseTask
from app.common.task_manager import get_task_manager
from app.common.constants import TASK_RESULTS_DIR
from app.login.tts import TTSLoginManager
from dotenv import load_dotenv
from lmnr import Laminar, Instruments

load_dotenv()

log = structlog.get_logger(__name__)

Laminar.initialize(
    project_api_key=os.getenv("LMNR_PROJECT_API_KEY"),
    instruments={Instruments.BROWSER_USE, Instruments.OPENAI, Instruments.REDIS}
)

# BrowserWorker is a singleton, use get_browser_worker() to get the BrowserWorker instance instead of BrowserWorker() directly 
# This ensures that the BrowserWorker instance is a singleton
class BrowserWorker:
    """The browser worker processes browser automation tasks"""
    
    def __init__(self, shop: TTShop):
        """Initialize the worker, only work for this shop"""
        self._browser = None
        self._running = True
        self._shop = shop
        
        random_id = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
        self._worker_id = f"worker-{socket.gethostname()}-{random_id}"
        
        self._login_manager = TTSLoginManager()
        self._cookies_file = None
        self._created_consumer_groups = set()

    @property
    def id(self) -> str:
        return self._worker_id
    
    @property
    def browser_instance(self) -> Browser:
        return self._browser

    async def initialize(self):
        """Initialize the worker and connect to Redis."""
        try:
            log.info("Initializing browser", name=self.id, shop=str(self._shop))
            self._cookies_file = await self._login_manager.save_login_cookies_to_tmp_file(self._shop)
            if self._cookies_file:
                log.info("Using cookies file", cookies_file=self._cookies_file, shop=str(self._shop))
                context_config = BrowserContextConfig(cookies_file=self._cookies_file)
                self._browser = Browser(config=BrowserConfig(headless=False, disable_security=True, new_context_config=context_config))
            else:
                self._browser = Browser(config=BrowserConfig(headless=False, disable_security=True))

            log.info("Browser initialized and ready")
            return True
        except Exception as e:
            log.error("Failed to initialize browser", error=str(e), exc_info=True)
            return False
    
    async def process_task(self, entry: TaskEntry) -> bool:
        task_id = entry.task_id
        log_ctx = log.bind(task_id=task_id)
        task_manager = await get_task_manager()

        try:
            log_ctx.info("Processing task", entry=entry)
            
            # Ensure results directory exists
            if not os.path.exists(TASK_RESULTS_DIR):
                os.makedirs(TASK_RESULTS_DIR)
            
            # Update status to running
            await task_manager.update_task_result(
                worker_id=self.id,
                task_id=task_id, 
                status=BrowserTaskStatus.RUNNING
            )
            
            if isinstance(entry.request.task, TTSBrowserUseTask):
                raw_response = await self.process_browser_use_task(log_ctx, task_id, entry.request.task)
            elif isinstance(entry.request.task, TTSPlaywrightTaskType):
                raw_response = await self.process_playwright_task(log_ctx, task_id, entry.request.task)
            else:
                raise ValueError(f"Unknown task type: {type(entry.request.task)}")
            
            log_ctx.info("Task completed successfully", result=raw_response)
            
            # Update task result
            await task_manager.update_task_result(
                worker_id=self.id,
                task_id=task_id, 
                status=BrowserTaskStatus.COMPLETED, 
                response=json.dumps(raw_response.model_dump() if raw_response else "")
            )
                
            return True
        
        except Exception as e:
            log_ctx.exception("Error processing task", error=str(e), exc_info=True)
            
            error_response = {
                "error": str(e),
                "stacktrace": traceback.format_exc()
            }
            
            await task_manager.update_task_result(
                worker_id=self.id,
                task_id=task_id, 
                status=BrowserTaskStatus.FAILED, 
                response=json.dumps(error_response)
            )
            return False


    async def process_browser_use_task(self, log_ctx: structlog.stdlib.BoundLogger, task_id: str, task: TTSBrowserUseTask) -> RawResponse:
            gif_path = f"{TASK_RESULTS_DIR}/{task_id}.gif"
            # Initialize the BrowserUse Agent
            agent = Agent(
                browser=self._browser,
                task=task.description,
                llm=ChatOpenAI(model="gpt-4o-mini"),
                generate_gif=gif_path
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
            return raw_response

    async def process_playwright_task(self, log_ctx: structlog.stdlib.BoundLogger, task_id: str, task: TTSPlaywrightTaskType):
        ## TODO: process playwright task
        log_ctx.info("Processing playwright task", task_id=task_id, task=task)
        
        

    async def read_tasks(self):
        """Read tasks from Redis stream and process them."""
        # Ensure consumer group exists
        task_manager = await get_task_manager()

        task_queue_name = self._shop.task_queue_name()
        if task_queue_name not in self._created_consumer_groups:
            await task_manager.create_consumer_group(task_queue_name)
            self._created_consumer_groups.add(task_queue_name)

        while self._running:
            try:
                # This claims the message but doesn't acknowledge it yet
                task_data = await task_manager.read_next_task(self.id)
                
                if not task_data:  # No new messages
                    continue
                
                message_id, entry = task_data
                log_ctx = log.bind(task_id=entry.task_id)
                log_ctx.info("Received task", message_id=message_id, shop=str(self._shop))
                try:
                    process_success = await self.process_task(entry=entry)
                    log_ctx.info("Task processed", process_success=process_success)
                    if process_success:
                        await task_manager.acknowledge_task(message_id=message_id, task_queue_name=task_queue_name)
                except Exception as e:
                    log_ctx.exception("Error processing task", error=str(e), exc_info=True)
                
            except Exception as e:
                log_ctx.exception("Error in read_tasks loop", error=str(e), exc_info=True)
                await asyncio.sleep(1)  # Avoid tight loop on persistent errors
    
    async def shutdown(self):
        """Shutdown the browser worker."""
        self._running = False
        await self._browser.close()
        log.info("Browser worker shutdown complete")


# BrowserWorker Singleton
_browser_worker = None

# Use get_browser_worker() to get the BrowserWorker instance instead of BrowserWorker() directly 
# This ensures that the BrowserWorker instance is a singleton
async def get_browser_worker():
    global _browser_worker
    if _browser_worker is None:
        _browser_worker = BrowserWorker()
        if not await _browser_worker.initialize():
            raise Exception("Failed to initialize browser worker")
    return _browser_worker

async def shutdown_browser_worker():
    global _browser_worker
    if _browser_worker:
        await _browser_worker.shutdown()
        _browser_worker = None