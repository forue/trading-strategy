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
    """粗略估算 token 数（中文约 1.5 token/字，英文约 0.25 token/char）"""
    if not text:
        return 0
    cn_chars = len(re.findall(r'[一-鿿]', text))
    en_chars = len(re.findall(r'[a-zA-Z]', text))
    other = len(text) - cn_chars - en_chars
    return int(cn_chars * 1.5 + en_chars * 0.25 + max(0, other) * 0.5)


def _get_context_budget(model: str) -> int:
    """根据模型名称返回截断 token 预算（保守估计，预留 40% 给工具调用和输出）"""
    m = model.lower()
    if "128k" in m or "deepseek-v4" in m:
        return 50000
    if "64k" in m or "qwen-max" in m:
        return 25000
    if "32k" in m:
        return 12000
    if "16k" in m or "gpt-4o" in m:
        return 8000
    if "8k" in m or "gpt-4" in m:
        return 4000
    # 默认：假设 8k 上下文
    return 4000


def _message_tokens(msg: dict) -> int:
    """估算单条消息的 token 数（含 tool_calls 定义）"""
    tokens = _estimate_tokens(msg.get("content", ""))
    if "tool_calls" in msg:
        tokens += _estimate_tokens(json.dumps(msg.get("tool_calls", [])))
    return tokens


def _group_middle_messages(middle: list[dict]) -> list[list[dict]]:
    """把中间消息分组：assistant(tool_calls) 与它的 tool 结果同组，其余消息各成一组

    截断必须整组进行。只丢掉 assistant 会让它的所有 tool 结果变成孤儿被清理掉，
    模型会彻底失去数据，进而重复调用工具直到超时。
    """
    groups: list[list[dict]] = []
    current: list[dict] = []
    in_tool_group = False
    for msg in middle:
        if "tool_calls" in msg:
            if current:
                groups.append(current)
            current = [msg]
            in_tool_group = True
        elif msg.get("role") == "tool" and in_tool_group:
            current.append(msg)
        else:
            if current:
                groups.append(current)
                current = []
            in_tool_group = False
            groups.append([msg])
    if current:
        groups.append(current)
    return groups


def _fit_tool_group(group: list[dict], budget: int) -> list[dict]:
    """单组放不下时：保留 assistant 与尽量新的 tool 结果，并同步裁剪 assistant 的 tool_calls

    只丢 tool 结果会让 API 因"tool_call 缺少响应"报 400，所以必须同步裁剪 tool_calls 列表。
    """
    head = group[0]
    kept_tools: list[dict] = []
    used = _message_tokens(head)
    for msg in reversed(group[1:]):
        tokens = _message_tokens(msg)
        if used + tokens > budget:
            break
        kept_tools.insert(0, msg)
        used += tokens
    if not kept_tools:
        return []

    kept_ids = {m.get("tool_call_id", "") for m in kept_tools}
    new_head = dict(head)
    new_head["tool_calls"] = [tc for tc in head.get("tool_calls", []) if tc.get("id", "") in kept_ids]
    if not new_head["tool_calls"]:
        return []
    return [new_head] + kept_tools


def _truncate_messages(messages: list[dict], max_tokens: int = 4000) -> list[dict]:
    """按 token 数截断消息历史，保留 system 和最后一条消息"""
    if len(messages) <= 2:
        return messages

    system_msg = messages[0]
    last_user_msg = messages[-1]
    middle = messages[1:-1]

    system_tokens = _estimate_tokens(system_msg.get("content", ""))
    user_tokens = _estimate_tokens(last_user_msg.get("content", ""))
    budget = max_tokens - system_tokens - user_tokens - 500

    kept: list[dict] = []
    current_tokens = 0
    for group in reversed(_group_middle_messages(middle)):
        group_tokens = sum(_message_tokens(m) for m in group)
        if group_tokens > budget:
            # 单组就超预算：只保留该组内放得下的部分数据，好过整组数据全丢
            trimmed = _fit_tool_group(group, budget) if "tool_calls" in group[0] else []
            if not trimmed:
                break
            group = trimmed
            group_tokens = sum(_message_tokens(m) for m in group)
        if current_tokens + group_tokens > budget:
            break
        kept = group + kept
        current_tokens += group_tokens
        if current_tokens >= budget:
            break

    # 兜底：清理没有对应 assistant(tool_calls) 的孤立 tool 消息
    return [system_msg] + _remove_orphaned_tool_messages(kept) + [last_user_msg]


