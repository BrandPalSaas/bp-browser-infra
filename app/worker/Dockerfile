# Use Python 3.11 as base
FROM registry.cn-hangzhou.aliyuncs.com/python:3.11-slim

WORKDIR /brandpal

# Install system dependencies for Playwright
RUN apt-get update && apt-get install -y \
    wget \
    libglib2.0-0 \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxcb1 \
    libxkbcommon0 \
    libx11-6 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    xvfb \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire app directory
COPY app /brandpal/app

# Install Playwright browsers
RUN playwright install chromium

# Create results directories
RUN mkdir -p /tmp/task_results && chmod 777 /tmp/task_results

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/brandpal
ENV DISPLAY=:99
ENV LIVE_VIEW_PORT=3000
ENV ANONYMIZED_TELEMETRY=False

# Expose live view port
EXPOSE 3000

# Run Xvfb and the worker process
CMD Xvfb :99 -screen 0 1280x1024x24 -ac +extension GLX +render -noreset & python app/worker/main.py 