"""AI 决策服务 - 提供商管理

管理在线模型提供商及其模型列表，持久化到 Redis。
"""
import json
from typing import Optional
from pydantic import BaseModel
from loguru import logger


class ModelInfo(BaseModel):
    """模型信息"""
    value: str
    label: str
    desc: str = ""


class ProviderConfig(BaseModel):
    """提供商配置"""
    id: str                    # 唯一标识: xiaomi, deepseek, openai 等
    name: str                  # 显示名称
    base_url: str              # API 地址
    api_key: str = ""          # API Key
    models: list[ModelInfo] = []  # 模型列表
    is_builtin: bool = False   # 是否内置（不可删除）
    is_configured: bool = False  # 是否已配置 API Key


# 预置提供商模板
BUILTIN_PROVIDERS = {
    "xiaomi": ProviderConfig(
        id="xiaomi",
        name="小米 MiMo",
        base_url="https://api.xiaomimimo.com/v1",
        is_builtin=True,
        models=[
            ModelInfo(value="mimo-v2.5-pro", label="MiMo V2.5 Pro", desc="最新旗舰"),
            ModelInfo(value="mimo-v2.5", label="MiMo V2.5", desc="标准版"),
            ModelInfo(value="mimo-v2-pro", label="MiMo V2 Pro", desc="上代旗舰"),
            ModelInfo(value="mimo-v2-omni", label="MiMo V2 Omni", desc="多模态"),
            ModelInfo(value="mimo-v2-flash", label="MiMo V2 Flash", desc="快速版"),
        ],
    ),
    "deepseek": ProviderConfig(
        id="deepseek",
        name="DeepSeek",
        base_url="https://api.deepseek.com/v1",
        is_builtin=True,
        models=[
            ModelInfo(value="deepseek-v4-pro", label="DeepSeek-V4 Pro", desc="最新旗舰"),
            ModelInfo(value="deepseek-v4-flash", label="DeepSeek-V4 Flash", desc="最新快速"),
            ModelInfo(value="deepseek-chat", label="DeepSeek-V3 (兼容)", desc="7月弃用"),
            ModelInfo(value="deepseek-reasoner", label="DeepSeek-R1 (兼容)", desc="7月弃用"),
        ],
    ),
    "openai": ProviderConfig(
        id="openai",
        name="OpenAI",
        base_url="https://api.openai.com/v1",
        is_builtin=True,
        models=[
            ModelInfo(value="gpt-4o-mini", label="GPT-4o Mini", desc="性价比最高"),
            ModelInfo(value="gpt-4o", label="GPT-4o", desc="多模态旗舰"),
            ModelInfo(value="gpt-4.1-mini", label="GPT-4.1 Mini", desc="最新轻量"),
            ModelInfo(value="gpt-4.1", label="GPT-4.1", desc="最新旗舰"),
            ModelInfo(value="o3-mini", label="o3-mini", desc="推理模型"),
            ModelInfo(value="o4-mini", label="o4-mini", desc="最新推理"),
        ],
    ),
    "qwen": ProviderConfig(
        id="qwen",
        name="通义千问",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        is_builtin=True,
        models=[
            ModelInfo(value="qwen3.6-max-preview", label="Qwen3.6 Max", desc="最新最强"),
            ModelInfo(value="qwen3.6-plus", label="Qwen3.6 Plus", desc="最新均衡"),
            ModelInfo(value="qwen3.6-flash", label="Qwen3.6 Flash", desc="最新快速"),
            ModelInfo(value="qwen-turbo", label="Qwen Turbo", desc="快速便宜"),
            ModelInfo(value="qwen-long", label="Qwen Long", desc="长文本"),
        ],
    ),
    "claude": ProviderConfig(
        id="claude",
        name="Claude",
        base_url="https://api.anthropic.com/v1",
        is_builtin=True,
        models=[
            ModelInfo(value="claude-sonnet-4-20250514", label="Claude Sonnet 4", desc="最新推荐"),
            ModelInfo(value="claude-3-7-sonnet-20250219", label="Claude 3.7 Sonnet", desc="快速"),
            ModelInfo(value="claude-3-5-haiku-20241022", label="Claude 3.5 Haiku", desc="轻量"),
        ],
    ),
    "siliconflow": ProviderConfig(
        id="siliconflow",
        name="硅基流动",
        base_url="https://api.siliconflow.cn/v1",
        is_builtin=True,
        models=[
            ModelInfo(value="deepseek-ai/DeepSeek-V4-Flash", label="DeepSeek-V4 Flash", desc="最新免费"),
            ModelInfo(value="Qwen/Qwen3.6-35B-A3B", label="Qwen3.6-35B", desc="MoE高效"),
            ModelInfo(value="Pro/zai-org/GLM-5.1", label="GLM-5.1", desc="智谱旗舰"),
            ModelInfo(value="Pro/moonshotai/Kimi-K2.6", label="Kimi K2.6", desc="月之暗面"),
            ModelInfo(value="MiniMaxAI/MiniMax-M2.5", label="MiniMax M2.5", desc="免费"),
            ModelInfo(value="deepseek-ai/DeepSeek-V3.2", label="DeepSeek-V3.2", desc="全能"),
            ModelInfo(value="deepseek-ai/DeepSeek-R1", label="DeepSeek-R1", desc="推理"),
        ],
    ),
    "ollama": ProviderConfig(
        id="ollama",
        name="Ollama 本地",
        base_url="http://host.docker.internal:11434",
        is_builtin=True,
        models=[],
    ),
}

