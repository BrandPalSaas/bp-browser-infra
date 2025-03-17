# Use Python 3.11 as base
FROM python:3.11-slim

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

# Install Python packages
RUN pip install --no-cache-dir \
    browser-use \
    playwright \
    langchain-openai \
    python-dotenv

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PLAYWRIGHT_BROWSERS_PATH=/browsers

# Create a non-root user
RUN useradd -m -u 1000 brandpal

# Create browsers directory with correct permissions
RUN mkdir -p /browsers && chown -R brandpal:brandpal /browsers

# Switch to brandpal user
USER brandpal
WORKDIR /home/brandpal

# Install browser binaries as brandpal user
RUN playwright install chromium

# Copy .env file
COPY --chown=brandpal:brandpal .env /home/brandpal/.env

# Create a wrapper script to run commands with xvfb
USER root
RUN echo '#!/bin/bash\nxvfb-run -a --server-args="-screen 0 1280x800x24" "$@"' > /usr/local/bin/xvfb-run-safe && \
    chmod +x /usr/local/bin/xvfb-run-safe
USER brandpal

# Keep container running
ENTRYPOINT ["/usr/local/bin/xvfb-run-safe"]
CMD ["python3"] 