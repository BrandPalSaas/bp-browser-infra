import os
import uuid
import time
import json
import redis.asyncio as redis
import structlog
import ssl

from app.common.models import BrowserTaskRequest, BrowserTaskStatus, BrowserTaskResponse

log = structlog.get_logger(__name__)

class TaskManager:
    def __init__(self):
        # Redis configuration
        self.redis_host = os.getenv("REDIS_HOST", "localhost")
        self.redis_port = int(os.getenv("REDIS_PORT", 6379))
        self.redis_password = os.getenv("REDIS_PASSWORD", "")
        self.redis_ssl = os.getenv("REDIS_SSL", "false").lower() == "true"
        self.task_stream = os.getenv("REDIS_STREAM", "browser_tasks")
        self.results_key_prefix = "task_result_"
        self.redis = None
        
    async def initialize(self):
        """Initialize the task manager asynchronously."""
        # Connect to Redis
        if not await self.connect_to_redis():
            log.error("Failed to connect to Redis during initialization")
            return False
        return True
    
    async def connect_to_redis(self):
        """Connect to Redis."""
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
            return True
        except Exception as e:
            log.error("Failed to connect to Redis", error=str(e), exc_info=True)
            return False

    async def ensure_redis_connection(self) -> bool:
        """Reconnect to Redis if needed."""
        if not self.redis or not await self.redis.ping():
            log.warning("Redis connection lost, reconnecting...")
            if not await self.connect_to_redis():
                log.error("Failed to reconnect to Redis")
                return False
        return True

    async def submit_task(self, task_data: BrowserTaskRequest) -> BrowserTaskResponse:
        """
        Submit a task to the Redis queue.
        
        Args:
            task_data: The task data to submit
            
        Returns:
            A dictionary with task_id and status
        """
        task_id = f"task-{uuid.uuid4().hex}"
        log_ctx = log.bind(task_id=task_id)
        
        try:
            # Check Redis connection
            if not await self.ensure_redis_connection():
                return BrowserTaskResponse(task_id=task_id, task_status=BrowserTaskStatus.FAILED, task_response="Failed to connect to Redis")
            
            # Add task to the stream
            redis_task = {
                'task_id': task_id,
                'payload': json.dumps(task_data.model_dump()),
                'enqueue_at': str(int(time.time() * 1000)),
            }
            
            # Initialize the task result in Redis with pending status
            result_key = f"{self.results_key_prefix}{task_id}"
            initial_result = BrowserTaskResponse(task_id=task_id, task_status=BrowserTaskStatus.WAITING)
            
            # Store the initial result
            await self.redis.set(result_key, json.dumps(initial_result.model_dump()), ex=36000)  # 10 hour expiry
            
            # Add to task stream
            log_ctx.info("Adding task to Redis stream", task_id=task_id, task_data=task_data)
            await self.redis.xadd(
                name=self.task_stream,
                fields=redis_task,
                maxlen=100000,  # Limit stream length
                approximate=True
            )
            return BrowserTaskResponse(task_id=task_id, task_status=BrowserTaskStatus.WAITING)

        except Exception as e:
            log_ctx.error("Error submitting task", error=str(e), exc_info=True)
            return BrowserTaskResponse(task_id=task_id, task_status=BrowserTaskStatus.FAILED, task_response=f"Error submitting task: {e}")

    async def get_task_result(self, task_id) -> BrowserTaskResponse:
        """
        Get the result of a task from Redis.
        
        Args:
            task_id: The ID of the task to get the result for

        Returns:
            The task result or an error response
        """
        log_ctx = log.bind(task_id=task_id)
        result_key = f"{self.results_key_prefix}{task_id}"
        
        try:
            # Check Redis connection
            if not await self.ensure_redis_connection():
                return BrowserTaskResponse(task_id=task_id, task_status=BrowserTaskStatus.FAILED, task_response="Failed to connect to Redis")
            
            # Try to get the result
            result_json = await self.redis.get(result_key)
            
            if result_json:
                # Parse the result
                result = json.loads(result_json)
                return BrowserTaskResponse(**result)
            
            log_ctx.error("Result not found", task_id=task_id)
            return BrowserTaskResponse(task_id=task_id, task_status=BrowserTaskStatus.FAILED, task_response="Result not found")
        
        except Exception as e:
            log_ctx.error("Error getting result", error=str(e), exc_info=True)
            return BrowserTaskResponse(task_id=task_id, task_status=BrowserTaskStatus.FAILED, task_response=f"Error getting result: {str(e)}")

# Global task manager instance (not initialized yet)
task_manager = TaskManager() 