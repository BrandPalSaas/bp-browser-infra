from browser_use import BrowserUseAgent
from playwright.async_api import async_playwright
import os
import time
import json
import asyncio
import redis.asyncio as redis
import structlog
import socket
import signal
import ssl
from app.common.models import BrowserTask, TaskResult

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
        
        # Connect to Redis
        self.redis_host = os.getenv("REDIS_HOST", "localhost")
        self.redis_port = int(os.getenv("REDIS_PORT", 6379))
        self.redis_password = os.getenv("REDIS_PASSWORD", "")
        self.redis_ssl = os.getenv("REDIS_SSL", "false").lower() == "true"
        self.stream_name = os.getenv("REDIS_STREAM", "browser_tasks")
        self.results_stream = os.getenv("REDIS_RESULTS_STREAM", "browser_results")
        self.group_name = os.getenv("REDIS_GROUP", "browser_workers")
        self.consumer_name = f"worker-{socket.gethostname()}-{os.getpid()}"
        
        self.redis = None
    
    async def connect_to_redis(self):
        """Connect to Redis and set up streams."""
        try:
            log.info("Connecting to Redis", 
                     host=self.redis_host, 
                     port=self.redis_port,
                     ssl=self.redis_ssl)
            
            # Set up SSL if needed
            ssl_connection = None
            if self.redis_ssl:
                ssl_connection = ssl.create_default_context()
            
            # Connect to Redis
            self.redis = redis.Redis(
                host=self.redis_host, 
                port=self.redis_port,
                password=self.redis_password if self.redis_password else None,
                ssl=self.redis_ssl,
                ssl_cert_reqs=None if self.redis_ssl else None,
                ssl_context=ssl_connection
            )
            
            # Check connection
            await self.redis.ping()
            log.info("Connected to Redis successfully")
            
            # Create consumer group if it doesn't exist
            try:
                await self.redis.xgroup_create(
                    name=self.stream_name,
                    groupname=self.group_name,
                    mkstream=True,
                    id='0'  # Start from beginning
                )
                log.info("Created consumer group", group=self.group_name, stream=self.stream_name)
            except redis.ResponseError as e:
                if "BUSYGROUP" in str(e):
                    # Group already exists
                    log.info("Consumer group already exists", group=self.group_name)
                else:
                    raise
            
            return True
        except Exception as e:
            log.error("Failed to connect to Redis", error=str(e), exc_info=True)
            await asyncio.sleep(5)  # Wait before retrying
            return False
    
    async def initialize(self):
        """Initialize the worker with a browser instance."""
        if not await self.connect_to_redis():
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
    
    async def process_task(self, task_data):
        """Process a browser task."""
        try:
            task_id = task_data.get('task_id', 'unknown')
            session_id = task_data.get('session_id', 'unknown')
            task_content = task_data.get('task', '{}')
            
            if isinstance(task_content, str):
                try:
                    task_content = json.loads(task_content)
                except json.JSONDecodeError:
                    log.error("Invalid task JSON", task_id=task_id)
                    return {'error': 'Invalid task format'}
            
            log.info("Processing task", task_id=task_id, session_id=session_id)
            
            # Create a new browser context for this session
            context = await self.browser.new_context()
            
            try:
                # Initialize the BrowserUseAgent
                agent = BrowserUseAgent(
                    browser=context,
                    session_id=session_id
                )
                
                # Process the task
                result = await agent.process_task(task_content)
                log.info("Task completed", task_id=task_id)
                return result
            finally:
                # Always close the context when done
                await context.close()
        
        except Exception as e:
            log.error("Error processing task", error=str(e), task_id=task_data.get('task_id', 'unknown'), exc_info=True)
            return {'error': str(e)}
    
    async def read_tasks(self):
        """Read tasks from Redis stream."""
        while self.running:
            try:
                if not self.ready:
                    log.warning("Worker not ready, waiting...")
                    await asyncio.sleep(1)
                    continue
                
                # Read from the stream with a block of 2 seconds
                tasks = await self.redis.xreadgroup(
                    groupname=self.group_name,
                    consumername=self.consumer_name,
                    streams={self.stream_name: '>'},
                    count=1,
                    block=2000
                )
                
                if not tasks:  # No new messages
                    continue
                
                # Process each task
                for stream_name, messages in tasks:
                    for message_id, data in messages:
                        task_data = {k.decode(): v.decode() for k, v in data.items()}
                        task_data['message_id'] = message_id.decode()
                        
                        log.info("Received task", task_id=task_data.get('task_id', 'unknown'))
                        
                        # Process the task asynchronously
                        result = await self.process_task(task_data)
                        
                        # Send result back to Redis
                        result_data = {
                            'task_id': task_data.get('task_id', 'unknown'),
                            'session_id': task_data.get('session_id', 'unknown'),
                            'result': json.dumps(result),
                            'timestamp': str(int(time.time() * 1000))
                        }
                        
                        # Add result to results stream
                        await self.redis.xadd(
                            name=self.results_stream,
                            fields=result_data,
                            maxlen=10000
                        )
                        
                        # Acknowledge the message
                        await self.redis.xack(
                            name=self.stream_name,
                            groupname=self.group_name,
                            id=message_id
                        )
                        
                        log.info("Task acknowledged and result sent", 
                                task_id=task_data.get('task_id', 'unknown'))
            
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
        
        if self.redis:
            await self.redis.close()
            log.info("Redis connection closed")
    
    async def run(self):
        """Run the worker."""
        # Set up signal handlers
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(self.shutdown()))
        
        if not await self.initialize():
            log.error("Initialization failed. Exiting.")
            return
        
        # Start the main task processing loop
        await self.read_tasks()

async def main():
    worker = BrowserWorker()
    await worker.run()

if __name__ == "__main__":
    asyncio.run(main()) 