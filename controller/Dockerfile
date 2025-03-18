FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy controller code
COPY *.py /app/

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Expose API port
EXPOSE 8000

# Command to run API
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"] 