import docker
from typing import Optional, Tuple, Dict, Any
import socket
from contextlib import closing
import os
import uuid
import requests
import time
import json
import structlog

# Configure structlog
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ]
)

log = structlog.get_logger()

class ContainerManager:
    def __init__(self):
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
        Execute a task on the browser worker.
        
        Args:
            session_id: The ID of the session
            task: The task description to send to the browser-use agent
            
        Returns:
            The result from the browser worker
        """
        log_ctx = log.bind(session_id=session_id)
        
        # Look up the session
        if hasattr(self, 'sessions') and session_id in self.sessions:
            session = self.sessions[session_id]
            url = session['live_view_url']
            log_ctx.info("Using session URL", url=url)
        else:
            # In K8s mode or if session not found, use the service URL
            url = f"http://{self.browser_service}:{self.browser_port}"
            log_ctx.info("Using service URL", url=url)
            
        # Send the task to the worker
        try:
            log_ctx.info("Executing task", task_length=len(task))
            response = requests.post(
                f"{url}/execute",
                json={"task": task},
                timeout=30
            )
            if response.status_code == 200:
                result = response.json()
                if result.get("success"):
                    log_ctx.info("Task executed successfully", 
                                result_length=len(str(result.get("result", ""))))
                else:
                    log_ctx.warning("Task execution failed", 
                                   error=result.get("error"))
                return result
            else:
                error_msg = f"Worker returned status code: {response.status_code}"
                log_ctx.error("Request failed", status_code=response.status_code)
                return {
                    "success": False,
                    "error": error_msg
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

# Global container manager instance
container_manager = ContainerManager() 