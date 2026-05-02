"""AI 决策服务 - 模型适配器

支持 OpenAI API (兼容 Claude/通义千问等) 和 Ollama 本地模型。
采用策略模式 + 工厂模式，运行时切换模型后端。
"""
import time
import httpx
from abc import ABC, abstractmethod
from pydantic import BaseModel
from loguru import logger


class LLMResponse(BaseModel):
    """统一的 LLM 响应格式"""
    content: str
    model: str
    tokens_used: int = 0
    latency_ms: int = 0


class BaseLLMClient(ABC):
    """LLM 客户端基类"""

    @abstractmethod
    async def chat(self, messages: list[dict], temperature: float = 0.7, max_tokens: int = 2000) -> LLMResponse:
        """发送对话请求"""
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """检查模型服务是否可用"""
        pass


class OpenAIClient(BaseLLMClient):
    """OpenAI API 客户端 (兼容所有 OpenAI 格式 API)"""

    def __init__(self, api_key: str, base_url: str, model: str):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._client = httpx.AsyncClient(
            timeout=60,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )

    async def chat(self, messages: list[dict], temperature: float = 0.7, max_tokens: int = 2000) -> LLMResponse:
        start_time = time.monotonic()
        try:
            resp = await self._client.post(
                f"{self.base_url}/chat/completions",
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )
            resp.raise_for_status()
            data = resp.json()

            content = data["choices"][0]["message"]["content"]
            tokens_used = data.get("usage", {}).get("total_tokens", 0)
            latency_ms = int((time.monotonic() - start_time) * 1000)

            return LLMResponse(
                content=content,
                model=self.model,
                tokens_used=tokens_used,
                latency_ms=latency_ms,
            )
        except Exception as e:
            logger.error(f"OpenAI API 调用失败: {e}")
            raise

    async def health_check(self) -> bool:
        try:
            # 尝试调用 /models 端点
            resp = await self._client.get(f"{self.base_url}/models", timeout=5)
            return resp.status_code == 200
        except Exception:
            # 如果 /models 不可用，尝试发送一个简单的请求来验证连接
            try:
                resp = await self._client.post(
                    f"{self.base_url}/chat/completions",
                    json={
                        "model": self.model,
                        "messages": [{"role": "user", "content": "hi"}],
                        "max_tokens": 1,
                    },
                    timeout=10,
                )
                return resp.status_code in [200, 400, 401]  # 400/401 也说明服务可达
            except Exception:
                return False


class OllamaClient(BaseLLMClient):
    """Ollama 本地模型客户端"""

    def __init__(self, base_url: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._client = httpx.AsyncClient(timeout=300)

    async def chat(self, messages: list[dict], temperature: float = 0.7, max_tokens: int = 2000) -> LLMResponse:
        start_time = time.monotonic()
        try:
            resp = await self._client.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": False,
                    "options": {
                        "temperature": temperature,
                        "num_predict": max_tokens,
                    },
                },
            )
            if resp.status_code == 500:
                error_detail = ""
                try:
                    error_detail = resp.json().get("error", "")
                except Exception:
                    error_detail = resp.text[:200]
                raise Exception(f"Ollama 服务错误: {error_detail}")

            resp.raise_for_status()
            data = resp.json()

            content = data.get("message", {}).get("content", "")
            if not content:
                raise Exception("Ollama 返回空内容")

            tokens_used = data.get("eval_count", 0) + data.get("prompt_eval_count", 0)
            latency_ms = int((time.monotonic() - start_time) * 1000)

            return LLMResponse(
                content=content,
                model=self.model,
                tokens_used=tokens_used,
                latency_ms=latency_ms,
            )
        except httpx.TimeoutException:
            raise Exception(f"Ollama 请求超时（模型: {self.model}），请检查模型是否过大或 GPU 资源不足")
        except Exception as e:
            logger.error(f"Ollama API 调用失败: {e}")
            raise

    async def health_check(self) -> bool:
        try:
            resp = await self._client.get(f"{self.base_url}/api/tags", timeout=5)
            return resp.status_code == 200
        except Exception:
            return False

    async def list_models(self) -> list[dict]:
        """获取可用模型列表"""
        try:
            resp = await self._client.get(f"{self.base_url}/api/tags", timeout=10)
            resp.raise_for_status()
            data = resp.json()
            models = []
            for m in data.get("models", []):
                models.append({
                    "name": m.get("name", ""),
                    "size": m.get("size", 0),
                    "modified_at": m.get("modified_at", ""),
                })
            return models
        except Exception as e:
            logger.error(f"获取 Ollama 模型列表失败: {e}")
            return []


class ModelAdapterFactory:
    """模型适配器工厂"""

    @staticmethod
    def create(
        provider: str,
        api_key: str = "",
        base_url: str = "",
        model: str = "",
        ollama_base_url: str = "http://localhost:11434",
        ollama_model: str = "qwen2.5:7b",
    ) -> BaseLLMClient:
        if provider == "openai":
            if not api_key:
                raise ValueError("OpenAI provider requires api_key")
            return OpenAIClient(api_key=api_key, base_url=base_url, model=model)
        elif provider == "ollama":
            return OllamaClient(base_url=ollama_base_url, model=ollama_model)
        else:
            raise ValueError(f"Unsupported provider: {provider}")
