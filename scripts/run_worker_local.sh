#!/bin/bash
# Run worker locally with Redis connection settings

# Set environment variables for Redis connection
export PYTHONPATH=$(pwd)

# Navigate to worker directory and run
cd app/worker
python main.py 