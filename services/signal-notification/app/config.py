"""信号通知服务 - 配置模块"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str = ""
    redis_db: int = 1

    # RabbitMQ
    rabbitmq_host: str = "localhost"
    rabbitmq_port: int = 5672
    rabbitmq_user: str = "guest"
    rabbitmq_password: str = ""

    # 钉钉推送
    dingtalk_enabled: bool = False
    dingtalk_webhook_url: str = ""
    dingtalk_secret: str = ""

    # 企业微信推送
    wecom_enabled: bool = False
    wecom_webhook_url: str = ""

    # Service
    service_port: int = 8004

    # Logging
    log_level: str = "INFO"

    class Config:
        env_file = ".env"


settings = Settings()
