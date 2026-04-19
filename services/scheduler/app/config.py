"""任务调度中心 - 配置模块"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    data_collector_url: str = "http://localhost:8003"
    strategy_url: str = "http://localhost:8002"
    signal_url: str = "http://localhost:8004"

    rabbitmq_host: str = "localhost"
    rabbitmq_port: int = 5672
    rabbitmq_user: str = "guest"
    rabbitmq_password: str = "guest"

    service_port: int = 8006

    class Config:
        env_file = ".env"


settings = Settings()
