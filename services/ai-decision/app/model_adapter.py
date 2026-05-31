"""AI 决策服务 - 模型适配器

支持 OpenAI API (兼容 Claude/通义千问等) 和 Ollama 本地模型。
采用策略模式 + 工厂模式，运行时切换模型后端。
支持流式输出 (SSE) 和 thinking 内容。
"""
import re
import time
import json
import httpx
from abc import ABC, abstractmethod
from typing import AsyncGenerator
from pydantic import BaseModel
from loguru import logger


class ToolCall(BaseModel):
    """工具调用"""
    id: str
    name: str
    arguments: dict


class LLMResponse(BaseModel):
    """统一的 LLM 响应格式"""
    content: str
    thinking: str = ""
    model: str
    tokens_used: int = 0
    latency_ms: int = 0
    tool_calls: list[ToolCall] = []


# 支持 thinking 的模型列表
THINKING_MODELS = {
    "deepseek-reasoner",
    "deepseek-r1",
    "deepseek-chat",
    "qwen-max",
    "qwen-plus",
    "qwen-turbo",
}

# 需要显式开启 thinking 的模型
EXPLICIT_THINKING_MODELS = {
    "qwen-max",
    "qwen-plus",
    "qwen-turbo",
}

# 支持 function calling 的模型列表
FUNCTION_CALLING_MODELS = {
    "deepseek-v4-pro",
    "deepseek-v4-flash",
    "deepseek-chat",
    "deepseek-reasoner",
    "qwen-max",
    "qwen-plus",
    "qwen-turbo",
    "gpt-4",
    "gpt-3.5-turbo",
}


def _model_supports_thinking(model: str) -> bool:
    """判断模型是否支持 thinking（OpenAI API 格式）"""
    model_lower = model.lower()
    for m in THINKING_MODELS:
        if m in model_lower:
            return True
    if "reason" in model_lower or "think" in model_lower:
        return True
    return False


def _needs_explicit_thinking(model: str) -> bool:
    """判断模型是否需要显式发送 enable_thinking 参数"""
    model_lower = model.lower()
    for m in EXPLICIT_THINKING_MODELS:
        if m in model_lower:
            return True
    return False


def _model_supports_function_calling(model: str) -> bool:
    """判断模型是否支持 function calling（OpenAI API 格式）"""
    model_lower = model.lower()
    for m in FUNCTION_CALLING_MODELS:
        if m in model_lower:
            return True
    if "gpt" in model_lower or "qwen" in model_lower:
        return True
    return False


# Ollama 模型能力缓存: {model_name: {"native_tools": bool, "native_think": bool}}
_ollama_capability_cache: dict[str, dict] = {}


def _parse_think_tags(text: str) -> tuple[str, str]:
    """从文本中解析 <think>...</think> 标签，返回 (thinking, content)"""
    match = re.search(r'<think>(.*?)</think>', text, re.DOTALL)
    if match:
        thinking = match.group(1).strip()
        content = re.sub(r'<think>.*</think>', '', text, flags=re.DOTALL).strip()
        return thinking, content
    return "", text


