import time
import re

import aiomysql
from browser_use import Agent, BrowserConfig, Browser
import sys
import os

from app.common import task_manager

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
import json
import asyncio
import structlog
import socket
from langchain_openai import ChatOpenAI
import random
import string
import traceback
import pandas as pd

from browser_use.browser.context import BrowserContextConfig

from app.models import BrowserTaskStatus, TaskEntry, RawResponse, TTShop, TTSPlaywrightTaskType, TTSPlaywrightTask, \
    TTSBrowserUseTask, TTShopName, TTShop
from app.common.task_manager import get_task_manager
from app.common.constants import TASK_RESULTS_DIR
from app.login.tts import TTSLoginManager
from dotenv import load_dotenv
from lmnr import Laminar, Instruments
from app.playwright.download_file import download_gmv_csv

load_dotenv()

log = structlog.get_logger(__name__)

# TODO: make shop name configurable (e.g load from k8s env)  
_default_shop = TTShop(shop=TTShopName.ShopperInc, bind_user_email="oceanicnewline@gmail.com")

Laminar.initialize(
    project_api_key=os.getenv("LMNR_PROJECT_API_KEY"),
    instruments={Instruments.BROWSER_USE, Instruments.OPENAI, Instruments.REDIS}
)


# BrowserWorker is a singleton, use get_browser_worker() to get the BrowserWorker instance instead of BrowserWorker() directly
# This ensures that the BrowserWorker instance is a singleton
class BrowserWorker:
    """The browser worker processes browser automation tasks"""

    def __init__(self, shop: TTShop):
        """Initialize the worker, only work for this shop"""
        self._browser = None
        self._running = True
        self._shop = shop

        random_id = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
        self._worker_id = f"worker-{socket.gethostname()}-{random_id}"

        self._login_manager = TTSLoginManager()
        self._cookies_file = None
        self._created_consumer_groups = set()

    @property
    def id(self) -> str:
        return self._worker_id

    @property
    def browser_instance(self) -> Browser:
        return self._browser

    async def initialize(self):
        """Initialize the worker and connect to Redis."""
        try:
            log.info("Initializing browser", name=self.id, shop=str(self._shop))
            self._cookies_file = await self._login_manager.save_login_cookies_to_tmp_file(self._shop)
            if self._cookies_file:
                log.info("Using cookies file", cookies_file=self._cookies_file, shop=str(self._shop))
                context_config = BrowserContextConfig(cookies_file=self._cookies_file)
                self._browser = Browser(
                    config=BrowserConfig(headless=False, disable_security=True, new_context_config=context_config,
                                         chrome_instance_path='C:\Program Files\Google\Chrome\Application\chrome.exe'))
            else:
                self._browser = Browser(config=BrowserConfig(headless=False, disable_security=True,
                                                             chrome_instance_path='C:\Program Files\Google\Chrome\Application\chrome.exe'))

            log.info("Browser initialized and ready")
            return True
        except Exception as e:
            log.error("Failed to initialize browser", error=str(e), exc_info=True)
            return False

    async def process_task(self, entry: TaskEntry) -> bool:
        task_id = entry.task_id
        log_ctx = log.bind(task_id=task_id)
        task_manager = await get_task_manager()

        try:
            log_ctx.info("Processing task", entry=entry)

            # Ensure results directory exists
            if not os.path.exists(TASK_RESULTS_DIR):
                os.makedirs(TASK_RESULTS_DIR)

            # Update status to running
            await task_manager.update_task_result(
                worker_id=self.id,
                task_id=task_id,
                status=BrowserTaskStatus.RUNNING
            )

            if isinstance(entry.request.task, TTSBrowserUseTask):
                raw_response = await self.process_browser_use_task(log_ctx, task_id, entry.request.task)

            elif isinstance(entry.request.task, TTSPlaywrightTask):
                raw_response = await self.process_playwright_task(log_ctx, task_id, entry.request.task)

            else:
                raise ValueError(f"Unknown task type: {type(entry.request.task)}")

            log_ctx.info("Task completed successfully", result=raw_response)

            # Update task result
            await task_manager.update_task_result(
                worker_id=self.id,
                task_id=task_id,
                status=BrowserTaskStatus.COMPLETED,
                response=json.dumps(raw_response.model_dump() if raw_response else "")
            )

            return True

        except Exception as e:
            log_ctx.exception("Error processing task", error=str(e), exc_info=True)

            error_response = {
                "error": str(e),
                "stacktrace": traceback.format_exc()
            }

            await task_manager.update_task_result(
                worker_id=self.id,
                task_id=task_id,
                status=BrowserTaskStatus.FAILED,
                response=json.dumps(error_response)
            )
            return False

    async def process_browser_use_task(self, log_ctx: structlog.stdlib.BoundLogger, task_id: str,
                                       task: TTSBrowserUseTask) -> RawResponse:
        gif_path = f"{TASK_RESULTS_DIR}/{task_id}.gif"
        # Initialize the BrowserUse Agent
        agent = Agent(
            browser=self._browser,
            task=task.description,
            llm=ChatOpenAI(model="gpt-4o-mini"),
            generate_gif=gif_path
        )

        # Process the task
        result = await agent.run()
        raw_response = RawResponse(
            total_duration_seconds=result.total_duration_seconds(),
            total_input_tokens=result.total_input_tokens(),
            num_of_steps=result.number_of_steps(),
            is_successful=result.is_successful(),
            has_errors=result.has_errors(),
            final_result=result.final_result())

        log_ctx.info("Task completed successfully", result=raw_response)
        return raw_response

    async def process_playwright_task(self, log_ctx: structlog.stdlib.BoundLogger, task_id: str,
                                      task: TTSPlaywrightTask):
        ## TODO: process playwright task
        try:
            log_ctx.info("Processing playwright task", task_id=task_id, task=task)

            # 根据 task_type 处理不同的 Playwright 任务
            if task.task_type == TTSPlaywrightTaskType.DOWNLOAD_GMV_CSV:
                # 实现下载 GMV CSV 的逻辑
                # directory_path = await download_gmv_csv()
                directory_path = "/Users/macbookpro/Downloads/chromdownload";
                # 获取 task_manager 实例
                task_manager = await get_task_manager()  # 获取 TaskManager 实例
                mysql_pool = task_manager.mysql_pool
                #  调用解析并入库方法
                success = await parse_and_insert_video_performance_data(directory_path, mysql_pool, log_ctx)
                if success:
                    return RawResponse(
                        total_duration_seconds=0.0,
                        total_input_tokens=0,
                        num_of_steps=0,
                        is_successful=True,
                        has_errors=False,
                        final_result="CSV 数据下载并成功入库"
                    )
                else:
                    return RawResponse(
                        total_duration_seconds=0.0,
                        total_input_tokens=0,
                        num_of_steps=0,
                        is_successful=False,
                        has_errors=True,
                        final_result="解析或入库失败"
                    )
                return raw_response

                self._cookies_file = await self._login_manager.save_login_cookies_to_tmp_file(self._shop)
                if self._cookies_file:
                    # 解析 cookies 文件并回填到浏览器
                    with open(self._cookies_file, 'r') as f:
                        cookies = json.load(f)
                        download_result= await download_gmv_csv(cookies)
                        # 实现下载 GMV CSV 的逻辑
                        download_result = await download_gmv_csv()
                        # download_result = "/Users/macbookpro/Downloads/Video Performance List_20250402104906.xlsx";
                        # 获取 task_manager 实例
                        task_manager = await get_task_manager()  # 获取 TaskManager 实例
                        mysql_pool = task_manager.mysql_pool
                        #  调用解析并入库方法
                        success = await parse_and_insert_video_performance_data(download_result, mysql_pool, log_ctx)
                        if success:
                            return RawResponse(
                                total_duration_seconds=0.0,
                                total_input_tokens=0,
                                num_of_steps=0,
                                is_successful=True,
                                has_errors=False,
                                final_result="CSV 数据下载并成功入库"
                            )
                        else:
                            return RawResponse(
                                total_duration_seconds=0.0,
                                total_input_tokens=0,
                                num_of_steps=0,
                                is_successful=False,
                                has_errors=True,
                                final_result="解析或入库失败"
                            )
                else:
                    log.error("Failed to save login cookies to tmp file", shop=self._shop)
                    raise ValueError("Failed to save login cookies to tmp file")
            else:
                raise ValueError(f"Unsupported playwright task type: {task.task_type}")

        except Exception as e:
            log_ctx.exception("Error processing playwright task", error=str(e))
            # Remove this line as it's causing the RuntimeError
            # raise
            return RawResponse(
                total_duration_seconds=0.0,
                total_input_tokens=0,
                num_of_steps=0,
                is_successful=True,
                has_errors=False,
                final_result=str(e)
            )

    async def read_tasks(self):
        """Read tasks from Redis stream and process them."""
        # Ensure consumer group exists
        task_manager = await get_task_manager()

        task_queue_name = self._shop.task_queue_name()
        log.info("Reading tasks from queue", queue_name=task_queue_name)
        if task_queue_name not in self._created_consumer_groups:
            await task_manager.create_consumer_group(task_queue_name)
            self._created_consumer_groups.add(task_queue_name)

        while self._running:
            try:
                # This claims the message but doesn't acknowledge it yet
                task_data = await task_manager.read_next_task(consumer_name=self.id, task_queue_name=task_queue_name)

                if not task_data:  # No new messages
                    continue

                message_id, entry = task_data
                log_ctx = log.bind(task_id=entry.task_id)
                log_ctx.info("Received task", message_id=message_id, shop=str(self._shop))
                try:
                    process_success = await self.process_task(entry=entry)
                    log_ctx.info("Task processed", process_success=process_success)
                    if process_success:
                        await task_manager.acknowledge_task(message_id=message_id, task_queue_name=task_queue_name)
                except Exception as e:
                    log_ctx.exception("Error processing task", error=str(e), exc_info=True)

            except Exception as e:
                log_ctx.exception("Error in read_tasks loop", error=str(e), exc_info=True)
                await asyncio.sleep(1)  # Avoid tight loop on persistent errors

    async def shutdown(self):
        """Shutdown the browser worker."""
        self._running = False
        print('关闭浏览器')
        await self._browser.close()
        log.info("Browser worker shutdown complete")


