# Kubernetes Configuration with Local Redis

This directory contains the Kubernetes configuration for the browser infrastructure that connects to a Redis server running on your local machine.

## Configuration

### Redis Connection

The system is configured to connect to a Redis server running on your local machine at:
- Host: localhost (from your machine) / host.docker.internal (from Kubernetes pods)
- Port: 6379
- No password
- No SSL

### Files

- `config.yaml`: ConfigMap with Redis connection settings
- `controller-deployment.yaml`: Controller deployment with hostAliases for Redis access
- `worker-deployment.yaml`: Worker deployment with hostAliases for Redis access
- `controller-service.yaml`: Service for the controller API
- `kustomization.yaml`: Kustomize configuration to apply all resources

## Deployment

To deploy the system:

```bash
# Add credentials to `config.yaml`

# Apply all resources
kubectl apply -k k8s/

# Check status
kubectl get pods
```

## Building Images

The system uses a shared requirements.txt file at the root level to manage dependencies for both components:

```bash
# Build controller image
docker build -t us-central1-docker.pkg.dev/browser-infra/browser-infra/controller:latest -f controller/Dockerfile .

# Build worker image
docker build -t us-central1-docker.pkg.dev/browser-infra/browser-infra/worker:latest -f worker/Dockerfile .
```

Note that the build command must be run from the root directory to include the shared requirements.txt file.

## Verification

To verify Redis connectivity from inside the pods:

```bash
# From controller pod
kubectl exec -it $(kubectl get pod -l app=controller -o jsonpath='{.items[0].metadata.name}') -- sh -c "cd /app && python -c \"
import redis
r = redis.Redis(host='host.docker.internal', port=6379)
print('Redis connection:', 'successful' if r.ping() else 'failed')
\""

# From worker pod
kubectl exec -it $(kubectl get pod -l app=worker -o jsonpath='{.items[0].metadata.name}') -- sh -c "cd /app && python -c \"
import redis
r = redis.Redis(host='host.docker.internal', port=6379)
print('Redis connection:', 'successful' if r.ping() else 'failed')
\""
``` 