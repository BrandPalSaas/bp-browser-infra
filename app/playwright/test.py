import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from app.common.http_client import http_client

response = http_client.post(
    "/tts/kol", data={"taskId": "hjkl", "GMV": None, "avgVideoViews": None}
)
if response.status_code == 200:
    response_data = response.json()
else:
    error = response.text

    raise Exception(f"API call failed: {error}")
