#!/bin/bash
# Run controller locally with Redis connection settings

export PYTHONPATH=$(pwd)
export API_PORT=8000

echo "API will be available at http://localhost:$API_PORT"

# Navigate to controller directory and run
cd app/controller
python main.py 