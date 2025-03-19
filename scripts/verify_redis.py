#!/usr/bin/env python3
"""
Verify Redis connection and setup for the browser infrastructure.

This script:
1. Checks connectivity to Redis
2. Ensures the task stream exists
3. Creates the consumer group if needed

Usage:
    python verify_redis.py

Exit codes:
    0 - Everything is properly configured
    1 - Failed to connect to Redis
    2 - Failed to set up task stream or consumer group
"""

import os
import sys
import asyncio
import redis.asyncio as redis
import ssl

async def verify_redis():
    # Redis connection parameters
    redis_host = os.getenv("REDIS_HOST", "localhost")
    redis_port = int(os.getenv("REDIS_PORT", 6379))
    redis_password = os.getenv("REDIS_PASSWORD", "")
    redis_ssl = os.getenv("REDIS_SSL", "false").lower() == "true"
    task_stream = os.getenv("REDIS_STREAM", "browser_tasks")
    group_name = os.getenv("REDIS_GROUP", "browser_workers")
    
    print(f"Connecting to Redis at {redis_host}:{redis_port}")
    
    try:
        # Set up SSL if needed
        ssl_connection = None
        if redis_ssl:
            ssl_connection = ssl.create_default_context()
        
        # Connect to Redis
        r = redis.Redis(
            host=redis_host,
            port=redis_port,
            password=redis_password if redis_password else None,
            ssl=redis_ssl,
            ssl_cert_reqs=None if redis_ssl else None,
            ssl_context=ssl_connection
        )
        
        # Check connection
        await r.ping()
        print("✅ Successfully connected to Redis")
        
        # Create the task stream if it doesn't exist
        stream_info = await r.exists(task_stream)
        if not stream_info:
            await r.xadd(task_stream, {"init": "1"})
            print(f"✅ Created task stream '{task_stream}'")
        else:
            print(f"✅ Task stream '{task_stream}' exists")
        
        # Create consumer group if it doesn't exist
        try:
            await r.xgroup_create(
                name=task_stream,
                groupname=group_name,
                mkstream=True,
                id='0'  # Start from beginning
            )
            print(f"✅ Created consumer group '{group_name}' for stream '{task_stream}'")
        except redis.ResponseError as e:
            if "BUSYGROUP" in str(e):
                # Group already exists
                print(f"✅ Consumer group '{group_name}' already exists")
            else:
                print(f"❌ Error creating consumer group: {e}")
                await r.close()
                return 2
        
        # Clean up
        await r.close()
        print("✅ Redis verification completed successfully")
        return 0
        
    except redis.ConnectionError as e:
        print(f"❌ Failed to connect to Redis: {e}")
        return 1
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return 2

if __name__ == "__main__":
    exit_code = asyncio.run(verify_redis())
    sys.exit(exit_code) 