def _parse_tool_calls_from_text(content: str, known_tools: list[dict] = None) -> list[ToolCall]:
    """从文本中解析工具调用

    支持的格式:
    1. get_market_overview()
    2. get_sector_ranking({"metric": "change"})
    3. 工具名列表中匹配
    """
    tool_calls = []
    known_names = set()
    if known_tools:
        for t in known_tools:
            func = t.get("function", {})
            known_names.add(func.get("name", ""))

    # 匹配函数调用模式: word( 或 word()
    pattern = r'(\w+)\s*\(([^)]*)\)'
    for match in re.finditer(pattern, content):
        func_name = match.group(1)
        args_str = match.group(2).strip()

        # 只匹配已知工具名或 MCP 工具名格式
        if known_names and func_name not in known_names:
            continue
        if not known_names and not func_name.startswith("get_") and not func_name.startswith("analyze_") and not func_name.startswith("run_"):
            continue

        # 跳过 Python 内置函数
        if func_name in ('if', 'for', 'while', 'print', 'len', 'str', 'int', 'float',
                         'list', 'dict', 'set', 'tuple', 'range', 'type', 'isinstance'):
            continue

        try:
            args = json.loads(args_str) if args_str else {}
        except (json.JSONDecodeError, ValueError):
            # 尝试解析 key=value 格式
            args = {}
            if args_str:
                for part in args_str.split(","):
                    part = part.strip().strip("'\"")
                    if "=" in part:
                        k, v = part.split("=", 1)
                        v = v.strip().strip("'\"")
                        try:
                            v = json.loads(v)
                        except (json.JSONDecodeError, ValueError):
                            pass
                        args[k.strip()] = v
                if not args:
                    # 无法解析，保留原始文本
                    args = {"_raw": args_str}

        tool_calls.append(ToolCall(
            id=f"call_{func_name}_{len(tool_calls)}",
            name=func_name,
            arguments=args,
        ))

    return tool_calls


class BaseLLMClient(ABC):
    """LLM 客户端基类"""

    @abstractmethod
    async def chat(self, messages: list[dict], temperature: float = 0.7, max_tokens: int = 2000, tools: list = None, **kwargs) -> LLMResponse:
        pass

    @abstractmethod
    async def chat_stream(self, messages: list[dict], temperature: float = 0.7, max_tokens: int = 2000, tools: list = None, **kwargs) -> AsyncGenerator[dict, None]:
        pass

    @abstractmethod
    async def health_check(self, **kwargs) -> bool:
        pass


class OpenAIClient(BaseLLMClient):
    """OpenAI API 客户端 (兼容所有 OpenAI 格式 API)"""

    def __init__(self, api_key: str, base_url: str, model: str):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._client = httpx.AsyncClient(
            timeout=120,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )

    def _build_payload(self, messages: list[dict], temperature: float, max_tokens: int, stream: bool = False, tools: list = None) -> dict:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }
        if _needs_explicit_thinking(self.model):
            payload["enable_thinking"] = True
        if tools:
            payload["tools"] = tools
        return payload

    def _extract_thinking(self, msg: dict) -> str:
        for key in ("reasoning_content", "thinking"):
            val = msg.get(key, "")
            if val:
                return val
        return ""

    def _extract_delta_thinking(self, delta: dict) -> str:
        for key in ("reasoning_content", "thinking"):
            val = delta.get(key, "")
            if val:
                return val
        return ""

    def _extract_tool_calls(self, msg: dict) -> list[ToolCall]:
        raw_calls = msg.get("tool_calls", [])
        if not raw_calls:
            return []
        result = []
        for tc in raw_calls:
            try:
                func = tc.get("function", {})
                args_str = func.get("arguments", "{}")
                args = json.loads(args_str) if isinstance(args_str, str) else args_str
                result.append(ToolCall(
                    id=tc.get("id", ""),
                    name=func.get("name", ""),
                    arguments=args,
                ))
            except Exception as e:
                logger.warning(f"解析 tool_call 失败: {e}")
        return result

    async def chat(self, messages: list[dict], temperature: float = 0.7, max_tokens: int = 2000, tools: list = None, **kwargs) -> LLMResponse:
        start_time = time.monotonic()
        try:
            payload = self._build_payload(messages, temperature, max_tokens, stream=False, tools=tools)
            resp = await self._client.post(f"{self.base_url}/chat/completions", json=payload)
            resp.raise_for_status()
            data = resp.json()

            msg = data["choices"][0]["message"]
            content = msg.get("content", "") or ""
            thinking = self._extract_thinking(msg)
            tool_calls = self._extract_tool_calls(msg)
            tokens_used = data.get("usage", {}).get("total_tokens", 0)
            latency_ms = int((time.monotonic() - start_time) * 1000)

            return LLMResponse(
                content=content, thinking=thinking, model=self.model,
                tokens_used=tokens_used, latency_ms=latency_ms, tool_calls=tool_calls
            )
        except Exception as e:
            logger.error(f"OpenAI API 调用失败: {e}")
            if hasattr(e, 'response'):
                logger.error(f"OpenAI API 响应: {e.response.text[:500]}")
            raise

    async def health_check(self, **kwargs) -> bool:
        try:
            resp = await self._client.get(f"{self.base_url}/models", timeout=5)
            return resp.status_code == 200
        except Exception:
            return False

    async def close(self):
        await self._client.aclose()

    async def chat_stream(self, messages: list[dict], temperature: float = 0.7, max_tokens: int = 2000, tools: list = None, **kwargs) -> AsyncGenerator[dict, None]:
        try:
            payload = self._build_payload(messages, temperature, max_tokens, stream=True, tools=tools)
            streaming_tool_calls: dict[int, dict] = {}
            async with self._client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                json=payload,
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str.strip() == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                        delta = data.get("choices", [{}])[0].get("delta", {})
                        thinking = self._extract_delta_thinking(delta)
                        if thinking:
                            yield {"type": "thinking", "data": thinking}
                        content = delta.get("content", "")
                        if content:
                            yield {"type": "content", "data": content}
                        if "tool_calls" in delta:
                            for tc in delta["tool_calls"]:
                                idx = tc.get("index", 0)
                                if idx not in streaming_tool_calls:
                                    streaming_tool_calls[idx] = {"name": "", "arguments": "", "id": tc.get("id", "")}
                                func = tc.get("function", {})
                                if func.get("name"):
                                    streaming_tool_calls[idx]["name"] = func["name"]
                                if func.get("arguments"):
                                    streaming_tool_calls[idx]["arguments"] += func["arguments"]
                    except json.JSONDecodeError:
                        continue

            # 流结束后 yield 完整的 tool_calls
            for idx, tc in streaming_tool_calls.items():
                if tc["name"]:
                    try:
                        args = json.loads(tc["arguments"]) if tc["arguments"] else {}
                    except json.JSONDecodeError:
                        args = {}
                    yield {"type": "tool_call", "data": {"name": tc["name"], "arguments": args}}
        except Exception as e:
            logger.error(f"OpenAI 流式调用失败: {e}")
            yield {"type": "error", "data": str(e)}


