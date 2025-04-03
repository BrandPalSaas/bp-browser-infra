FROM registry.cn-hangzhou.aliyuncs.com/python:3.11-slim

WORKDIR /brandpal

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire app directory
COPY app /brandpal/app

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/brandpal

# Expose port
EXPOSE 8000

# Run the application
CMD ["python", "app/controller/main.py"] 