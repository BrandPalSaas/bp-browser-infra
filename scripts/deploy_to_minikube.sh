#!/bin/bash
# Script to deploy the browser infrastructure to Minikube

set -e  # Exit on error

echo "Deploying browser infrastructure to Minikube..."

# Check if Minikube is running
if ! minikube status | grep -q "host: Running"; then
  echo "Minikube is not running. Starting Minikube..."
  minikube start
fi

# Point Docker CLI to Minikube's Docker daemon
echo "Configuring Docker CLI to use Minikube's Docker daemon..."
eval $(minikube docker-env)

# Build Docker images within Minikube
echo "Building Docker images in Minikube..."
docker build -t browser-controller:latest -f app/controller/Dockerfile .
docker build -t browser-worker:latest -f app/worker/Dockerfile .

# Determine the correct gateway IP for host access
# On macOS, this is typically the host machine's IP from the VM's perspective
if [[ "$(uname)" == "Darwin" ]]; then
  # For macOS, get the gateway IP that Minikube can use to reach the host
  GATEWAY_IP=$(minikube ssh "route -n | grep '^0.0.0.0' | awk '{print \$2}'")
  echo "Detected macOS. Gateway IP to reach host machine: $GATEWAY_IP"
else
  # For Linux, this is typically the default gateway within the Minikube VM
  GATEWAY_IP=$(minikube ssh "ip route | grep default | awk '{print \$3}'")
  echo "Detected Linux. Gateway IP to reach host machine: $GATEWAY_IP"
fi

echo ""
echo "Updating ConfigMap to use the correct Redis host IP..."
# Update the ConfigMap with the correct gateway IP for Redis
sed -i.bak "s/REDIS_HOST: \"host.minikube.internal\"/REDIS_HOST: \"$GATEWAY_IP\"/" k8s/config.yaml
echo "ConfigMap updated to use Redis at $GATEWAY_IP"

echo ""
echo "!! IMPORTANT !!"
echo "Ensure Redis is running on your host machine at $GATEWAY_IP:6379"
echo "And that your firewall allows connections from Minikube"
echo "!!"
echo ""

# Deploy to Minikube
echo "Applying Kubernetes configurations..."
kubectl apply -f k8s/config.yaml
kubectl apply -f k8s/controller-deployment.yaml
kubectl apply -f k8s/controller-service.yaml
kubectl apply -f k8s/worker-deployment.yaml

# Restore the ConfigMap file
mv k8s/config.yaml.bak k8s/config.yaml
echo "Restored original config.yaml file"

# Display status
echo ""
echo "Waiting for pods to start..."
sleep 5
kubectl get pods

echo ""
echo "Exposing controller service..."
kubectl port-forward service/controller-service 8000:8000 &
PORT_FORWARD_PID=$!

echo ""
echo "Deployment completed!"
echo "API is available at: http://localhost:8000"
echo ""
echo "Press Ctrl+C to stop port forwarding when done."

# Cleanup on exit
trap "kill $PORT_FORWARD_PID 2>/dev/null" EXIT
wait $PORT_FORWARD_PID 