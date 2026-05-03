"""AI 决策服务 - ReAct Agent

实现 Reasoning + Acting 循环：
1. 接收用户问题
2. LLM 决定是否需要调用工具
3. 调用工具获取实时数据
4. LLM 基于数据生成分析
5. 重复 2-4 直到 LLM 给出最终回答
"""
import json
import asyncio
from typing import AsyncGenerator
from loguru import logger

from .model_adapter import BaseLLMClient, LLMResponse, _model_supports_function_calling
from .tools import MCPToolExecutor, MCP_TOOLS
from .prompt_templates import get_template


# Agent 系统提示词
AGENT_SYSTEM_PROMPT = """你是一个专业的A股量化投资分析师。你的职责是分析板块资金流向、解读交易信号、评估投资风险。

你有以下工具可以调用获取实时数据：
- get_market_overview: 获取市场概览
- get_sector_ranking: 获取板块排行
- analyze_sector: 分析单个板块
- get_today_signals: 获取今日信号
- get_north_bound: 获取北向资金
- get_sector_history: 获取板块历史
- run_backtest: 运行回测

使用规则：
1. 当用户问到具体板块、市场数据、信号时，必须先调用工具获取实时数据
2. 基于获取的数据进行分析，不要编造数据
3. 如果工具返回错误，告知用户并建议稍后重试
4. 用简洁专业的语言分析，给出明确结论和建议
5. 风险提示要具体，不要泛泛而谈"""


class ReActAgent:
    """ReAct Agent - 实现工具调用循环"""

    MAX_ITERATIONS = 5
    MAX_TOOL_CALLS = 10  # 总工具调用次数上限
    TOOL_TIMEOUT = 30    # 单个工具超时(秒)
    TOTAL_TIMEOUT = 120  # 总超时(秒)

    def __init__(self, llm_client: BaseLLMClient, tool_executor: MCPToolExecutor):
        self.llm = llm_client
        self.tools = tool_executor
        # 检查模型是否支持 function calling
        self._supports_tools = _model_supports_function_calling(llm_client.model)

    async def run(self, user_message: str, history: list[dict] = None) -> AsyncGenerator[dict, None]:
        """执行 Agent 循环，流式输出"""
        import time as _time

        messages = [{"role": "system", "content": AGENT_SYSTEM_PROMPT}]
        if history:
            messages.extend(history[-10:])
        messages.append({"role": "user", "content": user_message})

        total_tool_calls = 0
        recent_tool_calls = []  # 检测重复调用
        start_time = _time.monotonic()

        for iteration in range(self.MAX_ITERATIONS):
            # 超时检查
            if _time.monotonic() - start_time > self.TOTAL_TIMEOUT:
                yield {"type": "content", "data": "分析超时，请简化问题后重试。"}
                return

            logger.info(f"Agent 迭代 {iteration + 1}/{self.MAX_ITERATIONS}")

            # 支持原生 function calling 的模型每轮都发送工具定义
            tools_to_use = MCP_TOOLS if self._supports_tools else None

            try:
                logger.info(f"发送消息数量: {len(messages)}, 工具: {tools_to_use is not None}")
                response = await self.llm.chat(
                    messages=messages,
                    temperature=0.3,
                    max_tokens=2000,
                    tools=tools_to_use,
                )
            except Exception as e:
                logger.error(f"LLM 调用失败: {e}")
                yield {"type": "content", "data": f"AI 服务暂时不可用: {str(e)}"}
                return

            if response.tool_calls:
                # 构建 assistant 消息，包含 reasoning_content（DeepSeek API 要求）
                assistant_msg = {
                    "role": "assistant",
                    "content": response.content or "",
                    "tool_calls": [
                        {"id": tc.id, "type": "function", "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)}}
                        for tc in response.tool_calls
                    ]
                }
                # DeepSeek API 要求必须传递 reasoning_content（即使为空）
                assistant_msg["reasoning_content"] = response.thinking or ""
                messages.append(assistant_msg)

                for tc in response.tool_calls:
                    total_tool_calls += 1
                    if total_tool_calls > self.MAX_TOOL_CALLS:
                        yield {"type": "content", "data": "已达到工具调用次数上限，请简化问题。"}
                        return

                    call_key = f"{tc.name}:{json.dumps(tc.arguments, sort_keys=True)}"
                    recent_tool_calls.append(call_key)
                    if recent_tool_calls[-3:].count(call_key) >= 2:
                        yield {"type": "tool_result", "data": {"name": tc.name, "result": '{"error": "重复调用已跳过"}'}}
                        messages.append({"role": "tool", "tool_call_id": tc.id, "content": '{"error": "重复调用已跳过"}'})
                        continue

                    yield {"type": "tool_call", "data": {"name": tc.name, "arguments": tc.arguments}}

                    try:
                        result = await asyncio.wait_for(
                            self.tools.execute(tc.name, tc.arguments),
                            timeout=self.TOOL_TIMEOUT,
                        )
                    except asyncio.TimeoutError:
                        result = {"error": f"工具 {tc.name} 超时"}
                    except Exception as e:
                        result = {"error": str(e)}

                    result_str = json.dumps(result, ensure_ascii=False, default=str)
                    yield {"type": "tool_result", "data": {"name": tc.name, "result": result_str}}
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": result_str})

                continue

            else:
                # 没有工具调用，流式输出最终回答
                full_thinking = ""
                full_content = ""

                if response.thinking:
                    full_thinking = response.thinking
                    yield {"type": "thinking", "data": full_thinking}

                # 使用流式输出最终回答
                async for chunk in self.llm.chat_stream(messages, temperature=0.3, max_tokens=2000):
                    if chunk["type"] == "content":
                        full_content += chunk["data"]
                        yield {"type": "content", "data": chunk["data"]}
                    elif chunk["type"] == "thinking" and not full_thinking:
                        full_thinking += chunk["data"]
                        yield {"type": "thinking", "data": chunk["data"]}

                return

        yield {"type": "content", "data": "分析完成，如需更深入分析请缩小问题范围。"}


class SimpleAgent:
    """简单 Agent - 不使用工具调用，直接回答"""

    def __init__(self, llm_client: BaseLLMClient):
        self.llm = llm_client

    async def run(self, user_message: str, history: list[dict] = None) -> LLMResponse:
        """直接调用 LLM 回答"""
        template = get_template("chat")
        messages = template.to_messages(user_message=user_message, context_text="")

        if history:
            system_msg = messages[0]
            user_msg = messages[-1]
            hist = [{"role": m["role"], "content": m["content"]} for m in history[-10:-1]]
            messages = [system_msg] + hist + [user_msg]

        return await self.llm.chat(messages)
