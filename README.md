# Browser Infrastructure / 浏览器基础设施

A scalable browser automation infrastructure system with WebSocket-based communication.

一个可扩展的浏览器自动化基础设施系统，使用WebSocket进行通信。

## Project Structure / 项目结构

- **app**: Core application code / 核心应用代码
  - **app/controller/**: API service that receives browser automation and live view requests / API服务，接收浏览器自动化请求和屏幕共享请求
  - **app/worker/**: Service that processes browser automation tasks / 处理浏览器自动化任务的服务
  - **app/common/**: Shared models, utilities, and constants / 共享模型、工具和常量

- **k8s**: Kubernetes configuration files / Kubernetes配置文件
  - Configuration maps, deployments, services / 配置映射、部署、服务等

- **scripts**: Utility scripts for development and deployment / 用于开发和部署的实用脚本
  - Setup scripts, deployment helpers, etc. / 设置脚本、部署助手等

## Architecture / 架构

### New Architecture / 新架构

The new system architecture uses a direct WebSocket connection between controller and workers:

新系统架构使用控制器和工作节点之间的直接WebSocket连接：

1. **Controller** / **控制器**:
   - Central hub for UI interactions / UI交互的中央枢纽
   - Manages worker connections / 管理工作节点连接
   - Proxies commands between viewers and workers / 在查看者和工作节点之间代理命令
   - Provides live view management / 提供实时视图管理

2. **Workers** / **工作节点**:
   - Run browser automation tasks / 运行浏览器自动化任务
   - Stream screenshots to controller / 向控制器流式传输截图
   - Execute commands from controller / 执行来自控制器的命令

## Testing Without Docker or Kubernetes / 不使用Docker或Kubernetes进行测试

### Prerequisites / 前提条件

- Python 3.11+ / Python 3.11以上版本
- Browser-use and Playwright dependencies / 浏览器使用和Playwright依赖项

### Setup Local Environment / 设置本地环境

1. **Install Python dependencies / 安装Python依赖项**:
   ```bash
   pip install -r requirements.txt
   playwright install chromium
   ```

2. **Create a `.env` file in the project root / 在项目根目录创建`.env`文件**:
   ```bash
   OPENAI_API_KEY=XXX # CHANGE THIS
   REDIS_HOST="r-rj9rt0snyetm52iqjrpd.redis.rds.aliyuncs.com"
   REDIS_PASSWORD="" # CHANGE THIS
   REDIS_PORT="6379"
   REDIS_SSL="false"
   REDIS_DB="200"
   ANONYMIZED_TELEMETRY=False
   ```

### Running the Services / 运行服务

1. **Run the controller / 运行控制器**:
   ```bash
   ./scripts/run_controller_local.sh
   ```

2. **Run the worker / 运行工作节点** (in a separate terminal / 在另一个终端):
   ```bash
   ./scripts/run_worker_local.sh
   ```

3. **Access the controller UI / 访问控制器UI**:
   - Open `http://localhost:8000/live` in your browser / 在浏览器中打开`http://localhost:8000/live`
   - View available workers / 查看可用工作节点
   - Click on a worker to access its live view / 点击工作节点以访问其实时视图

### Testing the API / 测试API

The API will be available at `http://localhost:8000`. Examples / API将在`http://localhost:8000`提供。示例：

```bash
# Create a browser task / 创建浏览器任务
curl -X POST http://localhost:8000/browser/task \
  -H "Content-Type: application/json" \
  -d '{
    "task_description": "go to google.com and search elon.musk and returns the first result page title",
    "task_domain": "tiktokshop"
  }'

# Check task status (replace with your task_id) / 检查任务状态（替换为您的task_id）
curl -X GET http://localhost:8000/browser/task/task_12345 \
  -H "Content-Type: application/json"
```

## Deployment with Kubernetes / 使用Kubernetes部署

请注意：**生产环境的部署需要创建单独的 k8s 集群，minikube 只是用来单机测试用、可以模拟 k8s 的集群。**

### Deployment with Minikube (Test Only) / 使用Minikube部署 (仅供测试)

Minikube is a lightweight Kubernetes implementation. / Minikube是一个轻量级Kubernetes实现

1. **Start Minikube / 启动Minikube**:
   ```bash
   brew install minikube
   minikube start
   ```

2. **Configure Docker to use Minikube's daemon / 配置Docker使用Minikube的守护进程**:
   ```bash
   eval $(minikube docker-env)
   ```

3. **Build Docker images in Minikube's environment / 在Minikube环境中构建Docker镜像**:
   ```bash
   docker build -t browser-controller:latest -f app/controller/Dockerfile .
   docker build -t browser-worker:latest -f app/worker/Dockerfile .
   ```

4. **Configure value / 配置值**:
   
   Edit `k8s/config.yaml` with your settings / 使用您的设置编辑`k8s/config.yaml`：
   ```yaml
   apiVersion: v1
   kind: ConfigMap
   metadata:
     name: browser-infra-config
   data:
     OPENAI_API_KEY: "XXX"
     ...
   ```

5. **Deploy to Kubernetes / 部署到Kubernetes**:
   ```bash
   kubectl apply -k k8s/
   ```

6. **Verify deployment / 验证部署**:
   ```bash
   kubectl get pods
   kubectl get services
   ```

7. **Access the API / 访问API**:
   ```bash
   kubectl port-forward service/controller 8000:8000
   ```

   The API will be available at `http://localhost:8000` / API将在`http://localhost:8000`提供

### Cleaning Up / 清理

```bash
# Delete everything / 删除所有内容
kubectl delete all --all

# Stop Minikube / 停止Minikube
minikube stop

# Delete Minikube / 删除Minikube
minikube delete
```