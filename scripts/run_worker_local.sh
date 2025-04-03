#!/bin/bash
# Run the worker locally

set -e

# Set environment variables
export PYTHONPATH=$PYTHONPATH:$PWD
export LIVE_VIEW_PORT=3000

source .venv/Scripts/activate

# Start Playwright with Xvfb to run in headless mode
echo "Starting worker with Xvfb..."
Xvfb :99 -screen 0 1280x1024x24 -ac +extension GLX +render -noreset & 
export DISPLAY=:99

# Create necessary directories
mkdir -p /tmp/task_results

cd app/worker
python main.py 