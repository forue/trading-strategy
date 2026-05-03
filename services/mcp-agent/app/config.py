"""MCP 金融 Agent 服务 - 配置模块"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # AI 模型配置
    ai_provider: str = "openai"
    ai_api_key: str = ""
    ai_base_url: str = "https://api.deepseek.com/v1"
    ai_model: str = "deepseek-chat"

    # Ollama
    ollama_base_url: str = "http://host.docker.internal:11434"
    ollama_model: str = "qwen2.5:7b"

    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str = ""
    redis_db: int = 4

    # RabbitMQ
    rabbitmq_host: str = "localhost"
    rabbitmq_port: int = 5672
    rabbitmq_user: str = "guest"
    rabbitmq_password: str = ""

    # InfluxDB
    influxdb_url: str = "http://localhost:8086"
    influxdb_token: str = ""
    influxdb_org: str = "rotation"
    influxdb_bucket: str = "market_data"

    # 内部服务地址
    strategy_url: str = "http://backend-strategy:8002"
    data_collector_url: str = "http://backend-data-collector:8003"
    signal_url: str = "http://backend-signal:8004"

    # Service
    service_port: int = 8008
    log_level: str = "INFO"

    class Config:
        env_file = ".env"


settings = Settings()
