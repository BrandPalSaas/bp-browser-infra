#!/bin/bash
# Run worker locally with Redis connection settings

# Set environment variables for Redis connection
export PYTHONPATH=$(pwd)
export REDIS_HOST=localhost
export REDIS_PORT=6379
export REDIS_SSL=false
export REDIS_PASSWORD=
export REDIS_STREAM=browser_tasks
export REDIS_RESULTS_STREAM=browser_results
export REDIS_GROUP=browser_workers
export HEALTH_PORT=3000

echo "Starting worker with local Redis at $REDIS_HOST:$REDIS_PORT"
echo "Health check will be available at http://localhost:$HEALTH_PORT/healthz"

# Navigate to worker directory and run
cd app/worker
python main.py 