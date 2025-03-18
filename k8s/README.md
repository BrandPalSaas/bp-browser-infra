# Kubernetes Deployment for Browser Infrastructure

This directory contains Kubernetes manifests for deploying the browser infrastructure.

## Prerequisites

- Kubernetes cluster with kubectl access
- Docker to build the API image

## Building the API Image

```bash
# From the root directory
docker build -t browser-infra-service:latest .
```

## Deployment

To deploy all resources to your Kubernetes cluster:

```bash
kubectl apply -k k8s/
```

Or you can apply each file individually:

```bash
kubectl apply -f k8s/rbac.yaml
kubectl apply -f k8s/config.yaml
kubectl apply -f k8s/api-deployment.yaml
kubectl apply -f k8s/api-service.yaml
kubectl apply -f k8s/browser-deployment.yaml
kubectl apply -f k8s/browser-service.yaml
```

## Accessing the API

The API service is deployed as a ClusterIP service. To access it, you can:

1. Use port-forwarding:
   ```bash
   kubectl port-forward svc/browser-infra-service 8000:8000
   ```

2. Or set up an Ingress resource (not included in these manifests).

## Clean Up

To remove all resources:

```bash
kubectl delete -k k8s/
``` 