# Browser Infrastructure with External Redis

This project implements a browser infrastructure system utilizing Kubernetes and an external Redis server for task queue management.

## Architecture

- **Controller**: API service that receives browser automation requests and queues them in Redis
- **Worker**: Service that processes browser automation tasks from Redis queues
- **Redis**: External Redis server used for task queuing and results

### Prerequisites

- Kubernetes cluster
- External Redis server (managed service or standalone installation)
- Docker and kubectl installed

### Configuration Steps

1. **Update Redis Configuration**

   Edit the `k8s/config.yaml` file to set your Redis connection details:
   
   ```yaml
   REDIS_HOST: "your-external-redis-host"
   REDIS_PORT: "6379"
   REDIS_SSL: "true"  # Set to "false" if not using SSL
   REDIS_STREAM: "browser_tasks"
   REDIS_RESULTS_STREAM: "browser_results"
   REDIS_GROUP: "browser_workers"
   ```

2. **Set Redis Password**

   Update the Redis password in the `k8s/redis-secret.yaml` file:
   
   ```bash
   # Generate base64 encoded password
   echo -n "your-redis-password" | base64
   
   # Update the secret file with the encoded password
   ```

3. **Build Docker Images**

   ```bash
   # Build controller image
   docker build -t us-central1-docker.pkg.dev/browser-infra/browser-infra/controller:latest -f app/controller/Dockerfile .
   
   # Build worker image
   docker build -t us-central1-docker.pkg.dev/browser-infra/browser-infra/worker:latest -f app/worker/Dockerfile .
   
   # Push to your container registry
   docker push us-central1-docker.pkg.dev/browser-infra/browser-infra/controller:latest
   docker push us-central1-docker.pkg.dev/browser-infra/browser-infra/worker:latest
   ```

4. **Deploy to Kubernetes**

   ```bash
   kubectl apply -k k8s/
   ```

5. **Verify Deployment**

   ```bash
   # Check the pods are running
   kubectl get pods
   
   # Check controller service
   kubectl get svc
   ```

## Development

To run the system locally for development:

1. Start a local Redis server:
   ```bash
   docker run -d -p 6379:6379 redis:latest
   ```

2. Set environment variables:
   ```bash
   export REDIS_HOST=localhost
   export REDIS_PORT=6379
   export REDIS_SSL=false
   export REDIS_PASSWORD=
   ```

3. Run the controller:
   ```bash
   cd controller
   python main.py
   ```

4. Run the worker:
   ```bash
   cd worker
   python main.py
   ```

## Local Testing with Minikube

For testing the complete system locally with Kubernetes before deploying to a production cluster, you can use Minikube:

### Prerequisites

- [Minikube](https://minikube.sigs.k8s.io/docs/start/) installed
- [kubectl](https://kubernetes.io/docs/tasks/tools/install-kubectl/) installed
- [Docker](https://docs.docker.com/get-docker/) installed
- Redis running locally (as described below)

### Setting Up Redis for Local Testing

For the browser infrastructure to work properly with Minikube, you need Redis running on your host machine:

```bash
# macOS: Install and start Redis using Homebrew
brew install redis
brew services start redis

# Verify Redis is running
redis-cli ping  # Should return "PONG"
```

Make sure Redis is configured to accept external connections:

```bash
# Edit Redis config to allow external connections
# For Homebrew installations, edit /usr/local/etc/redis.conf
# Change "bind 127.0.0.1" to "bind 0.0.0.0"

# Restart Redis to apply changes
brew services restart redis
```

The `deploy_to_minikube.sh` script will automatically configure Minikube to connect to your host Redis instance.

### Setup and Deployment

1. **Start Minikube**

   ```bash
   minikube start
   ```

2. **Build Docker Images in Minikube**

   Point your Docker CLI to Minikube's Docker daemon and build the images:

   ```bash
   # Configure Docker to use Minikube's Docker daemon
   eval $(minikube docker-env)
   
   # Build images directly in Minikube's environment
   docker build -t browser-controller:latest -f app/controller/Dockerfile .
   docker build -t browser-worker:latest -f app/worker/Dockerfile .
   ```

3. **Run the Deployment Script**

   We provide a script that handles the deployment to Minikube:

   ```bash
   # Ensure Redis is running locally first
   ./scripts/deploy_to_minikube.sh
   ```

   This script will:
   - Configure Docker to use Minikube's daemon
   - Build the Docker images
   - Configure the system to use your local Redis
   - Deploy the controller and worker components
   - Set up port forwarding for accessing the API

4. **Accessing the API**

   After successful deployment, the API will be available at:
   
   ```
   http://localhost:8000
   ```

5. **Cleanup**

   To stop and clean up your Minikube deployment:

   ```bash
   # Stop port forwarding (if running)
   pkill -f "kubectl port-forward"
   
   # Delete deployments
   kubectl delete -f k8s/controller-deployment.yaml
   kubectl delete -f k8s/worker-deployment.yaml
   
   # Stop Minikube (optional)
   minikube stop
   ```

### Troubleshooting Minikube Deployment

- **Redis connection fails**: 
  - Check Redis is running: `brew services list | grep redis`
  - Ensure Redis is listening on all interfaces and not just localhost
  - Test connectivity from Minikube: `minikube ssh "nc -zv $(minikube ssh 'route -n | grep ^0.0.0.0 | awk "{print \$2}"') 6379"`

- **Images not found**: Make sure you built the images within Minikube's Docker environment
- **Pods crash-looping**: Check logs with `kubectl logs <pod-name>`

## API Usage Examples

Here are some example curl commands to interact with the browser infrastructure API:

### Create a Browser Task

```bash
# Create a simple navigation and screenshot task
curl -X POST http://localhost:8000/browser/task \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com",
    "actions": [
      {"type": "wait", "duration": 2000},
      {"type": "screenshot", "fullPage": true}
    ]
  }'

# Response will include a task_id
# Example response: {"task_id": "task_12345", "status": "queued"}
```

### Poll for Task Status

```bash
# Check status of a specific task
curl -X GET http://localhost:8000/browser/task/task_12345 \
  -H "Content-Type: application/json"

# Example response: {"task_id": "task_12345", "status": "completed", "result": {"screenshot": "data:image/png;base64,..."}}
```

### Complex Task Example

```bash
# Create a more complex task with multiple actions
curl -X POST http://localhost:8000/browser/task \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com/login",
    "actions": [
      {"type": "wait", "selector": "#username"},
      {"type": "type", "selector": "#username", "text": "testuser"},
      {"type": "type", "selector": "#password", "text": "password123"},
      {"type": "click", "selector": "#login-button"},
      {"type": "wait", "duration": 3000},
      {"type": "screenshot", "fullPage": true}
    ]
  }'
```

### List All Tasks

```bash
# Get a list of all tasks
curl -X GET http://localhost:8000/browser/tasks \
  -H "Content-Type: application/json"

# Example response: {"tasks": [{"task_id": "task_12345", "status": "completed"}, {"task_id": "task_67890", "status": "running"}]}
```