def _tool_call_key(tc) -> str:
    """工具调用去重键（工具名 + 参数）"""
    return f"{tc.name}:{json.dumps(tc.arguments, sort_keys=True)}"


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


# Agent 系统提示词（{current_date} 在运行时替换为当前日期）
AGENT_SYSTEM_PROMPT = """你是一个专业的A股量化投资分析师，擅长板块轮动分析和资金流向研究。

**当前日期: {current_date}**

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
- get_current_positions: 获取当前策略持仓（自动从Redis读取）
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
- get_bond_spread: 国债收益率曲线摘要（中债期限利差、中美10Y利差及20日变化）
- get_margin_data: 融资融券数据（杠杆资金动向）

跨市场同步指标:
- get_overseas_commodity_fx: 外盘商品（WTI/布伦特原油、COMEX金银铜、天然气、富时A50期货）与人民币中间价
- get_commodity_futures_trend: 国内商品期货主力（原油/螺纹钢/铁矿石/沪铜）1/5/20日涨跌与持仓变化
- get_index_futures_basis: IF/IH/IC/IM股指期货主力基差与升贴水变化

情绪与结构:
- get_limit_up_stats: 涨停家数、炸板率、连板梯队、涨停行业分布、龙虎榜机构净买
- get_market_fund_structure: 超大单/大单/中单/小单逐日净流入（区分机构与散户）
- get_full_market_valuation: 全A中位PE及历史分位、沪深300/中证500市盈率

## 工作流程（工具调用最多 4 轮）
工具结果会整段回传，每多一轮都要重发全部历史，**轮次是成本的主要来源**，因此：

1. **第 1 轮：一次并行取全**。在**同一条消息**里并行调用本题需要的全部核心工具（4-6 个），
   禁止"一次只调 1 个、分多轮慢慢问"。
2. **第 2-4 轮：只补关键缺口**。每轮补 1-3 个工具，只补与结论直接相关的维度
   （例如缺"外资情绪"就补 get_overseas_commodity_fx，缺"情绪温度"就补 get_limit_up_stats），
   不重复调用已成功返回过的工具或同类工具。
3. 补充数据够用就**直接作答**，不要为凑满轮次继续取数；取不到的数据在"数据说明"里一句话声明。
   （系统对取数轮次有硬上限，超出后工具不会再执行，只会要求你立即作答）

### 各问题类型的取数清单（核心必取 + 按需补 1-3 项）
| 问题类型 | 核心（必取） | 常用补充（按需选 1-3 个，用不上就不要调） |
|---|---|---|
| 市场整体/大盘 | get_market_overview + get_market_breadth + get_fund_flow_distribution | get_market_fund_structure、get_limit_up_stats、get_full_market_valuation、get_index_futures_basis |
| 板块分析 | list_sectors → analyze_sector（批量） | get_technical_indicators、get_sector_valuation、get_factor_analysis、get_commodity_futures_trend |
| 板块对比 | compare_sectors + get_factor_analysis | get_capital_flow_trend |
| 信号/持仓 | get_today_signals + get_current_positions | check_portfolio_risk、get_signal_history |
| 轮动/资金 | get_sector_rotation + get_fund_flow_distribution | get_market_heatmap、get_market_fund_structure |
| 情绪/宏观 | get_market_news + get_margin_data | get_limit_up_stats、get_bond_spread、get_china_macro、get_us_macro |
| 外围冲击/外资 | get_global_market + get_overseas_commodity_fx | get_index_futures_basis、get_bond_spread |

同一维度的多个工具（如 heatmap 与 sector_ranking、资金分布与资金结构）按需二选一，不要都调。

## 示例
用户: 今天市场怎么样
正确做法（一轮取全 + 一轮作答）：
  1. 同一条消息并行调用：get_market_overview + get_market_breadth + get_fund_flow_distribution
     + get_market_heatmap + get_margin_data
  2. 拿到结果后按"回答格式"直接输出，不再追加工具调用

错误做法：先调 1 个 → 看结果 → 再调 1 个，分 4、5 轮凑数据。

用户: 分析一下半导体板块
正确做法：
  1. list_sectors(keyword: "半导体") → 获取代码
  2. 拿到代码后并行调用：analyze_sector + get_technical_indicators + get_sector_valuation

## 回答格式
正文控制在 **1200-2000 字**，数据用表格承载，不要把工具返回的原文数字整段重抄。必须包含：
1. **摘要**：一句话结论 + 信心度(0-10)
2. **数据**：按维度汇总关键数字（板块名、涨跌幅、资金流、评分），标注来源工具与数据日期
3. **分析**：**至少 2 条"交叉验证/背离"结论**（如 涨但主力净流出、放量滞涨、资金集中度低=无主线、
   两融变化与指数背离），不能只是数据平铺
4. **风险**：3-5 条，按影响程度排序
5. **建议**：可操作，必须写明**具体触发条件**（如"主力净流出转净流入且 top5 集中度回到 15% 以上再考虑加仓"）
6. **数据说明**（仅在有缺失时）：一句话说明未取到或不可用的维度及其对结论的影响

## 规则

### 数据获取规则
- **必须先获取数据再分析，禁止编造数据**
- 所有工具的 date 参数必须使用当前日期或其附近的日期，不指定时工具自动使用最近交易日
- **交易日感知**：A股周末和法定节假日休市，工具会自动回退到最近交易日并返回 note 字段说明
- **数据延迟**：部分数据（如北向资金、融资融券）有 T+1 延迟，分析时注意数据时效性
- 工具返回 `note` 字段时，必须在分析中说明使用的是哪天的数据
- 工具返回 `_stale: true` 时，说明数据来自过期缓存，分析可靠性降低，必须提示用户
- 工具返回 `_partial_failures` 时，在分析中明确说明哪些数据源不可用

### 分析规则
- **成本控制**：单轮并行取数，总工具调用不超过 12 个、轮次不超过 4 轮；取不到的维度用"数据说明"声明，
  不要为凑数据反复重试或重复调用同类工具
- 引用数据时必须标注来源工具名（如"根据 get_sector_ranking 返回的数据"）
- 数据不足时明确说"当前数据不足以判断"，不要编造
- 不确定的结论标注"（低置信度）"
- 禁止编造未查询过的板块代码或数字
- 不知道板块代码时先调 list_sectors 搜索，使用返回的 `code` 字段，不要用名称
- **同轮可并行调用多个无依赖的工具**，如同时获取多个板块数据、同时查技术指标和估值
- **优先使用批量接口**：analyze_sector(sector_codes: [...]) 一次分析多个板块，list_sectors(keyword: "半导体,白酒,银行") 一次搜索多个关键词
- **工具返回错误时**：尝试其他工具或调整参数重试，不要直接放弃
- **信号冲突处理**：技术面与资金面冲突时优先资金面；短期与长期信号冲突时说明分歧并给出两种情景；多因子矛盾时列出各因子方向让用户判断

### 禁止事项
- 禁止编造数据或使用训练数据中的历史信息
- 禁止在没有调用工具的情况下给出具体数字或结论
- 禁止忽略工具返回的 error 字段继续分析
- 禁止使用超过30天前的历史数据做判断（除非用户明确要求回测）
- 使用 Markdown 格式，数据标注来源日期，重要结论加粗"""


