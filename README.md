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
   apiVersion: v1
   kind: ConfigMap
   metadata:
     name: browser-infra-config
   data:
     REDIS_HOST: "your-production-redis-host"
     REDIS_PORT: "6379"
     REDIS_SSL: "true"  # Set to "false" if not using SSL
     REDIS_DB: "0"      # Redis database index (0-15)
     REDIS_STREAM: "browser_tasks"
     REDIS_RESULTS_PREFIX: "task_result_"
     REDIS_GROUP: "browser_workers"
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

1. Create a `.env` file in the project root:
   ```bash
   # Redis configuration
   OPENAI_API_KEY=XXX
   REDIS_HOST=your-redis-host
   REDIS_PORT=6379
   REDIS_SSL=false
   REDIS_PASSWORD=your-redis-password
   REDIS_DB=0  # Redis database index (0-15)
   ```

2. Start a local Redis server (if not using external Redis):
   ```bash
   brew install redis
   brew services start[stop] redis
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
```

## API Usage Examples

Here are some example curl commands to interact with the browser infrastructure API:

### Create a Browser Task

```bash
# Create a simple navigation and screenshot task
curl -X POST http://localhost:8000/browser/task \
  -H "Content-Type: application/json" \
  -d '{
    "task_description": "go to google.com and search xiao.liang and returns the first result page title",
    "task_domain": "tiktokshop"
  }'
```

### Poll for Task Status

```bash
# Check status of a specific task
curl -X GET http://localhost:8000/browser/task/task_12345 \
  -H "Content-Type: application/json"
```