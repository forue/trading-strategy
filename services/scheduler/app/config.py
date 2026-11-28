"""任务调度中心 - 配置模块"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    data_collector_url: str = "http://localhost:8003"
    strategy_url: str = "http://localhost:8002"
    signal_url: str = "http://localhost:8004"
    fund_url: str = "http://localhost:8005"

    rabbitmq_host: str = "localhost"
    rabbitmq_port: int = 5672
    rabbitmq_user: str = "guest"
    rabbitmq_password: str = ""

    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str = ""

    service_port: int = 8006

    # 服务间调用密钥：策略服务的策略参数已按账号隔离，调度器没有用户登录态，
    # 用该密钥换取"内部调度"身份（数据归属管理员），不再依赖匿名访问
    internal_token: str = ""

    # Logging
    log_level: str = "INFO"

    class Config:
        env_file = ".env"


settings = Settings()
