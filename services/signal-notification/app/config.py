"""信号通知服务 - 配置模块"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str = ""
    redis_db: int = 1

    # 与 auth 服务共用的 JWT 密钥，用于本地验签识别当前用户（推送配置按用户隔离）
    jwt_secret: str = ""

    # 服务间调用密钥：ai-decision / 调度器等内部服务没有用户登录态，
    # 用它换取管理员身份读取信号；未配置时退回"无 token 视为管理员"
    internal_token: str = ""

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

    # AI 分析随信号推送：生成信号后等待 AI 解读完成再合并推送（超时则降级为无AI推送）
    ai_push_enabled: bool = True
    ai_push_wait_seconds: int = 120

    # Service
    service_port: int = 8004

    # Logging
    log_level: str = "INFO"

    class Config:
        env_file = ".env"


settings = Settings()
