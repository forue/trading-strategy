"""
共享库 - 提供统一的基础设施连接和工具函数

使用方法:
    from shared import rabbitmq, redis_client, ApiResponse
"""

from .rabbitmq import RabbitMQManager
from .redis_client import RedisManager
from .response import ApiResponse, success_response, error_response

__all__ = [
    "RabbitMQManager",
    "RedisManager",
    "ApiResponse",
    "success_response",
    "error_response",
]
