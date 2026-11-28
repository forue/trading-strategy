"""策略引擎服务 - 配置模块"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # InfluxDB
    influxdb_url: str = "http://localhost:8086"
    influxdb_token: str = ""
    influxdb_org: str = "rotation"
    influxdb_bucket: str = "market_data"

    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str = ""
    redis_db: int = 1

    # PostgreSQL (用于状态检查)
    postgres_host: str = "localhost"
    postgres_db: str = "rotation_db"
    postgres_user: str = "admin"
    postgres_password: str = ""

    # RabbitMQ
    rabbitmq_host: str = "localhost"
    rabbitmq_port: int = 5672
    rabbitmq_user: str = "guest"
    rabbitmq_password: str = ""

    # 外部服务（ETF 收盘价由 data-collector 统一采集，策略只查询，不直连数据源）
    data_collector_url: str = "http://localhost:8003"

    # 认证服务（高级功能配额校验：盘感训练每日次数）
    auth_service_url: str = "http://localhost:8001"

    # 与 auth 服务共用的 JWT 密钥，用于本地验签识别当前用户（按用户保存设置）
    jwt_secret: str = ""

    # 服务间调用密钥：调度器/mcp/ai-decision 没有用户登录态，用该密钥换取
    # 管理员身份访问策略数据；未配置时退回"无 token 视为管理员"的旧行为
    internal_token: str = ""

    # Service
    service_port: int = 8002

    # Logging
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
