# Makefile for Browser Infrastructure with External Redis

# Configuration
IMAGE_REGISTRY := us-central1-docker.pkg.dev/browser-infra/browser-infra
CONTROLLER_IMAGE := $(IMAGE_REGISTRY)/controller:latest
WORKER_IMAGE := $(IMAGE_REGISTRY)/worker:latest
NAMESPACE := default

# Build targets - run from project root to include common module and shared requirements.txt
.PHONY: build-controller
build-controller:
	docker build -t $(CONTROLLER_IMAGE) -f controller/Dockerfile .

.PHONY: build-worker
build-worker:
	docker build -t $(WORKER_IMAGE) -f worker/Dockerfile .

.PHONY: build-all
build-all: build-controller build-worker

# Push targets
.PHONY: push-controller
push-controller: build-controller
	docker push $(CONTROLLER_IMAGE)

.PHONY: push-worker
push-worker: build-worker
	docker push $(WORKER_IMAGE)

.PHONY: push-all
push-all: push-controller push-worker

# Deployment targets
.PHONY: deploy
deploy:
	kubectl apply -k k8s/

.PHONY: delete
delete:
	kubectl delete -k k8s/

.PHONY: redeploy
redeploy: delete deploy

# Redis secrets management
.PHONY: update-redis-secret
update-redis-secret:
	@read -p "Enter Redis password: " REDIS_PASSWORD; \
	echo "Creating Redis secret with provided password..."; \
	kubectl create secret generic redis-credentials \
		--from-literal=REDIS_PASSWORD=$$REDIS_PASSWORD \
		--dry-run=client -o yaml | kubectl apply -f -

# Status and logs
.PHONY: status
status:
	@echo "=== Deployments ==="
	kubectl get deployments -n $(NAMESPACE)
	@echo "\n=== Pods ==="
	kubectl get pods -n $(NAMESPACE)
	@echo "\n=== Services ==="
	kubectl get services -n $(NAMESPACE)

.PHONY: logs-controller
logs-controller:
	kubectl logs -l app=controller -n $(NAMESPACE) --tail=100 -f

.PHONY: logs-worker
logs-worker:
	kubectl logs -l app=worker -n $(NAMESPACE) --tail=100 -f

# Development targets
.PHONY: run-local-redis
run-local-redis:
	docker run -d --name redis-local -p 6379:6379 redis:latest

.PHONY: test-redis-connection
test-redis-connection:
	python3 scripts/redis_connection_test.py

.PHONY: port-forward-controller
port-forward-controller:
	kubectl port-forward svc/controller-service 8000:8000 -n $(NAMESPACE)

# Full deployment workflow
.PHONY: full-deploy
full-deploy: build-all push-all deploy status

# Help
.PHONY: help
help:
	@echo "Browser Infrastructure with External Redis Makefile"
	@echo ""
	@echo "Usage:"
	@echo "  make build-all           Build controller and worker Docker images"
	@echo "  make push-all            Push all Docker images to registry"
	@echo "  make deploy              Deploy the application to Kubernetes"
	@echo "  make update-redis-secret Update Redis password in Kubernetes secret"
	@echo "  make status              Show status of deployed resources"
	@echo "  make logs-controller     Show controller logs"
	@echo "  make logs-worker         Show worker logs"
	@echo "  make full-deploy         Build, push, and deploy all components"
	@echo "  make redeploy            Delete and redeploy the application"
	@echo "  make delete              Delete the application from Kubernetes"
	@echo "  make run-local-redis     Run Redis locally for development"
	@echo "  make test-redis-connection Test Redis connection with local settings"
	@echo "  make help                Show this help message" 