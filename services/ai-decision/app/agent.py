"""AI 决策服务 - ReAct Agent

实现 Reasoning + Acting 循环：
1. 接收用户问题
2. LLM 决定是否需要调用工具
3. 调用工具获取实时数据
4. LLM 基于数据生成分析
5. 重复 2-4 直到 LLM 给出最终回答
"""
import re
import json
import asyncio
from typing import AsyncGenerator
from loguru import logger

from .model_adapter import BaseLLMClient, LLMResponse, _model_supports_function_calling
from .tools import MCPToolExecutor, MCP_TOOLS
from .prompt_templates import get_template


def _estimate_tokens(text: str) -> int:
    """粗略估算 token 数（中文约 1.5 token/字，英文约 1.33 token/word）"""
    if not text:
        return 0
    cn_chars = len(re.findall(r'[一-鿿]', text))
    en_words = len(re.findall(r'[a-zA-Z]+', text))
    other = len(text) - cn_chars * 3 - en_words * 5
    return int(cn_chars * 1.5 + en_words * 1.33 + max(0, other) * 0.5)


def _truncate_messages(messages: list[dict], max_tokens: int = 12000) -> list[dict]:
    """按 token 数截断消息历史，保留 system 和最后一条 user 消息"""
    if len(messages) <= 2:
        return messages

    system_msg = messages[0]
    last_user_msg = messages[-1]
    middle = messages[1:-1]

    system_tokens = _estimate_tokens(system_msg.get("content", ""))
    user_tokens = _estimate_tokens(last_user_msg.get("content", ""))
    budget = max_tokens - system_tokens - user_tokens - 500

    kept = []
    current_tokens = 0
    for msg in reversed(middle):
        msg_tokens = _estimate_tokens(msg.get("content", ""))
        if "tool_calls" in msg:
            msg_tokens += _estimate_tokens(json.dumps(msg.get("tool_calls", [])))
        if current_tokens + msg_tokens > budget:
            break
        kept.insert(0, msg)
        current_tokens += msg_tokens

    # 清理孤零零的 tool 横向：如果 tool 消息对应的 assistant(tool_calls) 被截掉了，必须删掉 tool
    valid_tc_ids = set()
    for msg in kept:
        if "tool_calls" in msg:
            for tc in msg["tool_calls"]:
                valid_tc_ids.add(tc.get("id", ""))
    cleaned = []
    for msg in kept:
        if msg.get("role") == "tool":
            tc_id = msg.get("tool_call_id", "")
            if tc_id and tc_id not in valid_tc_ids:
                continue  # 孤立 tool 消息，丢弃
        cleaned.append(msg)

    return [system_msg] + cleaned + [last_user_msg]


def _remove_orphaned_tool_messages(messages: list[dict]) -> list[dict]:
    """移除没有对应 assistant(tool_calls) 的孤立 tool 消息"""
    valid_tc_ids = set()
    for msg in messages:
        if "tool_calls" in msg:
            for tc in msg["tool_calls"]:
                valid_tc_ids.add(tc.get("id", ""))
    return [m for m in messages if m.get("role") != "tool" or m.get("tool_call_id", "") in valid_tc_ids]