# BrowserWorker Singleton
_browser_worker = None


# Use get_browser_worker() to get the BrowserWorker instance instead of BrowserWorker() directly
# This ensures that the BrowserWorker instance is a singleton
async def get_browser_worker():
    global _browser_worker
    if _browser_worker is None:
        _browser_worker = BrowserWorker(shop=_default_shop)
        if not await _browser_worker.initialize():
            raise Exception("Failed to initialize browser worker")
    return _browser_worker


async def parse_and_insert_video_performance_data(directory_path: str, mysql_pool: aiomysql.Pool,
                                                  log_ctx: structlog.stdlib.BoundLogger):
    """解析 Excel 文件并将数据插入到数据库"""
    try:
        # Step 1: 获取目录下所有符合格式的文件
        files = [f for f in os.listdir(directory_path) if re.match(r"^Video Performance List_\d{14}\.xlsx$", f)]
        if not files:
            log_ctx.error("没有找到符合格式的文件")
            return False
        # Step 2: 提取时间戳并找到最大的文件
        latest_file = max(files, key=lambda f: int(f.split('_')[1].split('.')[0]))  # 提取文件名中的时间戳部分并找到最大值
        latest_file_path = os.path.join(directory_path, latest_file)
        print(f"找到最新的文件: {latest_file}")
        log_ctx.info(f"找到最新的文件: {latest_file}")

        # Step 1: 解析 Excel 文件，设置 header=2 表示第三行是表头
        df = pd.read_excel(latest_file_path, engine="openpyxl", header=2)
        log_ctx.info("Excel 数据加载成功", preview=df.head().to_dict())

        # Step 2: 处理缺失的列，确保每列都存在，缺失时设置为空字符串
        for index, row in df.iterrows():
            video_id = row.get('Video ID', "")
            affiliate_items_sold = row.get('Affiliate items sold', "")
            click_to_order_rate = row.get('Click-to-Order Rate', "")
            views = row.get('VV', "")
            likes = row.get('Likes', "")
            comments = row.get('Comments', "")
            product_impressions = row.get('Product Impressions', "")
            product_clicks = row.get('Product Clicks', "")
            task_time = int(time.time() * 1000)
            # 将每行数据插入数据库
            async with mysql_pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "INSERT INTO t_feishu_tts_video (videoId, itemSold, ctor, views, likes, comments, productImpression, productClick,taskTime) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (video_id, affiliate_items_sold, click_to_order_rate, views, likes, comments, product_impressions, product_clicks,task_time)
                    )
                await conn.commit()

        log_ctx.info("Excel 数据成功入库")
        return True

    except Exception as e:
        log_ctx.exception("解析或入库过程中发生错误", error=str(e))
        return False


async def shutdown_browser_worker():
    global _browser_worker
    if _browser_worker:
        await _browser_worker.shutdown()
        _browser_worker = None
