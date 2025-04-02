import os
import uuid
import json
import redis.asyncio as redis
import structlog
import asyncio
from datetime import datetime
from typing import Callable, Dict, Optional, Union, Any, List, Set
from playwright._impl._api_structures import Cookie

from app.models import BrowserTaskRequest, BrowserTaskStatus, BrowserTaskResponse, TaskEntry
from app.common.constants import BROWSER_TASKS_STREAM, TASK_RESULTS_KEY_SUFFIX, REDIS_RESULT_EXPIRATION_SECONDS, REDIS_COOKIES_KEY_FMT
log = structlog.get_logger(__name__)

# Define a callback type for task status listeners (worker_id, task_id, status, response)
TaskStatusCallback = Callable[[str, str, BrowserTaskStatus, str], None]
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()
# Singleton TaskManager, use get_task_manager() to get the TaskManager instance instead of TaskManager() directly 
class TaskManager:
    """The task manager manages the tasks and results in Redis."""
    
    def __init__(self):
        # Redis configuration
        self.redis_host = os.getenv("REDIS_HOST", "localhost")
        self.redis_port = int(os.getenv("REDIS_PORT", 6379))
        self.redis_password = os.getenv("REDIS_PASSWORD", "")
        self.redis_db = int(os.getenv("REDIS_DB", 0))
        self.redis_ssl = os.getenv("REDIS_SSL", "false").lower() == "true"
        # self.task_stream = BROWSER_TASKS_STREAM
        self.results_key_suffix = TASK_RESULTS_KEY_SUFFIX
        self.group_name = "browser_workers"
        self.redis = None
        
        # Task status listeners
        self.status_listeners: Set[TaskStatusCallback] = set()
    
    async def save_cookies(self, username: str, cookies: List[Cookie]):
        await self.redis.set(REDIS_COOKIES_KEY_FMT.format(username), json.dumps(cookies))
    
    async def get_cookies(self, username: str) -> List[Cookie]:
        cookies_json = await self.redis.get(REDIS_COOKIES_KEY_FMT.format(username))
        return json.loads(cookies_json) if cookies_json else []
    
    def add_status_listener(self, callback: TaskStatusCallback) -> None:
        """Register a callback to receive task status updates.
        
        Args:
            callback: A function that will be called when task status changes
                with parameters (task_id, status, result_data)
        """
        self.status_listeners.add(callback)
        log.info("Task status listener registered")
    
    def remove_status_listener(self, callback: TaskStatusCallback) -> None:
        """Remove a previously registered callback.
        
        Args:
            callback: The callback function to remove
        """
        if callback in self.status_listeners:
            self.status_listeners.remove(callback)
            log.info("Task status listener removed")
    
    def _notify_listeners(self, worker_id: str, task_id: str, status: BrowserTaskStatus, result_data: str = None) -> None:
        """Notify all registered listeners about a task status change.
        
        Args:
            task_id: The ID of the task
            status: The status of the task (BrowserTaskStatus enum)
            result_data: The task result data for completed/failed tasks
        """
        for listener in self.status_listeners:
            try:
                listener(worker_id, task_id, status, result_data)
            except Exception as e:
                log.error(f"Error in task status listener", error=str(e), exc_info=True)

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
            
            # Connection parameters
            connection_params = {
                "host": self.redis_host, 
                "port": self.redis_port,
                "password": self.redis_password if self.redis_password else None,
                "ssl": self.redis_ssl,
                "db": self.redis_db
            }
            
            # Some Redis clients use ssl_cert_reqs instead of ssl_context
            if self.redis_ssl:
                connection_params["ssl_cert_reqs"] = None
            
            # Connect to Redis
            self.redis = redis.Redis(**connection_params)
            
            # Check connection
            await self.redis.ping()
            log.info("Connected to Redis successfully")
            return True
        except Exception as e:
            log.exception("Failed to connect to Redis", error=str(e), exc_info=True)
            return False

    async def ensure_redis_connection(self) -> bool:
        """Reconnect to Redis if needed."""
        if not self.redis or not await self.redis.ping():
            log.warning("Redis connection lost, reconnecting...")
            if not await self.connect_to_redis():
                log.error("Failed to reconnect to Redis")
                return False
        return True

    def get_task_result_key(self, task_id: str) -> str:
        return f"{task_id}_{self.results_key_suffix}"

    async def submit_task(self, task_data: BrowserTaskRequest) -> BrowserTaskResponse:
        """
        Submit a task to the Redis queue.
        
        Args:
            task_data: The task data to submit
            
        Returns:
            A dictionary with task_id and status
        """
        # Create a task_id with mmddhhmmss and uuid suffix
        task_id = f'task-{datetime.now().strftime("%m%d-%H%M")}-{uuid.uuid4().hex[:8]}'
        log_ctx = log.bind(task_id=task_id)
        
        try:
            # Check Redis connection
            if not await self.ensure_redis_connection():
                return BrowserTaskResponse(task_id=task_id, task_status=BrowserTaskStatus.FAILED, task_response="Failed to connect to Redis")
            
            # Add task to the stream
            redis_task = {'task_id': task_id }
            
            # Initialize the task result in Redis with pending status
            result_key = self.get_task_result_key(task_id)
            initial_result = BrowserTaskResponse(task_id=task_id, task_status=BrowserTaskStatus.WAITING)
            entry = TaskEntry(
                task_id=task_id,
                request=task_data,
                response=initial_result,
                created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )
            
            # Store the initial result
            await self.redis.set(result_key, json.dumps(entry.model_dump()), ex=REDIS_RESULT_EXPIRATION_SECONDS)
            
            # Add to task stream
            log_ctx.info("Adding task to Redis stream", task_id=task_id, task_data=task_data)
            await self.redis.xadd(
                name=task_data.task_queue_name(), # tts task has a unique task queue for each shop
                fields=redis_task,
                maxlen=10000,  # Limit stream length
                approximate=True
            )
            return initial_result

        except Exception as e:
            log_ctx.exception("Error submitting task", error=str(e), exc_info=True)
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
        result_key = self.get_task_result_key(task_id)
        
        try:
            # Check Redis connection
            if not await self.ensure_redis_connection():
                return BrowserTaskResponse(task_id=task_id, task_status=BrowserTaskStatus.FAILED, task_response="Failed to connect to Redis")
            
            # Try to get the result
            result_json = await self.redis.get(result_key)
            
            if result_json:
                # Parse the result
                result = json.loads(result_json)
                entry = TaskEntry(**result)
                log_ctx.info("Result found", task_id=task_id, result=entry.response)
                return entry.response
            
            log_ctx.error("Result not found", task_id=task_id)
            return BrowserTaskResponse(task_id=task_id, task_status=BrowserTaskStatus.FAILED, task_response="Result not found")
        
        except Exception as e:
            log_ctx.exception("Error getting result", error=str(e), exc_info=True)
            return BrowserTaskResponse(task_id=task_id, task_status=BrowserTaskStatus.FAILED, task_response=f"Error getting result: {str(e)}")
    
    async def create_consumer_group(self, task_queue_name: str) -> bool:
        """Create consumer group for task processing if it doesn't exist."""
        try:
            if not await self.ensure_redis_connection():
                return False
                
            # Create consumer group if it doesn't exist
            try:
                await self.redis.xgroup_create(
                    name=task_queue_name,
                    groupname=self.group_name,
                    mkstream=True,
                    id='0'  # Start from beginning
                )
                log.info("Created consumer group", group=self.group_name, stream=task_queue_name)
            except redis.ResponseError as e:
                if "BUSYGROUP" in str(e):
                    # Group already exists
                    log.info("Consumer group already exists", group=self.group_name)
                else:
                    raise
                    
            return True
        except Exception as e:
            log.exception("Failed to create consumer group", error=str(e), exc_info=True)
            return False
    
    async def read_next_task(self, consumer_name: str, task_queue_name: str, block_ms=2000) -> tuple[str, TaskEntry] | None:
        """
        Read the next task from the Redis stream.
        
        Args:
            consumer_name: The name of the consumer (usually worker ID)
            task_queue_name: The name of the task queue (by tts shop name)
            block_ms: How long to block waiting for a new message (in milliseconds)
            
        Returns:
            Task data or None if no task is available
        """
        try:
            if not await self.ensure_redis_connection():
                return None
                
            # Read from the stream
            tasks = await self.redis.xreadgroup(
                groupname=self.group_name,
                consumername=consumer_name,
                streams={task_queue_name: '>'},
                count=1,
                block=block_ms
            )
            
            if not tasks:  # No new messages
                return None
                
            log.info("Tasks found", task_count=len(tasks))
                
            # Process the first task
            for stream_name, messages in tasks:
                for message_id, data in messages:
                    # Convert binary keys and values to strings
                    task_data = {k.decode('utf-8') if isinstance(k, bytes) else k: 
                                v.decode('utf-8') if isinstance(v, bytes) else v 
                                for k, v in data.items()}
                    resolved_message_id = message_id.decode('utf-8') if isinstance(message_id, bytes) else message_id
                    
                    # Get the task details from Redis
                    task_id = task_data.get('task_id')
                    if task_id:
                        result_key = self.get_task_result_key(task_id)
                        result_json = await self.redis.get(result_key)
                        
                        if result_json:
                            # Update the task status to running
                            try:
                                entry = TaskEntry(**json.loads(result_json))
                                entry.response.task_status = BrowserTaskStatus.RUNNING
                                entry.start_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                await self.redis.set(result_key, json.dumps(entry.model_dump()), ex=REDIS_RESULT_EXPIRATION_SECONDS)

                                return resolved_message_id, entry
                            except Exception as e:
                                log.exception("Error updating task status", task_id=task_id, error=str(e))
                                return
                    
                    log.error("Task found in stream but no valid entry in Redis", task_id=task_id)
                    return

        except Exception as e:
            log.exception("Error reading task", error=str(e), exc_info=True)
            await asyncio.sleep(1)  # Avoid tight loop on persistent errors
    
    async def acknowledge_task(self, message_id: str, task_queue_name: str):
        """
        Acknowledge that a task has been processed.
        """
        try:
            if not await self.ensure_redis_connection():
                return
                
            await self.redis.xack(task_queue_name, self.group_name, message_id)
            log.info("Task acknowledged", message_id=message_id)
        except Exception as e:
            log.exception("Error acknowledging task", error=str(e), exc_info=True, message_id=message_id)
    
    async def update_task_result(self, worker_id: str, task_id: str, status: BrowserTaskStatus, response=None, exception=None) -> bool:
        """
        Update the result of a task in Redis.
        
        Args:
            task_id: The ID of the task to update
            status: The new status (completed, failed, etc.)
            response: The task response (if any)
            exception: Exception info (if failed)
            worker_name: The name of the worker processing the task
        """
        try:
            if not await self.ensure_redis_connection():
                return False
                
            # Get the current entry
            result_key = self.get_task_result_key(task_id)
            result_json = await self.redis.get(result_key)
            
            if not result_json:
                log.error("Task not found for update", task_id=task_id)
                return False
                
            # Update the entry
            entry = TaskEntry(**json.loads(result_json))
            entry.response.task_status = status
            
            if response:
                entry.response.task_response = response
                
            if exception:
                entry.response.task_response = f"Error: {str(exception)}"
                
            entry.response.worker_name = worker_id
                
            if status == BrowserTaskStatus.COMPLETED or status == BrowserTaskStatus.FAILED:
                entry.end_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
            # Save the updated entry
            await self.redis.set(
                result_key, 
                json.dumps(entry.model_dump()), 
                ex=REDIS_RESULT_EXPIRATION_SECONDS
            )
            
            # Notify status listeners
            self._notify_listeners(worker_id, task_id, status, entry.response.task_response)
            
            return True
        except Exception as e:
            log.exception("Error updating task", 
                        error=str(e), 
                        exc_info=True, 
                        task_id=task_id)
            return False


# TaskManager Singleton
_task_manager = None

# Use get_task_manager() to get the TaskManager instance instead of TaskManager() directly 
# This ensures that the TaskManager instance is a singleton
async def get_task_manager() -> TaskManager:
    """Dependency function to get the TaskManager instance."""
    global _task_manager
    if _task_manager is None:
        _task_manager = TaskManager()
        if not await _task_manager.initialize():
            raise Exception("Failed to initialize task manager")
        log.info("Task manager initialized successfully")
    return _task_manager

# Add a shutdown function for cleanup
async def shutdown_task_manager():
    """Clean up the task manager when the application shuts down."""
    global _task_manager
    if _task_manager and _task_manager.redis:
        await _task_manager.redis.close()
        _task_manager = None 