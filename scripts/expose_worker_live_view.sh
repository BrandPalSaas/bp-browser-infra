#!/bin/bash
# Expose worker live view for interactive browser sessions

set -e

# Get the worker pod name
WORKER_POD=$(kubectl get pod -l app=browser-worker -o jsonpath="{.items[0].metadata.name}")

if [ -z "$WORKER_POD" ]; then
    echo "No worker pod found! Make sure the deployment is running."
    exit 1
fi

# Get the worker name from the pod
WORKER_NAME=$(kubectl exec -it $WORKER_POD -- bash -c "echo \$HOSTNAME")

if [ -z "$WORKER_NAME" ]; then
    # Fallback to pod name if hostname isn't available
    WORKER_NAME=$WORKER_POD
fi

echo "Found worker: $WORKER_NAME"
echo "Starting port-forward to access the live view..."
echo "Live view will be available at: http://localhost:3000/live/$WORKER_NAME"
echo ""
echo "Press Ctrl+C to stop"

# Forward the port
kubectl port-forward service/worker-service 3000:3000

# This part will run after the user presses Ctrl+C
echo "Port-forwarding stopped." 