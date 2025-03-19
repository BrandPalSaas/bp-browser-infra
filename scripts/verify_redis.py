#!/usr/bin/env python3
"""
Redis Connection Verification Script

This script verifies connectivity to Redis and sets up the required streams.

Usage:
    python scripts/verify_redis.py

The script will:
1. Check if Redis is running at localhost:6379
2. Ensure the browser_tasks and browser_results streams exist
3. Create the browser_workers consumer group if needed

Exit codes:
    0 - Success, Redis is ready
    1 - Failure, could not connect to Redis or other error
"""

import redis
import sys
import time

def verify_redis():
    """Verify connection to Redis and set up streams."""
    print("Verifying Redis connection at localhost:6379...")
    
    try:
        # Connect to Redis
        r = redis.Redis(
            host='localhost',
            port=6379,
            decode_responses=True
        )
        
        # Test connection
        if r.ping():
            print("✅ Connected to Redis successfully!")
            
            # Define stream names
            task_stream = "browser_tasks"
            results_stream = "browser_results"
            group_name = "browser_workers"
            
            # Create streams if they don't exist
            if not r.exists(task_stream):
                r.xadd(task_stream, {"test": "test"}, maxlen=10)
                print(f"✅ Created task stream: {task_stream}")
            else:
                print(f"✅ Task stream exists: {task_stream}")
            
            if not r.exists(results_stream):
                r.xadd(results_stream, {"test": "test"}, maxlen=10)
                print(f"✅ Created results stream: {results_stream}")
            else:
                print(f"✅ Results stream exists: {results_stream}")
            
            # Create consumer group
            try:
                r.xgroup_create(task_stream, group_name, id="0", mkstream=True)
                print(f"✅ Created consumer group: {group_name}")
            except redis.exceptions.ResponseError as e:
                if "BUSYGROUP" in str(e):
                    print(f"✅ Consumer group already exists: {group_name}")
                else:
                    raise
            
            print("\nRedis is ready for use with the browser infrastructure!")
            return True
        else:
            print("❌ Redis ping failed")
            return False
    except redis.exceptions.ConnectionError as e:
        print(f"❌ Could not connect to Redis: {e}")
        print("Make sure Redis is running on localhost:6379")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False

if __name__ == "__main__":
    success = verify_redis()
    sys.exit(0 if success else 1) 