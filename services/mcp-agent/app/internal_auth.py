"""服务间调用凭证

mcp-agent 没有用户登录态，而 strategy / signal 服务的策略参数与信号已按账号
隔离（无凭证的匿名请求会被拒绝）。内部服务统一用 INTERNAL_TOKEN 换取管理员
口径，与调度器、ai-decision 保持同一套约定。
"""
import os

_HEADER_NAME = "X-Internal-Token"


def internal_headers() -> dict:
    """返回访问内部服务时要带的请求头（未配置密钥时返回空 dict，兼容旧部署）"""
    token = os.getenv("INTERNAL_TOKEN", "")
    return {_HEADER_NAME: token} if token else {}
