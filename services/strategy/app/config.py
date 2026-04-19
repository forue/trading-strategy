"""策略引擎服务 - 配置模块"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # InfluxDB
    influxdb_url: str = "http://localhost:8086"
    influxdb_token: str = "my-super-secret-token"
    influxdb_org: str = "rotation"
    influxdb_bucket: str = "market_data"

    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str = "redis123"
    redis_db: int = 1

    # RabbitMQ
    rabbitmq_host: str = "localhost"
    rabbitmq_port: int = 5672
    rabbitmq_user: str = "guest"
    rabbitmq_password: str = "guest"

    # Service
    service_port: int = 8002

    class Config:
        env_file = ".env"


settings = Settings()
