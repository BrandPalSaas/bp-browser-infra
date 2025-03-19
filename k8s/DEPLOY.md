# Kubernetes Deployment Guide

This guide walks through deploying the browser infrastructure to a Kubernetes cluster.

## Prerequisites

- Docker installed
- Access to a container registry (e.g., Docker Hub, GCR, ECR)
- kubectl configured to access your K8s cluster
- A running Redis instance accessible from your K8s cluster

## Step 1: Tag and Push the Docker Images

First, tag your locally built images with your registry URL:

```bash
# Replace with your registry URL
REGISTRY_URL=your-registry.com/your-project

# Tag images
docker tag browser-controller:latest ${REGISTRY_URL}/browser-controller:latest
docker tag browser-worker:latest ${REGISTRY_URL}/browser-worker:latest

# Push images
docker push ${REGISTRY_URL}/browser-controller:latest
docker push ${REGISTRY_URL}/browser-worker:latest
```

## Step 2: Update Kubernetes Manifests

Edit the deployment files to use your registry URLs:

1. Edit `k8s/controller-deployment.yaml`:
   ```yaml
   image: ${REGISTRY_URL}/browser-controller:latest
   ```

2. Edit `k8s/worker-deployment.yaml`:
   ```yaml
   image: ${REGISTRY_URL}/browser-worker:latest
   ```

3. Update Redis configuration in `k8s/config.yaml`:
   ```yaml
   REDIS_HOST: "your-redis-host"
   REDIS_PORT: "6379"
   REDIS_PASSWORD: "your-redis-password" # If needed
   REDIS_SSL: "true" # If using SSL
   ```

## Step 3: Deploy to Kubernetes

Apply the configuration with `kubectl`:

```bash
kubectl apply -k k8s/
```

Or apply individual components:

```bash
kubectl apply -f k8s/config.yaml
kubectl apply -f k8s/controller-deployment.yaml
kubectl apply -f k8s/controller-service.yaml
kubectl apply -f k8s/worker-deployment.yaml
kubectl apply -f k8s/worker-service.yaml
```

## Step 4: Verify the Deployment

Check that pods are running:

```bash
kubectl get pods
```

Check services:

```bash
kubectl get services
```

## Step 5: Access the API

Get the external IP/URL for the controller service:

```bash
kubectl get service controller-service
```

Use the IP/URL to access the API at port 8000.

## Troubleshooting

To check pod logs:

```bash
kubectl logs <pod-name>
```

To describe a pod for detailed status:

```bash
kubectl describe pod <pod-name>
```

To restart a deployment:

```bash
kubectl rollout restart deployment controller-deployment
kubectl rollout restart deployment worker-deployment
``` 