def _summarize_tool_result(tool_name: str, result: dict, max_chars: int = 2000) -> str:
    """对工具返回的大结果进行智能摘要，减少 token 消耗"""
    result_str = json.dumps(result, ensure_ascii=False, default=str)
    if len(result_str) <= max_chars:
        return result_str

    # 针对不同工具的智能摘要
    if tool_name in ("get_sector_history",) and "records" in result:
        records = result["records"]
        summary = {
            "sector_code": result.get("sector_code"),
            "total_records": len(records),
            "latest": records[-1] if records else None,
            "first": records[0] if records else None,
            "max_change": max((r.get("change_pct", 0) for r in records), default=0),
            "min_change": min((r.get("change_pct", 0) for r in records), default=0),
            "_truncated": True,
        }
        return json.dumps(summary, ensure_ascii=False, default=str)

    if tool_name in ("get_technical_indicators",):
        # 保留信号和最新值，去掉历史数组
        summary = {k: v for k, v in result.items() if k not in ("upper", "middle", "lower", "dif", "dea", "macd", "values")}
        return json.dumps(summary, ensure_ascii=False, default=str)

    if tool_name in ("compare_sectors",) and "comparison" in result:
        summary = {"days": result.get("days"), "comparison": [
            {k: v for k, v in s.items() if k not in ("daily_flows",)}
            for s in result["comparison"]
        ]}
        return json.dumps(summary, ensure_ascii=False, default=str)

    if tool_name in ("get_market_heatmap",) and "heatmap" in result:
        # 热力图只保留 top/bottom 10
        hm = result["heatmap"]
        summary = {k: v for k, v in result.items() if k != "heatmap"}
        summary["heatmap_top10"] = hm[:10]
        summary["heatmap_bottom10"] = hm[-10:]
        return json.dumps(summary, ensure_ascii=False, default=str)

    if tool_name in ("get_sector_rotation",) and "rotation_signals" in result:
        # 轮动信号保留前10条
        summary = {k: v for k, v in result.items() if k != "rotation_signals"}
        summary["rotation_signals"] = result["rotation_signals"][:10]
        return json.dumps(summary, ensure_ascii=False, default=str)

    if tool_name in ("get_factor_analysis",) and "factors" in result:
        # 因子分析保留 composite_score 和 top factors
        summary = {k: v for k, v in result.items() if k != "factors"}
        summary["factors"] = result["factors"][:8]
        return json.dumps(summary, ensure_ascii=False, default=str)

    if tool_name in ("get_global_market",) and "indices" in result:
        # 全球市场只保留前10个指数
        summary = {k: v for k, v in result.items() if k != "indices"}
        summary["indices"] = result["indices"][:10]
        return json.dumps(summary, ensure_ascii=False, default=str)

    if tool_name in ("get_market_news",) and "news" in result:
        # 新闻只保留前8条
        summary = {k: v for k, v in result.items() if k != "news"}
        summary["news"] = result["news"][:8]
        return json.dumps(summary, ensure_ascii=False, default=str)

    if tool_name in ("get_bdi",) and "records" in result:
        # BDI 只保留最近10条
        records = result["records"]
        summary = {k: v for k, v in result.items() if k != "records"}
        summary["records"] = records[-10:]
        summary["total_records"] = len(records)
        return json.dumps(summary, ensure_ascii=False, default=str)

    if tool_name in ("get_bond_spread",) and "records" in result:
        records = result["records"]
        summary = {k: v for k, v in result.items() if k != "records"}
        summary["records"] = records[-10:]
        summary["total_records"] = len(records)
        return json.dumps(summary, ensure_ascii=False, default=str)

    if tool_name in ("get_margin_data",):
        # 融资融券每市只保留最近5天
        summary = {}
        for key in ("shanghai", "shenzhen"):
            if key in result and isinstance(result[key], list):
                summary[key] = result[key][-5:]
            else:
                summary[key] = result.get(key)
        if "error" in result:
            summary["error"] = result["error"]
        return json.dumps(summary, ensure_ascii=False, default=str)

    # 通用截断
    return result_str[:max_chars] + "\n...(已截断)"


