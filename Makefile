.PHONY: build-controller build-worker build-all load-images deploy clean

# Default Kubernetes namespace
NAMESPACE ?= default

# Docker image names and tags
CONTROLLER_IMAGE = controller:latest
WORKER_IMAGE = worker:latest

# Build the controller image
build-controller:
	docker build -t $(CONTROLLER_IMAGE) -f controller/Dockerfile controller

# Build the worker image
build-worker:
	docker build -t $(WORKER_IMAGE) -f worker/Dockerfile worker

# Build all images
build-all: build-controller build-worker

# Load images into Minikube
load-images: build-all
	@echo "Loading images into Minikube..."
	minikube image load $(CONTROLLER_IMAGE)
	minikube image load $(WORKER_IMAGE)

# Deploy to Kubernetes using kustomize
deploy:
	kubectl apply -k k8s/

# Deploy everything in one command
all: build-all load-images deploy
	@echo "Deployment complete!"
	@kubectl get pods -n $(NAMESPACE)

# Display service URLs
urls:
	@echo "Controller API URL:"
	@minikube service controller --url -n $(NAMESPACE)

# Clean up resources
clean:
	kubectl delete -k k8s/

# Tail logs from controller
logs-controller:
	kubectl logs -f deployment/controller -n $(NAMESPACE)

# Tail logs from worker
logs-worker:
	kubectl logs -f deployment/worker -n $(NAMESPACE)

# Print status
status:
	@echo "Kubernetes Resources:"
	@echo "---------------------"
	@echo "Pods:"
	@kubectl get pods -n $(NAMESPACE)
	@echo "\nServices:"
	@kubectl get services -n $(NAMESPACE)
	@echo "\nDeployments:"
	@kubectl get deployments -n $(NAMESPACE)

# Run controller locally
run-controller:
	cd controller && uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Run worker locally
run-worker:
	cd worker && python browser_worker.py 