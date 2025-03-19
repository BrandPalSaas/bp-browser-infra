import os
import asyncio
import redis.asyncio as redis
from aiohttp import web
import structlog

log = structlog.get_logger()

class HealthCheck:
    def __init__(self):
        self.redis_host = os.getenv("REDIS_HOST", "localhost")
        self.redis_port = int(os.getenv("REDIS_PORT", 6379))
        self.redis_password = os.getenv("REDIS_PASSWORD", "")
        self.redis_ssl = os.getenv("REDIS_SSL", "false").lower() == "true"
        self.redis = None
        self.app = web.Application()
        self.app.router.add_get('/healthz', self.healthz)
        self.port = int(os.getenv("HEALTH_PORT", 3000))
    
    async def connect_to_redis(self):
        """Connect to Redis to check health."""
        try:
            # Connect to Redis
            self.redis = redis.Redis(
                host=self.redis_host, 
                port=self.redis_port,
                password=self.redis_password if self.redis_password else None,
                ssl=self.redis_ssl,
                socket_connect_timeout=2
            )
            
            # Check connection
            await self.redis.ping()
            return True
        except Exception as e:
            log.error("Failed to connect to Redis", error=str(e))
            return False
        finally:
            # Close connection if opened
            if self.redis:
                await self.redis.close()
                self.redis = None
    
    async def healthz(self, request):
        """Health check endpoint."""
        redis_ok = await self.connect_to_redis()
        
        if redis_ok:
            return web.json_response({
                "status": "healthy",
                "redis": "connected"
            })
        else:
            return web.json_response({
                "status": "unhealthy",
                "redis": "disconnected"
            }, status=503)
    
    async def start(self):
        """Start the health check server."""
        log.info(f"Starting health check server on port {self.port}")
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', self.port)
        await site.start()
        return runner

async def start_health_server():
    health = HealthCheck()
    runner = await health.start()
    return runner

if __name__ == "__main__":
    asyncio.run(start_health_server()) 