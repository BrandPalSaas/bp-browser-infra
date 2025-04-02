import os
import requests
import logging
from typing import Callable, Dict, Any
from collections import deque
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()
logger = logging.getLogger(__name__)


class HttpClient:
    _instance = None

    def __new__(cls, base_url: str):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.base_url = base_url.rstrip("/")
            cls._instance.session = requests.Session()
            cls._instance.request_interceptors = deque()
            cls._instance.response_interceptors = deque()
        return cls._instance

    def add_request_interceptor(self, interceptor: Callable):
        """添加请求拦截器"""
        self.request_interceptors.append(interceptor)

    def add_response_interceptor(self, interceptor: Callable):
        """添加响应拦截器"""
        self.response_interceptors.append(interceptor)

    def _apply_request_interceptors(self, method: str, url: str, **kwargs):
        """应用所有请求拦截器"""
        for interceptor in self.request_interceptors:
            try:
                method, url, kwargs = interceptor(method, url, **kwargs)
            except Exception as e:
                logger.warning(f"Request interceptor failed: {str(e)}")
        return method, url, kwargs

    def _apply_response_interceptors(self, response: requests.Response):
        """应用所有响应拦截器"""
        for interceptor in self.response_interceptors:
            try:
                response = interceptor(response)
            except Exception as e:
                logger.warning(f"Response interceptor failed: {str(e)}")
        return response

    def request(self, method: str, endpoint: str, **kwargs):
        """发送HTTP请求"""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"

        # 设置默认headers，包含content_type
        headers = kwargs.pop("headers", {})
        headers.setdefault("Content-Type", "application/json")

        # 应用请求拦截器
        method, url, kwargs = self._apply_request_interceptors(method, url, **kwargs)

        # 打印请求信息
        print("##########################################################")
        logger.info(
            f"Sending {method} \nrequest to {url} \nwith data: {kwargs}\nheaders: {headers}"
        )
        print("##########################################################")
        # 发送请求
        response = self.session.request(method, url, headers=headers, **kwargs)

        # 应用响应拦截器
        response = self._apply_response_interceptors(response)
        return response

    def get(self, endpoint: str, **kwargs):
        return self.request("GET", endpoint, **kwargs)

    def post(self, endpoint: str, **kwargs):
        return self.request("POST", endpoint, **kwargs)

    def put(self, endpoint: str, **kwargs):
        return self.request("PUT", endpoint, **kwargs)

    def delete(self, endpoint: str, **kwargs):
        return self.request("DELETE", endpoint, **kwargs)


# 全局HTTP客户端实例
http_client = HttpClient(os.getenv("BP_AI_AGENT_BASE_URL", ""))
