# Browser Management API

A scalable solution for managing browser-use instances through a REST API. This service allows you to dynamically create, manage, and delete browser sessions in containers.

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Run the server:
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## API Documentation

Once the server is running, visit:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## Features

- Profile Management API (Create, List, Delete browser profiles)
- Containerized browser instances
- Live browser session monitoring
- Resource usage tracking 