PROVIDERS_KEY = "ai:providers"


class ProviderManager:
    """提供商管理器"""

    def __init__(self, redis_client):
        self.redis = redis_client

    def get_all(self) -> list[ProviderConfig]:
        """获取所有提供商（合并内置 + 自定义）"""
        saved = self._load_saved()
        result = []

        # 内置提供商
        for pid, builtin in BUILTIN_PROVIDERS.items():
            if pid in saved:
                merged = saved[pid]
                merged.is_builtin = True
                merged.is_configured = bool(merged.api_key)
                result.append(merged)
            else:
                builtin.is_configured = False
                result.append(builtin)

        # 自定义提供商
        for pid, cfg in saved.items():
            if pid not in BUILTIN_PROVIDERS:
                cfg.is_builtin = False
                cfg.is_configured = bool(cfg.api_key)
                result.append(cfg)

        return result

    def get_configured(self) -> list[ProviderConfig]:
        """获取已配置的提供商（有 API Key 或本地模型）"""
        all_providers = self.get_all()
        return [p for p in all_providers if p.is_configured or p.id == "ollama"]

    def get(self, provider_id: str) -> Optional[ProviderConfig]:
        """获取单个提供商"""
        all_providers = self.get_all()
        for p in all_providers:
            if p.id == provider_id:
                return p
        return None

    def save(self, config: ProviderConfig) -> ProviderConfig:
        """保存提供商配置"""
        saved = self._load_saved()
        saved[config.id] = config
        self._save_all(saved)
        config.is_configured = bool(config.api_key)
        return config

    def delete(self, provider_id: str) -> bool:
        """删除自定义提供商（内置不可删除）"""
        if provider_id in BUILTIN_PROVIDERS:
            return False
        saved = self._load_saved()
        if provider_id in saved:
            del saved[provider_id]
            self._save_all(saved)
        return True

    def _load_saved(self) -> dict[str, ProviderConfig]:
        """从 Redis 加载"""
        raw = self.redis.get(PROVIDERS_KEY)
        if raw:
            try:
                data = json.loads(raw)
                result = {}
                for pid, cfg_data in data.items():
                    result[pid] = ProviderConfig(**cfg_data)
                return result
            except Exception as e:
                logger.warning(f"加载提供商配置失败: {e}")
        return {}

    def _save_all(self, providers: dict[str, ProviderConfig]):
        """保存所有到 Redis"""
        data = {pid: cfg.model_dump() for pid, cfg in providers.items()}
        self.redis.set(PROVIDERS_KEY, json.dumps(data, ensure_ascii=False))