# Agent 系统提示词
AGENT_SYSTEM_PROMPT = """你是一个专业的A股量化投资分析师，擅长板块轮动分析和资金流向研究。

## 可用工具
数据查询:
- get_market_overview: 市场概览（涨跌家数、情绪、主力资金）
- get_sector_ranking: 板块涨跌排行/资金流入排行
- analyze_sector: 分析单个板块详情
- get_sector_history: 板块历史K线数据
- get_north_bound: 北向资金数据
- get_trading_dates: 交易日历
- list_sectors: 搜索板块代码（当不知道代码时先调用此工具）

信号与策略:
- get_today_signals: 获取今日交易信号
- get_signal_history: 历史信号记录和策略表现
- run_backtest: 运行策略回测
- check_portfolio_risk: 投资组合风险检查

深度分析:
- compare_sectors: 对比多个板块表现
- get_capital_flow_trend: 资金流向趋势分析
- get_technical_indicators: 技术指标（MA/MACD/RSI/布林带）
- get_sector_valuation: 板块估值分析（PE/PB历史百分位）
- get_factor_analysis: 多因子评分（动量、资金流、估值等）
- get_market_breadth: 市场宽度（涨跌比、参与率、强弱判断）
- get_fund_flow_distribution: 资金流向分布（资金集中度）
- get_sector_rotation: 板块轮动信号检测
- get_market_heatmap: 市场热力图（全部板块概览）

外部宏观数据:
- get_global_market: 全球主要市场指数（道琼斯、纳斯达克、标普500、恒生、日经等）
- get_china_macro: 中国宏观指标（PMI/CPI/PPI/GDP/M2/LPR）
- get_us_macro: 美国宏观指标（CPI/PMI/非农/失业率/美联储利率）
- get_market_news: 市场新闻资讯（东方财富/同花顺/新浪/财联社）
- get_bdi: BDI波罗的海干散货指数（大宗商品/航运领先指标）
- get_bond_spread: 中美国债收益率对比（中美利差）
- get_margin_data: 融资融券数据（杠杆资金动向）

## 工作流程
1. **数据收集**：根据问题类型调用工具获取数据
   - 市场分析 → get_market_overview + get_market_breadth + get_global_market（外围参考）
   - 板块分析 → 先 list_sectors 查代码（支持逗号分隔多关键词），再用 analyze_sector(sector_codes: [...]) 批量分析
   - 信号分析 → get_today_signals → get_signal_history
   - 板块对比 → compare_sectors + get_factor_analysis
   - 轮动分析 → get_sector_rotation + get_fund_flow_distribution
   - 宏观分析 → get_china_macro + get_us_macro + get_bond_spread + get_bdi
   - 情绪分析 → get_market_news + get_margin_data + get_global_market
2. **深度分析**：结合资金流向、技术指标、估值水平、市场情绪、宏观环境综合判断
3. **结论输出**：给出明确结论、信心度(0-10)、风险因素、可操作建议

## 规则
- 必须先获取数据再分析，禁止编造数据
- 不知道板块代码时先调 list_sectors 搜索，使用返回的 `code` 字段（如 THS881101），不要用名称
- **同轮可并行调用多个无依赖的工具**，如同时获取多个板块数据、同时查技术指标和估值
- **优先使用批量接口**：analyze_sector(sector_codes: [...]) 一次分析多个板块，list_sectors(keyword: "半导体,白酒,银行") 一次搜索多个关键词
- 工具返回错误时尝试其他工具或调整参数
- 使用 Markdown 格式，数据标注来源日期，重要结论加粗"""


