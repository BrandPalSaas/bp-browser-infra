import json
import asyncio
import os
from typing import Optional
import structlog
from datetime import datetime
from app.models.api import BrowserTaskStatus
from app.common.task_manager import TaskManager
from app.common.http_client import http_client
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()
log = structlog.get_logger(__name__)


async def poll_task_status(
    task_id: str, task_manager: TaskManager, timeout: int = 300, poll_interval: int = 5
) -> Optional[dict]:
    """
    轮询任务状态，直到任务完成或超时
    :param task_id: 任务ID
    :param task_manager: TaskManager实例
    :param timeout: 超时时间（秒）
    :param poll_interval: 轮询间隔（秒）
    :return: 任务结果或None（如果超时）
    """
    start_time = asyncio.get_event_loop().time()
    poll_count = 0

    log.info(
        "🔁 ℹ️ Starting task polling",
        task_id=task_id,
        start_time=datetime.now().isoformat(),
        timeout=timeout,
        poll_interval=poll_interval,
    )

    while True:
        poll_count += 1
        current_time = datetime.now().isoformat()

        # 检查超时
        if asyncio.get_event_loop().time() - start_time > timeout:
            log.warning(
                "🔁 ⚠️ Task polling timeout",
                task_id=task_id,
                current_time=current_time,
                poll_count=poll_count,
            )
            # 调用外部接口
            http_client.post("/tts/kol", data={"taskId": task_id, "GMV": None})
            return None

        # 获取任务状态
        task_status = await task_manager.get_task_result(task_id)

        log.info(
            "🔁 ℹ️ Task status update",
            task_id=task_id,
            status=task_status.task_status,
            current_time=current_time,
            poll_count=poll_count,
        )

        if task_status.task_status == BrowserTaskStatus.COMPLETED:
            log.info(
                "🔁 ✅ Task completed successfully",
                task_id=task_id,
                response=task_status.task_response,
                total_polls=poll_count,
            )
            print("--------------| 达人信息 JSON |--------------")
            # print(task_status.task_response)
            # print(json.loads(task_status.task_response))
            print(json.loads(json.loads(task_status.task_response)["final_result"]))
            print("------------------------------------------------")

            final_result = json.loads(
                json.loads(task_status.task_response)["final_result"]
            )

            # 调用外部接口
            response = http_client.post(
                "/tts/kol",
                # 将data参数改为json格式
                json={
                    "taskId": task_id,
                    "GMV": final_result["gmv"],
                },
                # data={"taskId": task_id, "GMV": final_result["gmv"]},
            )
            if response.status_code == 200:
                response_data = response.json()
                log.info("External API call succeeded", response=response_data)
            else:
                error = response.text
                log.error(
                    "External API call failed",
                    status=response.status_code,
                    error=error,
                )
                raise Exception(f"API call failed: {error}")

            return task_status.task_response
        elif task_status.task_status == BrowserTaskStatus.FAILED:
            log.error(
                "🔁 ❌ Task failed",
                task_id=task_id,
                error=task_status.task_response,
                total_polls=poll_count,
            )
            # 调用外部接口
            http_client.post("/tts/kol", data={"taskId": task_id, "GMV": None})
            raise Exception(task_status.task_response)

        await asyncio.sleep(poll_interval)