class OllamaClient(BaseLLMClient):
    """Ollama 本地模型客户端

    模型能力探测策略:
    - 初始化时通过向 Ollama 发送探测请求，判断模型是否支持原生 tools / think 参数
    - 探测结果缓存，后续请求直接使用
    - 对于不支持原生能力的模型，从文本内容中解析 <think> 标签和工具调用
    """

    def __init__(self, base_url: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._client = httpx.AsyncClient(timeout=300)
        # 模型能力标记，-1 表示未探测
        self._native_tools: int = -1   # -1=未知, 0=不支持, 1=支持
        self._native_think: int = -1   # -1=未知, 0=不支持, 1=支持

    async def _probe_capabilities(self) -> None:
        """探测模型是否支持原生 tools 和 think 参数

        通过向 Ollama 发送最小请求来检测:
        1. 先测试 think 参数
        2. 再测试 tools 参数
        结果缓存到 _ollama_capability_cache
        """
        cache_key = self.model
        if cache_key in _ollama_capability_cache:
            caps = _ollama_capability_cache[cache_key]
            self._native_tools = 1 if caps["native_tools"] else 0
            self._native_think = 1 if caps["native_think"] else 0
            return

        logger.info(f"探测 Ollama 模型能力: {self.model}")

        # 测试 think 参数
        try:
            resp = await self._client.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": "hi"}],
                    "stream": False,
                    "think": True,
                    "options": {"num_predict": 1},
                },
                timeout=30,
            )
            if resp.status_code == 200:
                self._native_think = 1
                logger.info(f"模型 {self.model} 支持原生 think")
            else:
                self._native_think = 0
                logger.info(f"模型 {self.model} 不支持原生 think (HTTP {resp.status_code})")
        except Exception as e:
            self._native_think = 0
            logger.warning(f"模型 {self.model} think 探测失败: {e}")

        # 测试 tools 参数
        try:
            resp = await self._client.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": "hi"}],
                    "stream": False,
                    "tools": [{
                        "type": "function",
                        "function": {
                            "name": "_test_probe",
                            "description": "test",
                            "parameters": {"type": "object", "properties": {}}
                        }
                    }],
                    "options": {"num_predict": 1},
                },
                timeout=30,
            )
            if resp.status_code == 200:
                self._native_tools = 1
                logger.info(f"模型 {self.model} 支持原生 tools")
            else:
                self._native_tools = 0
                logger.info(f"模型 {self.model} 不支持原生 tools (HTTP {resp.status_code})")
        except Exception as e:
            self._native_tools = 0
            logger.warning(f"模型 {self.model} tools 探测失败: {e}")

        _ollama_capability_cache[cache_key] = {
            "native_tools": self._native_tools == 1,
            "native_think": self._native_think == 1,
        }

    async def _ensure_probed(self) -> None:
        """确保模型能力已探测"""
        if self._native_tools == -1:
            await self._probe_capabilities()

    def _build_payload(self, messages: list[dict], temperature: float, max_tokens: int,
                       stream: bool, tools: list = None) -> dict:
        """根据模型能力构建请求 payload"""
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": stream,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        # 只在模型支持原生 tools 时才发送
        if tools and self._native_tools == 1:
            payload["tools"] = tools
        # 只在模型支持原生 think 时才发送
        if self._native_think == 1:
            payload["think"] = True
        return payload

    async def chat(self, messages: list[dict], temperature: float = 0.7, max_tokens: int = 2000, tools: list = None, **kwargs) -> LLMResponse:
        await self._ensure_probed()
        start_time = time.monotonic()
        try:
            payload = self._build_payload(messages, temperature, max_tokens, stream=False, tools=tools)
            resp = await self._client.post(f"{self.base_url}/api/chat", json=payload)
            if resp.status_code == 500:
                raise Exception(f"Ollama 服务错误: {resp.text[:200]}")
            resp.raise_for_status()
            data = resp.json()

            msg = data.get("message", {})
            raw_content = msg.get("content", "")
            if not raw_content:
                raise Exception("Ollama 返回空内容")

            # 提取 thinking: 优先用原生字段，否则从 content 中解析 <think> 标签
            thinking = msg.get("thinking", "") or ""
            content = raw_content
            if not thinking:
                thinking, content = _parse_think_tags(raw_content)

            # 提取 tool_calls: 优先用原生字段，否则从 content 中解析文本形式
            tool_calls: list[ToolCall] = []
            if "tool_calls" in msg:
                for tc in msg["tool_calls"]:
                    func = tc.get("function", {})
                    tool_calls.append(ToolCall(
                        id=f"call_{func.get('name', '')}_{len(tool_calls)}",
                        name=func.get("name", ""),
                        arguments=func.get("arguments", {}),
                    ))
            elif tools and self._native_tools == 0:
                # 模型不支持原生 tools，从文本中解析工具调用
                tool_calls = _parse_tool_calls_from_text(content, tools)

            tokens_used = data.get("eval_count", 0) + data.get("prompt_eval_count", 0)
            latency_ms = int((time.monotonic() - start_time) * 1000)

            return LLMResponse(
                content=content, thinking=thinking, model=self.model,
                tokens_used=tokens_used, latency_ms=latency_ms, tool_calls=tool_calls
            )
        except httpx.TimeoutException:
            raise Exception(f"Ollama 请求超时（模型: {self.model}）")
        except Exception as e:
            logger.error(f"Ollama API 调用失败: {e}")
            raise

    async def chat_stream(self, messages: list[dict], temperature: float = 0.7, max_tokens: int = 2000, tools: list = None, **kwargs) -> AsyncGenerator[dict, None]:
        await self._ensure_probed()
        try:
            payload = self._build_payload(messages, temperature, max_tokens, stream=True, tools=tools)
            async with self._client.stream(
                "POST",
                f"{self.base_url}/api/chat",
                json=payload,
            ) as resp:
                resp.raise_for_status()
                # 用于累积 content 以便解析 <think> 标签（非原生 think 模式）
                content_buffer = ""
                in_think = False

                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                        msg = data.get("message", {})

                        # 原生 thinking 字段
                        native_thinking = msg.get("thinking", "")
                        if native_thinking:
                            yield {"type": "thinking", "data": native_thinking}

                        content_chunk = msg.get("content", "")
                        if content_chunk:
                            if self._native_think == 1:
                                # 原生 think 模式，content 不含 <think> 标签，直接输出
                                yield {"type": "content", "data": content_chunk}
                            else:
                                # 非原生 think 模式，需要从 content 中解析 <think> 标签
                                content_buffer += content_chunk
                                # 逐字符状态机解析
                                while content_buffer:
                                    if not in_think:
                                        # 当前不在 think 中，查找 <think> 开始标签
                                        think_start = content_buffer.find("<think>")
                                        if think_start == -1:
                                            # 没有 think 标签，全部作为 content 输出
                                            # 保留最后 6 个字符以防标签被截断
                                            if len(content_buffer) > 6:
                                                yield {"type": "content", "data": content_buffer[:-6]}
                                                content_buffer = content_buffer[-6:]
                                            break
                                        else:
                                            # 输出 think 标签之前的内容
                                            if think_start > 0:
                                                yield {"type": "content", "data": content_buffer[:think_start]}
                                            content_buffer = content_buffer[think_start + 7:]  # len("<think>") = 7
                                            in_think = True
                                    else:
                                        # 当前在 think 中，查找 </think> 结束标签
                                        think_end = content_buffer.find("</think>")
                                        if think_end == -1:
                                            # think 还没结束，输出已有内容作为 thinking
                                            # 保留最后 8 个字符以防标签被截断
                                            if len(content_buffer) > 8:
                                                yield {"type": "thinking", "data": content_buffer[:-8]}
                                                content_buffer = content_buffer[-8:]
                                            break
                                        else:
                                            # think 结束
                                            if think_end > 0:
                                                yield {"type": "thinking", "data": content_buffer[:think_end]}
                                            content_buffer = content_buffer[think_end + 8:]  # len("</think>") = 8
                                            in_think = False

                        if data.get("done"):
                            # 处理剩余 buffer
                            if content_buffer:
                                if in_think:
                                    yield {"type": "thinking", "data": content_buffer}
                                else:
                                    yield {"type": "content", "data": content_buffer}
                            break
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.error(f"Ollama 流式调用失败: {e}")
            yield {"type": "error", "data": str(e)}

    async def health_check(self, **kwargs) -> bool:
        try:
            resp = await self._client.get(f"{self.base_url}/api/tags", timeout=5)
            return resp.status_code == 200
        except Exception:
            return False

    async def list_models(self) -> list[dict]:
        try:
            resp = await self._client.get(f"{self.base_url}/api/tags", timeout=10)
            resp.raise_for_status()
            return [{"name": m.get("name", ""), "size": m.get("size", 0)} for m in resp.json().get("models", [])]
        except Exception as e:
            logger.error(f"获取 Ollama 模型列表失败: {e}")
            return []

    async def close(self):
        await self._client.aclose()


class ModelAdapterFactory:
    @staticmethod
    def create(provider: str, api_key: str = "", base_url: str = "", model: str = "",
               ollama_base_url: str = "http://localhost:11434", ollama_model: str = "qwen2.5:7b") -> BaseLLMClient:
        if provider == "openai":
            if not api_key:
                raise ValueError("OpenAI provider requires api_key")
            return OpenAIClient(api_key=api_key, base_url=base_url, model=model)
        elif provider == "ollama":
            return OllamaClient(base_url=ollama_base_url, model=ollama_model)
        else:
            raise ValueError(f"Unsupported provider: {provider}")