class ReActAgent:
    """ReAct Agent - 实现工具调用循环"""

    MAX_ITERATIONS = 10
    MAX_TOOL_CALLS = 30    # 总工具调用次数上限（真正控成本的是下面的轮次上限与工具参数收敛）
    MAX_TOOL_ROUNDS = 4    # 带工具调用的轮次上限：每轮都要重发全部历史，是 token 成本的主要来源
    TOOL_TIMEOUT = 30    # 单个工具超时(秒)
    TOTAL_TIMEOUT = 360  # 总超时(秒)，随轮次上限同步放宽

    def __init__(self, llm_client: BaseLLMClient, tool_executor: MCPToolExecutor):
        self.llm = llm_client
        self.tools = tool_executor
        # 检查模型是否支持 function calling
        self._supports_tools = _model_supports_function_calling(llm_client.model)

    async def _summarize_messages(self, msgs: list[dict]) -> str:
        """用 LLM 对旧消息生成智能摘要"""
        # 构建摘要请求：将消息转为纯文本
        parts = []
        for m in msgs:
            role = m.get("role", "")
            content = m.get("content", "")
            if role == "user":
                parts.append(f"用户: {content[:300]}")
            elif role == "assistant":
                if m.get("tool_calls"):
                    names = [tc.get("function", {}).get("name", "") for tc in m["tool_calls"]]
                    parts.append(f"[调用工具: {', '.join(names)}]")
                if content:
                    parts.append(f"助手: {content[:400]}")
            elif role == "tool":
                parts.append(f"[工具结果]: {content[:300]}")
        text = "\n".join(parts[-15:])  # 最多保留最近15条

        prompt = [
            {"role": "system", "content": "你是摘要助手。将以下对话历史压缩为简洁摘要，保留：1)用户的核心问题 2)查询过的工具和关键数据（数字、板块名称）3)助手的主要结论。不超过200字。"},
            {"role": "user", "content": text},
        ]
        try:
            resp = await self.llm.chat(prompt, temperature=0.1, max_tokens=300)
            return resp.content.strip() if resp.content else ""
        except Exception:
            return ""

    async def run(self, user_message: str, history: list[dict] = None) -> AsyncGenerator[dict, None]:
        """执行 Agent 循环，流式输出"""
        import time as _time

        from datetime import datetime as _dt
        system_prompt = AGENT_SYSTEM_PROMPT.replace("{current_date}", _dt.now().strftime("%Y-%m-%d %A"))
        messages = [{"role": "system", "content": system_prompt}]
        if history:
            clean_history = _remove_orphaned_tool_messages(history[-10:])

            # 长对话摘要：超过 8 条消息时，用 LLM 生成智能摘要
            if len(clean_history) > 8:
                old_msgs = clean_history[:-6]
                recent_msgs = clean_history[-6:]
                summary = await self._summarize_messages(old_msgs)
                if summary:
                    messages.append({"role": "system", "content": f"【历史摘要】{summary}"})
                messages.extend(recent_msgs)
            else:
                messages.extend(clean_history)

        messages.append({"role": "user", "content": user_message})

        total_tool_calls = 0
        tool_rounds = 0
        force_final = False  # 取数轮次用完后置 True：不再给工具定义，强制模型收口
        total_tokens = 0
        # 本次回答内去重：call_key -> 首次真实结果，重复调用直接复用
        tool_call_results: dict[str, str] = {}
        used_tools: set[str] = set()
        start_time = _time.monotonic()

        # 是否发送原生工具定义：Ollama 走实际探测结果，云端模型走模型名推断
        self._supports_tools = await self.llm.supports_native_tools()
        # 上下文截断预算：Ollama 用实际 num_ctx，云端模型按模型名推断
        ctx_budget = await self.llm.context_budget() or _get_context_budget(self.llm.model)
        # 单次生成上限：本地模型按 num_ctx 收敛，在线模型返回 0（不下发 max_tokens，不限制）
        output_budget = await self.llm.output_budget()

        for iteration in range(self.MAX_ITERATIONS):
            # 超时检查
            if _time.monotonic() - start_time > self.TOTAL_TIMEOUT:
                yield {"type": "content", "data": "分析超时，请简化问题后重试。"}
                return

            logger.info(f"Agent 迭代 {iteration + 1}/{self.MAX_ITERATIONS}")

            # 注入迭代感知：帮助 agent 知道剩余预算
            if iteration > 0:
                remaining_tools = self.MAX_TOOL_CALLS - total_tool_calls
                iteration_msg = f"[系统: 当前第 {iteration + 1}/{self.MAX_ITERATIONS} 轮，剩余工具调用 {remaining_tools} 次"
                if used_tools:
                    # 换参数重复调用同一工具同样会把结果再塞一遍上下文，明确告知模型别重复取
                    iteration_msg += f"；已取数: {', '.join(sorted(used_tools))}，不要重复调用这些工具（换参数也一样重复占用上下文）"
                iteration_msg += "]"
                messages.append({"role": "system", "content": iteration_msg})

            # 支持原生 function calling 的模型每轮都发送工具定义；强制收口时不再给工具
            tools_to_use = MCP_TOOLS if (self._supports_tools and not force_final) else None

            messages = _truncate_messages(messages, max_tokens=ctx_budget)
            logger.info(f"发送消息数量: {len(messages)}, 工具: {tools_to_use is not None}")

            # LLM 调用，指数退避重试最多 3 次
            response = None
            for _attempt in range(3):
                try:
                    response = await self.llm.chat(
                        messages=messages,
                        temperature=0.3,
                        max_tokens=output_budget,
                        tools=tools_to_use,
                    )
                    total_tokens += getattr(response, 'tokens_used', 0) or 0
                    if getattr(response, 'finish_reason', '') == "length":
                        logger.warning(
                            f"LLM 输出被长度限制截断（budget={output_budget or '不限制'}），"
                            f"本轮内容 {len(response.content or '')} 字符"
                        )
                    break
                except Exception as e:
                    if _attempt < 2:
                        wait = 2 ** _attempt
                        logger.warning(f"LLM 调用失败(第{_attempt+1}次)，{wait}秒后重试: {e}")
                        await asyncio.sleep(wait)
                    else:
                        logger.error(f"LLM 调用失败(已重试3次): {e}")
                        yield {"type": "content", "data": f"AI 服务暂时不可用: {str(e)}"}
                        return

            if response.tool_calls and force_final:
                # 已强制收口却仍要调工具：有正文就当结论输出，否则提示收敛问题
                if response.content:
                    yield {"type": "content", "data": response.content}
                    return
                yield {"type": "content", "data": "取数轮次已达上限，请缩小问题范围后重试。"}
                return

            if response.tool_calls:
                tool_rounds += 1

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

                if tool_rounds > self.MAX_TOOL_ROUNDS:
                    # 轮次是成本大头（每轮重发全量历史）：超限时不再执行工具，下一轮不带工具定义强制收口
                    logger.warning(f"已达取数轮次上限 {self.MAX_TOOL_ROUNDS}，本轮 {len(response.tool_calls)} 个工具不再执行")
                    for tc in response.tool_calls:
                        messages.append({"role": "tool", "tool_call_id": tc.id,
                                         "content": '{"info": "取数轮次已用完，请基于已有数据作答"}'})
                    messages.append({"role": "system",
                                     "content": "[系统: 取数轮次已用完，禁止再调用工具，请立即按回答格式给出完整分析]"})
                    force_final = True
                    continue

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

                    call_key = _tool_call_key(tc)
                    cached = tool_call_results.get(call_key)
                    if cached is not None:
                        # 复用首次结果：只回填"已跳过"占位文案，会让模型在上下文被截断后拿不到数据
                        skipped += 1
                        yield {"type": "tool_result", "data": {"name": tc.name, "result": cached}}
                        messages.append({"role": "tool", "tool_call_id": tc.id, "content": cached})
                        continue
                    exec_tasks.append((tc, call_key))

                logger.info(f"迭代 {iteration + 1}: LLM 请求 {len(response.tool_calls)} 个工具，执行 {len(exec_tasks)} 个，跳过 {skipped} 个重复，累计 {total_tool_calls}/{self.MAX_TOOL_CALLS}")

                # 并行执行所有工具调用
                if exec_tasks:
                    for tc, _ in exec_tasks:
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

                    results = await asyncio.gather(*[_run_one(tc) for tc, _ in exec_tasks])

                    for tc, result in results:
                        result_str = _summarize_tool_result(tc.name, result)
                        tool_call_results[_tool_call_key(tc)] = result_str
                        used_tools.add(tc.name)
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
                    yield {"type": "content", "data": response.content}
                else:
                    yield {"type": "content", "data": "（模型未返回内容，请重试）"}

                if total_tokens > 0:
                    yield {"type": "usage", "data": {"tokens_used": total_tokens}}
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
