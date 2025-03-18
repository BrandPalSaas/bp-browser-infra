# Browser Infrastructure

A modular system for managing browser instances with a controller API and worker nodes.

## Project Structure

- `controller/` - API control plane
  - `main.py` - FastAPI application
  - `models.py` - Data models
  - `container.py` - Container management
  - `Dockerfile` - Controller container image
  - `requirements.txt` - Controller dependencies

- `worker/` - Browser worker
  - `browser_worker.py` - Worker implementation
  - `Dockerfile` - Worker container image
  - `requirements.txt` - Worker dependencies

- `k8s/` - Kubernetes manifests
  - Deployments, services, and configuration

## Development

### Local Development

1. Setup virtual environments:
```bash
# Controller
cd controller
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

```bash
# Worker
cd worker
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

2. Run the controller API:
```bash
cd controller
uvicorn main:app --reload
```

3. Run the worker:
```bash
cd worker
python browser_worker.py
```

### Docker Setup

Build the images:
```bash
# Controller
docker build -t controller:latest -f controller/Dockerfile controller

# Worker
docker build -t worker:latest -f worker/Dockerfile worker
```

Run the containers:
```bash
# Controller
docker run -p 8000:8000 controller:latest

# Worker
docker run -p 3000:3000 worker:latest
```

### Kubernetes Deployment

#### Prerequisites
- Minikube, kind, or another local Kubernetes cluster
- kubectl configured to access your cluster

#### Using Makefile

The Makefile provides simple commands for building, deploying, and managing the application:

```bash
# Start Minikube if not running
minikube start

# Build all images, load into Minikube, and deploy
make all

# Check deployment status
make status

# Get controller URL
make urls

# View logs
make logs-controller
make logs-worker

# Clean up resources
make clean

# Run services locally
make run-controller
make run-worker
```

#### Manual Deployment

1. Build and load images:
```bash
docker build -t controller:latest -f controller/Dockerfile controller
docker build -t worker:latest -f worker/Dockerfile worker

minikube image load controller:latest
minikube image load worker:latest
```

2. Deploy to Kubernetes:
```bash
kubectl apply -k k8s/
```

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