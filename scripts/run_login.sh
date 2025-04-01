#!/bin/bash
# Run the login script locally

set -e

# Check if username and password are provided
if [ $# -ne 2 ]; then
    echo "Usage: $0 <username> <password>"
    echo "Example: $0 your.email@example.com your_password"
    exit 1
fi

# Set environment variables
export PYTHONPATH=$PYTHONPATH:$PWD

source venv/bin/activate

cd app/login
python main.py "$1" "$2" 
