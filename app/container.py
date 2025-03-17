import docker
from typing import Optional, Tuple
import socket
from contextlib import closing

class ContainerManager:
    def __init__(self):
        self.client = docker.from_env()
        self.image = "browserless/chrome"  # We can make this configurable later
    
    def _find_free_port(self) -> int:
        """Find a free port on the host machine."""
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
            s.bind(('', 0))
            s.listen(1)
            port = s.getsockname()[1]
            return port

    async def create_browser_container(self) -> Tuple[str, int, str]:
        """
        Create a new browser container.
        Returns: (container_id, port, live_view_url)
        """
        port = self._find_free_port()
        
        # Create container with debug port exposed
        container = self.client.containers.run(
            self.image,
            detach=True,
            ports={
                '3000/tcp': port,  # browserless API port
            },
            environment={
                'MAX_CONCURRENT_SESSIONS': '1',
                'WORKSPACE_DELETE_EXPIRED': 'true',
                'WORKSPACE_EXPIRE_DAYS': '1',
            }
        )
        
        live_view_url = f"http://localhost:{port}"
        return container.id, port, live_view_url

    async def stop_container(self, container_id: str) -> None:
        """Stop and remove a container."""
        try:
            container = self.client.containers.get(container_id)
            container.stop(timeout=5)  # Give it 5 seconds to stop gracefully
            container.remove()
        except docker.errors.NotFound:
            # Container already removed or doesn't exist
            pass
        except Exception as e:
            # Log the error but don't raise it
            print(f"Error stopping container {container_id}: {e}")

# Global container manager instance
container_manager = ContainerManager() 