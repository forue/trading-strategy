"""AI 决策服务 - 配置模块"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # AI 模型配置
    ai_provider: str = "openai"  # openai / ollama
    ai_api_key: str = ""
    ai_base_url: str = "https://api.openai.com/v1"
    ai_model: str = "gpt-4o-mini"
    ai_temperature: float = 0.7
    ai_max_tokens: int = 2000

    # Ollama 配置
    ollama_base_url: str = "http://host.docker.internal:11434"
    ollama_model: str = "qwen2.5:7b"

    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str = ""
    redis_db: int = 3

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

    # Service
    service_port: int = 8007

    # Logging
    log_level: str = "INFO"

    class Config:
        env_file = ".env"


settings = Settings()
