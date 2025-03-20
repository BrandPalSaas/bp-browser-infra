# Browser Infrastructure

A scalable browser automation infrastructure system with Redis-based task queuing.

## Project Structure

- **app**: Core application code
  - **app/controller/**: API service that receives browser automation requests and queues them in Redis
  - **app/worker/**: Service that processes browser automation tasks from Redis queues  
  - **app/common/**: Shared models, utilities, and constants used by both services

- **k8s**: Kubernetes configuration files
  - Configuration maps, deployments, services, and RBAC settings

- **scripts**: Utility scripts for development and deployment
  - Setup scripts, deployment helpers, etc.

## Testing Without Docker or Kubernetes

### Prerequisites

- Python 3.11+
- Redis server (local or remote)
- Browser-use and Playwright dependencies

### Setup Local Environment

1. **Install Python dependencies**:
   ```bash
   pip install -r requirements.txt
   pip install playwright==1.51.0 browser-use==0.1.40
   playwright install chromium
   ```

2. **Configure Redis**:

   Install and start Redis locally (macOS):
   ```bash
   brew install redis
   brew services start redis
   ```

3. **Create a `.env` file in the project root**:
   ```bash
   OPENAI_API_KEY=XXX
   REDIS_HOST=localhost
   REDIS_PORT=6379
   REDIS_SSL=false
   REDIS_PASSWORD=
   REDIS_DB=0
   ```

### Running the Services

1. **Run the controller**:
   ```bash
   cd app/controller
   python main.py
   ```

2. **Run the worker** (in a separate terminal):
   ```bash
   cd app/worker
   python main.py
   ```

### Testing the API

The API will be available at `http://localhost:8000`. Examples:

```bash
# Create a browser task
curl -X POST http://localhost:8000/browser/task \
  -H "Content-Type: application/json" \
  -d '{
    "task_description": "go to google.com and search xiao.liang and returns the first result page title",
    "task_domain": "tiktokshop"
  }'

# Check task status (replace with your task_id)
curl -X GET http://localhost:8000/browser/task/task_12345 \
  -H "Content-Type: application/json"
```

## Deployment with Docker/Kubernetes

### Deployment with Minikube

Minikube is a lightweight Kubernetes implementation that creates a VM on your local machine and deploys a simple single-node cluster. 

1. **Start Minikube**:
   ```bash
   brew install minikube
   minikube start
   ```

2. **Configure Docker to use Minikube's daemon**:
   ```bash
   eval $(minikube docker-env)
   ```

3. **Build Docker images in Minikube's environment**:
   ```bash
   docker build -t browser-controller:latest -f app/controller/Dockerfile .
   docker build -t browser-worker:latest -f app/worker/Dockerfile .
   ```

4. **Configure value**:
   
   Edit `k8s/config.yaml` with your Redis settings:
   ```yaml
   apiVersion: v1
   kind: ConfigMap
   metadata:
     name: browser-infra-config
   data:
     OPENAI_API_KEY: "keys"
     REDIS_HOST: "your-redis-host"
     REDIS_PORT: "6379"
     REDIS_SSL: "false"
     REDIS_DB: "0"
   ```

5. **Deploy to Kubernetes**:
   ```bash
   kubectl apply -k k8s/
   ```

6. **Verify deployment**:
   ```bash
   kubectl get pods
   kubectl get services
   ```

7. **Access the API**:
   ```bash
   kubectl port-forward service/controller 8000:8000
   ```

   The API will be available at `http://localhost:8000`

### Cleaning Up

```bash
# Delete deployments
kubectl delete deployment worker-deployment controller-deployment

# Delete everything
kubectl delete all --all

# Stop Minikube
minikube stop

# Delete Minikube
minikube delete
```