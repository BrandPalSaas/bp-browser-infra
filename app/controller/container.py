import docker
from typing import Optional, Tuple, Dict, Any
import socket
from contextlib import closing
import os
import uuid
import requests
import time
import json
import redis.asyncio as redis
import structlog
import asyncio
import ssl
import threading

log = structlog.get_logger(__name__)

class ContainerManager:
    def __init__(self):
        # Redis configuration
        self.redis_host = os.getenv("REDIS_HOST", "localhost")
        self.redis_port = int(os.getenv("REDIS_PORT", 6379))
        self.redis_password = os.getenv("REDIS_PASSWORD", "")
        self.redis_ssl = os.getenv("REDIS_SSL", "false").lower() == "true"
        self.task_stream = os.getenv("REDIS_STREAM", "browser_tasks")
        self.results_stream = os.getenv("REDIS_RESULTS_STREAM", "browser_results")
        self.results_cache = {}  # Cache for task results
        self.redis = None
        self._listener_task = None
        
        # Check if running in Kubernetes or locally
        if "KUBERNETES_SERVICE_HOST" in os.environ:
            self.k8s_mode = True
            # Use the worker service in Kubernetes
            self.browser_service = "worker"
            self.browser_port = 3000
            log.info("Running in Kubernetes mode", 
                     service=self.browser_service, 
                     port=self.browser_port)
        else:
            # Local development fallback to Docker
            try:
                self.client = docker.from_env()
                self.k8s_mode = False
                self.image = "worker:latest"
                log.info("Running in Docker mode", image=self.image)
            except Exception as e:
                log.warning("Docker not available, falling back to localhost", 
                           error=str(e))
                # Fallback to using localhost if Docker is not available
                self.k8s_mode = True
                self.browser_service = "localhost"
                self.browser_port = 3000
                log.info("Fallback to localhost mode", 
                        service=self.browser_service, 
                        port=self.browser_port)
    
    async def initialize(self):
        """Initialize the container manager asynchronously."""
        # Connect to Redis
        if not await self.connect_to_redis():
            log.error("Failed to connect to Redis during initialization")
            return False
        
        # Start the results listener
        self._listener_task = asyncio.create_task(self._start_results_listener())
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
    
    async def _start_results_listener(self):
        """Start a background task to listen for task results."""
        # Get the last ID
        last_id = '0'
        log.info("Starting results listener")
        
        # Make sure we're connected to Redis first
        if not self.redis:
            if not await self.connect_to_redis():
                log.error("Failed to connect to Redis, can't start results listener")
                return
        
        while True:
            try:
                # Read new results
                results = await self.redis.xread(
                    streams={self.results_stream: last_id},
                    count=10,
                    block=2000
                )
                
                if results:
                    stream_name, stream_items = results[0]
                    for message_id, data in stream_items:
                        # Update the last ID
                        last_id = message_id
                        
                        # Extract the result
                        task_id = data.get(b'task_id', b'unknown').decode('utf-8')
                        session_id = data.get(b'session_id', b'unknown').decode('utf-8')
                        result_json = data.get(b'result', b'{}').decode('utf-8')
                        
                        try:
                            result = json.loads(result_json)
                            # Store in the cache
                            self.results_cache[task_id] = result
                            log.info("Received result", 
                                    task_id=task_id, 
                                    session_id=session_id, 
                                    success=result.get('success', False))
                        except json.JSONDecodeError:
                            log.error("Invalid JSON in result", task_id=task_id)
            
            except redis.ConnectionError:
                log.error("Redis connection error, reconnecting...")
                await asyncio.sleep(5)
                if not await self.connect_to_redis():
                    continue
            
            except Exception as e:
                log.error("Error processing results", error=str(e), exc_info=True)
                await asyncio.sleep(1)  # Avoid tight loop in case of persistent errors
    
    def _find_free_port(self) -> int:
        """Find a free port on the host machine."""
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
            s.bind(('', 0))
            s.listen(1)
            port = s.getsockname()[1]
            log.debug("Found free port", port=port)
            return port

    async def create_browser_container(self) -> Tuple[str, int, str]:
        """
        Get access to a browser container.
        In K8s mode, returns info for the static worker service.
        In Docker mode, creates a new container.
        
        Returns: (container_id, port, live_view_url)
        """
        log.info("Creating browser container")
        if self.k8s_mode:
            return self._get_browser_service()
        else:
            return self._create_docker_container()
    
    def _get_browser_service(self) -> Tuple[str, int, str]:
        """
        Get the browser service info.
        Instead of creating a new pod, we'll use the static worker service.
        """
        # Generate a session ID - not a real container ID, but used for tracking
        session_id = f"session-{uuid.uuid4().hex[:8]}"
        log_ctx = log.bind(session_id=session_id)
        
        # In Kubernetes, we'll use the service name for access
        live_view_url = f"http://{self.browser_service}:{self.browser_port}"
        log_ctx.info("Getting browser service", url=live_view_url)
        
        # Check if the service is available
        retries = 0
        while retries < 5:
            try:
                # Simple healthcheck to see if service is available
                response = requests.get(f"{live_view_url}/healthz", timeout=2)
                if response.status_code == 200:
                    log_ctx.info("Service healthcheck successful")
                    break
            except Exception as e:
                log_ctx.warning("Service healthcheck failed", 
                              retry=retries+1, 
                              error=str(e))
            
            time.sleep(1)
            retries += 1
        
        if retries >= 5:
            log_ctx.warning("Max retries reached for service healthcheck")
        
        return session_id, self.browser_port, live_view_url
    
    def _create_docker_container(self) -> Tuple[str, int, str]:
        """Create a Docker container for browser worker (fallback method)."""
        port = self._find_free_port()
        
        log.info("Creating Docker container", port=port)
        
        # Create container with debug port exposed
        container = self.client.containers.run(
            self.image,
            detach=True,
            ports={
                '3000/tcp': port,  # browser worker port
            },
            environment={
                'REDIS_HOST': self.redis_host,
                'REDIS_PORT': str(self.redis_port),
                'HEALTH_PORT': '3000'
            },
            command=["python", "browser_worker.py"]
        )
        
        container_id = container.id
        log_ctx = log.bind(container_id=container_id[:12])
        log_ctx.info("Container created successfully")
        
        # Wait for container to start
        log_ctx.debug("Waiting for container to start")
        time.sleep(2)
        
        live_view_url = f"http://localhost:{port}"
        log_ctx.info("Container ready", url=live_view_url)
        return container_id, port, live_view_url

    async def execute_task(self, session_id: str, task: str) -> Dict[str, Any]:
        """
        Execute a task on the browser worker using Redis.
        
        Args:
            session_id: The ID of the session
            task: The task description to send to the browser-use agent
            
        Returns:
            The result from the browser worker
        """
        task_id = f"task-{uuid.uuid4().hex}"
        log_ctx = log.bind(task_id=task_id, session_id=session_id)
        
        try:
            # Check Redis connection
            if not hasattr(self, 'redis') or not await self.redis.ping():
                log_ctx.warning("Redis connection lost, reconnecting...")
                if not await self.connect_to_redis():
                    log_ctx.error("Failed to connect to Redis")
                    return {
                        "success": False,
                        "error": "Failed to connect to Redis"
                    }
            
            # Add task to the stream
            task_data = {
                'task_id': task_id,
                'session_id': session_id,
                'task': task,
                'timestamp': int(time.time() * 1000),
            }
            
            log_ctx.info("Adding task to Redis stream", task_length=len(task))
            await self.redis.xadd(
                name=self.task_stream,
                fields=task_data,
                maxlen=1000,  # Limit stream length
                approximate=True
            )
            
            # Wait for the result
            start_time = time.time()
            timeout = 60  # 60 seconds timeout
            
            while time.time() - start_time < timeout:
                # Check if result is in cache
                if task_id in self.results_cache:
                    result = self.results_cache[task_id]
                    # Remove from cache
                    del self.results_cache[task_id]
                    log_ctx.info("Got result from cache", 
                                success=result.get('success', False))
                    return result
                
                # Wait a bit
                await asyncio.sleep(0.5)
            
            # Timeout
            log_ctx.warning("Task execution timed out")
            return {
                "success": False,
                "error": "Task execution timed out"
            }
        
        except Exception as e:
            log_ctx.error("Error executing task", error=str(e), exc_info=True)
            return {
                "success": False,
                "error": f"Error executing task: {str(e)}"
            }

    async def stop_container(self, container_id: str) -> None:
        """
        Stop container tracking.
        In K8s mode, this is a no-op since we're using a static service.
        In Docker mode, this stops and removes the container.
        """
        log_ctx = log.bind(container_id=container_id[:12] if container_id else None)
        
        if not self.k8s_mode:
            log_ctx.info("Stopping container")
            self._stop_docker_container(container_id)
        else:
            log_ctx.debug("No-op in Kubernetes mode")
    
    def _stop_docker_container(self, container_id: str) -> None:
        """Stop a Docker container (fallback method)."""
        log_ctx = log.bind(container_id=container_id[:12])
        
        try:
            log_ctx.info("Getting container")
            container = self.client.containers.get(container_id)
            
            log_ctx.info("Stopping container")
            container.stop(timeout=5)  # Give it 5 seconds to stop gracefully
            
            log_ctx.info("Removing container")
            container.remove()
            
            log_ctx.info("Container stopped and removed successfully")
        except docker.errors.NotFound:
            # Container already removed or doesn't exist
            log_ctx.warning("Container not found (already removed)")
        except Exception as e:
            # Log the error but don't raise it
            log_ctx.error("Error stopping container", error=str(e), exc_info=True)

# Global container manager instance (not initialized yet)
container_manager = ContainerManager() 