class ReActAgent:
    """ReAct Agent - 实现工具调用循环"""

    MAX_ITERATIONS = 10
    MAX_TOOL_CALLS = 30  # 总工具调用次数上限
    TOOL_TIMEOUT = 30    # 单个工具超时(秒)
    TOTAL_TIMEOUT = 240  # 总超时(秒)

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
            # 清理历史中孤立的 tool 消息（对应的 assistant(tool_calls) 可能已被截断或丢失）
            clean_history = _remove_orphaned_tool_messages(history[-10:])
            messages.extend(clean_history)
        messages.append({"role": "user", "content": user_message})

        total_tool_calls = 0
        seen_tool_calls = set()  # 全局去重：跟踪所有唯一调用
        start_time = _time.monotonic()

        for iteration in range(self.MAX_ITERATIONS):
            # 超时检查
            if _time.monotonic() - start_time > self.TOTAL_TIMEOUT:
                yield {"type": "content", "data": "分析超时，请简化问题后重试。"}
                return

            logger.info(f"Agent 迭代 {iteration + 1}/{self.MAX_ITERATIONS}")

            # 注入迭代感知：帮助 agent 知道剩余预算
            if iteration > 0:
                remaining_tools = self.MAX_TOOL_CALLS - total_tool_calls
                iteration_msg = f"[系统: 当前第 {iteration + 1}/{self.MAX_ITERATIONS} 轮，剩余工具调用 {remaining_tools} 次]"
                messages.append({"role": "system", "content": iteration_msg})

            # 支持原生 function calling 的模型每轮都发送工具定义
            tools_to_use = MCP_TOOLS if self._supports_tools else None

            try:
                messages = _truncate_messages(messages)
                logger.info(f"发送消息数量: {len(messages)}, 工具: {tools_to_use is not None}")
                response = await self.llm.chat(
                    messages=messages,
                    temperature=0.3,
                    max_tokens=4000,
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

                tool_feedbacks = []  # 收集反馈，所有 tool 消息之后再注入

                # 分离需要执行的和需要跳过的调用
                exec_tasks = []  # (tc, call_key) 需要执行的
                skipped = 0
                for tc in response.tool_calls:
                    total_tool_calls += 1
                    if total_tool_calls > self.MAX_TOOL_CALLS:
                        logger.warning(f"已达工具调用上限 {self.MAX_TOOL_CALLS}，本轮第 {len(exec_tasks)} 个待执行")
                        yield {"type": "content", "data": "已达到工具调用次数上限，请简化问题。"}
                        return

                    call_key = f"{tc.name}:{json.dumps(tc.arguments, sort_keys=True)}"
                    if call_key in seen_tool_calls:
                        skipped += 1
                        yield {"type": "tool_result", "data": {"name": tc.name, "result": '{"info": "相同调用已跳过，使用之前的查询结果"}'}}
                        messages.append({"role": "tool", "tool_call_id": tc.id, "content": '{"info": "相同调用已跳过，使用之前结果"}'})
                        continue
                    seen_tool_calls.add(call_key)
                    exec_tasks.append(tc)

                logger.info(f"迭代 {iteration + 1}: LLM 请求 {len(response.tool_calls)} 个工具，执行 {len(exec_tasks)} 个，跳过 {skipped} 个重复，累计 {total_tool_calls}/{self.MAX_TOOL_CALLS}")

                # 并行执行所有工具调用
                if exec_tasks:
                    for tc in exec_tasks:
                        logger.info(f"  → {tc.name}({json.dumps(tc.arguments, ensure_ascii=False)[:120]})")
                        yield {"type": "tool_call", "data": {"name": tc.name, "arguments": tc.arguments}}

                    async def _run_one(tc):
                        try:
                            result = await asyncio.wait_for(
                                self.tools.execute(tc.name, tc.arguments),
                                timeout=self.TOOL_TIMEOUT,
                            )
                        except asyncio.TimeoutError:
                            result = {"error": f"工具 {tc.name} 超时"}
                        except Exception as e:
                            result = {"error": str(e)}
                        return tc, result

                    results = await asyncio.gather(*[_run_one(tc) for tc in exec_tasks])

                    for tc, result in results:
                        result_str = _summarize_tool_result(tc.name, result)
                        has_error = isinstance(result, dict) and "error" in result
                        logger.info(f"  ← {tc.name} → {'ERROR: ' + str(result.get('error',''))[:80] if has_error else f'{len(result_str)} chars'}")
                        yield {"type": "tool_result", "data": {"name": tc.name, "result": result_str}}
                        messages.append({"role": "tool", "tool_call_id": tc.id, "content": result_str})

                        if isinstance(result, dict) and "error" in result:
                            tool_feedbacks.append(f"工具 {tc.name} 返回错误，请尝试其他工具或调整参数重试")
                        elif isinstance(result, dict):
                            if result.get("records") == [] or result.get("signals") == [] or result.get("data") == []:
                                tool_feedbacks.append(f"工具 {tc.name} 返回空数据，请检查参数或尝试其他日期")

                # 所有 tool 消息之后，再统一注入反馈
                if tool_feedbacks:
                    messages.append({"role": "system", "content": "[系统: " + "; ".join(tool_feedbacks) + "]"})

                continue

            else:
                # 没有工具调用 = 最终回答
                if response.thinking:
                    yield {"type": "thinking", "data": response.thinking}

                if response.content:
                    # 已有内容，直接输出（不需要再次调用 LLM）
                    yield {"type": "content", "data": response.content}
                else:
                    # 极少数情况下 content 为空，用流式重试一次
                    async for chunk in self.llm.chat_stream(messages, temperature=0.3, max_tokens=2000):
                        if chunk["type"] == "content":
                            yield {"type": "content", "data": chunk["data"]}
                        elif chunk["type"] == "thinking":
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
