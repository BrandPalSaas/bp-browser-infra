#!/bin/bash
# Run controller locally with Redis connection settings

# Set environment variables for Redis connection
export PYTHONPATH=$(pwd)
export REDIS_HOST=localhost
export REDIS_PORT=6379
export REDIS_SSL=false
export REDIS_PASSWORD=
export REDIS_STREAM=browser_tasks
export REDIS_RESULTS_STREAM=browser_results
export REDIS_GROUP=browser_workers
export API_PORT=8000

echo "Starting controller with local Redis at $REDIS_HOST:$REDIS_PORT"
echo "API will be available at http://localhost:$API_PORT"

# Navigate to controller directory and run
cd app/controller
python main.py 