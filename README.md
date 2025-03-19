# Browser Infrastructure with External Redis

This project implements a browser infrastructure system utilizing Kubernetes and an external Redis server for task queue management.

## Architecture

- **Controller**: API service that receives browser automation requests and queues them in Redis
- **Worker**: Service that processes browser automation tasks from Redis queues
- **Redis**: External Redis server used for task queuing and results

## Dependency Management

The project uses a split dependency management approach:

- **Core dependencies** are managed in the shared `requirements.txt` file at the project root
- **Worker-specific dependencies** (like Playwright and browser-use) are installed directly in the worker Dockerfile
- **Controller-specific dependencies** are listed in the shared requirements.txt

This approach ensures that the controller doesn't need to install the heavy browser automation dependencies.

### Development Setup

For development, you can use the setup script:

```bash
# Setup with interactive prompts
./scripts/setup_dev.sh

# Or specify components explicitly
./scripts/setup_dev.sh --worker     # For worker development
./scripts/setup_dev.sh --controller # For controller development
./scripts/setup_dev.sh --all        # For both
```

## Setup with External Redis

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
   docker build -t us-central1-docker.pkg.dev/browser-infra/browser-infra/controller:latest -f controller/Dockerfile .
   
   # Build worker image
   docker build -t us-central1-docker.pkg.dev/browser-infra/browser-infra/worker:latest -f worker/Dockerfile .
   
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

## Usage

The controller exposes an API endpoint for submitting browser automation tasks:

```bash
curl -X POST http://<controller-service-ip>/browser/use -H "Content-Type: application/json" -d '{
  "url": "https://example.com",
  "actions": [
    {"type": "wait", "duration": 2000},
    {"type": "screenshot"}
  ]
}'
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

## Scaling

To scale the number of workers:

```bash
kubectl scale deployment worker-deployment --replicas=5
```

## Troubleshooting

- **Redis Connection Issues**: Ensure your network policies allow traffic to the Redis server
- **Worker Errors**: Check the worker logs for details about task execution issues
- **Controller API Unavailable**: Verify the service and endpoints are correctly configured

## Project Structure

- `controller/`: API service for queueing browser tasks
- `worker/`: Service for processing browser tasks
- `common/`: Shared models and utilities used by both components
- `k8s/`: Kubernetes configuration files
  - Deployments, services, and configuration

## API Endpoints

- `GET /` - API info
- `POST /sessions` - Start a new browser session
- `GET /sessions` - List all sessions
- `GET /sessions/{session_id}` - Get session details
- `DELETE /sessions/{session_id}` - Stop a session
- `POST /profiles` - Create a browser profile
- `GET /profiles` - List all profiles
- `GET /profiles/{profile_id}` - Get profile details
- `DELETE /profiles/{profile_id}` - Delete a profile

## Features

- Scalable browser infrastructure
- Kubernetes deployment support
- Session and profile management 