"""AI 决策服务 - 信号解读器

负责接收策略信号，组装市场上下文，调用 LLM 生成解读。
"""
import asyncio
import json
import re
from typing import Optional
from pydantic import BaseModel
from loguru import logger

from .model_adapter import BaseLLMClient, LLMResponse
from .prompt_templates import get_template


class SignalAnalysis(BaseModel):
    """信号解读结果"""
    sector_code: str
    sector_name: str
    direction: str
    interpretation: str
    risk_factors: list[str]
    confidence: float
    suggestion: str
    model: str = ""
    tokens_used: int = 0
    latency_ms: int = 0


class MarketContext(BaseModel):
    """市场上下文数据"""
    sector_code: str = ""
    sector_name: str = ""
    change_5d: float = 0.0
    change_10d: float = 0.0
    change_today: float = 0.0
    main_flow: float = 0.0
    north_flow: float = 0.0
    # 北向净买额自 2024-08-19 起交易所停止披露，采集值恒为 0。
    # 该标记为 False 时不得把 north_flow 当作"净流入为 0"解读（会误导为"外资缺席"）。
    north_flow_available: bool = False
    turnover: float = 0.0
    # 大盘（上证指数）当日涨跌幅（%）。available 为 False 时不得把 0.0 解读为"大盘持平"。
    market_change: float = 0.0
    market_change_available: bool = False
    # 全市场板块涨跌幅的等权均值（%），反映市场宽度。与大盘指数是两个不同指标，
    # 二者差异显著（2026-09-21 上证 +0.97% vs 板块等权均值 +1.86%），不可互相替代。
    market_avg_change: Optional[float] = None
    market_sentiment: str = "中性"
    # 该板块历史信号回溯文本（含信号后收益/胜率），缺省表示无可用历史
    signal_history_text: str = "无历史信号数据"
    # 板块估值（申万行业口径 TTM 市盈率/市净率），None 表示数据缺失
    pe_ttm: Optional[float] = None
    pb: Optional[float] = None
    # 估值历史分位（0-100，越低越便宜），需≥10个交易日样本才会产出
    pe_percentile: Optional[float] = None
    pb_percentile: Optional[float] = None
    # 近5日主力资金日均净流入（亿元）
    avg_flow_5d: Optional[float] = None
    # 建议交易标的与板块排名
    etf_code: str = ""
    etf_name: str = ""
    rank: Optional[int] = None
    total_sectors: Optional[int] = None
    # 该板块市场数据是否成功获取。False 表示本次上下文构建未取到行情，
    # 提示词须把 change_*/main_flow/turnover 标注为"数据不可用"，
    # 不得把默认值 0.0 当作真实行情解读。
    data_available: bool = False


class SignalAnalyzer:
    """信号解读器"""

    def __init__(self, llm_client: BaseLLMClient):
        self.llm = llm_client
        self.template = get_template("signal_interpretation")

    async def analyze_signal(self, signal: dict, context: Optional[MarketContext] = None) -> SignalAnalysis:
        """解读单个信号"""
        if context is None:
            context = MarketContext()

        direction_cn = "买入" if signal.get("direction") == "BUY" else "卖出"
        position_pct = round(signal.get("position_ratio", 0) * 100, 1)

        # 该板块行情未取到时（如数据服务超时），所有数值字段一律渲染为"数据不可用"，
        # 避免把 MarketContext 的默认值 0.0 当作真实行情喂给 LLM
        data_ok = context.data_available
        na = "数据不可用"

        messages = self.template.to_messages(
            sector_name=signal.get("sector_name", "未知"),
            sector_code=signal.get("sector_code", ""),
            direction=signal.get("direction", ""),
            direction_cn=direction_cn,
            score=round(signal.get("score", 0), 2),
            position_pct=position_pct,
            strategy_type=signal.get("strategy_type", "MODERATE"),
            reason=signal.get("reason", ""),
            change_5d_text=f"{round(context.change_5d, 2)}%" if data_ok else na,
            change_10d_text=f"{round(context.change_10d, 2)}%" if data_ok else na,
            change_today_text=f"{round(context.change_today, 2)}%" if data_ok else na,
            main_flow_text=f"{round(context.main_flow / 1e8, 2)}亿" if data_ok else na,
            north_flow_text=(
                f"{round(context.north_flow / 1e8, 2)}亿"
                if context.north_flow_available
                else "数据不可用（交易所自2024-08-19起停止披露北向资金成交净买额）"
            ),
            turnover_text=f"{round(context.turnover / 1e8, 2)}亿" if data_ok else na,
            market_change_text=(
                f"{context.market_change:+.2f}%"
                if context.market_change_available
                else "数据不可用（大盘指数获取失败）"
            ),
            market_avg_change_text=(
                f"{context.market_avg_change:+.2f}%（全市场板块等权均值，非大盘指数）"
                if context.market_avg_change is not None
                else "数据不可用"
            ),
            # 行情缺失时不得声称"中性"，否则会被误读为真实的市场情绪
            market_sentiment=(
                context.market_sentiment if data_ok else "数据不可用（本次市场数据获取失败）"
            ),
            signal_history_text=context.signal_history_text,
            avg_flow_5d_text=(
                f"{context.avg_flow_5d:.2f}亿" if context.avg_flow_5d is not None
                else "数据不可用"
            ),
            pe_ttm_text=(
                f"{context.pe_ttm:.2f}" if context.pe_ttm is not None
                else "数据不可用（该板块暂无匹配的申万行业估值）"
            ),
            pb_text=f"{context.pb:.2f}" if context.pb is not None else "数据不可用",
            valuation_percentile_text=(
                f"市盈率分位 {context.pe_percentile:.1f}、市净率分位 {context.pb_percentile:.1f}"
                f"（取值0-100，越低越便宜）"
                if context.pe_percentile is not None and context.pb_percentile is not None
                else "数据不可用（历史样本不足10个交易日，分位尚未生成）"
            ),
            etf_text=(
                f"{context.etf_name}({context.etf_code})" if context.etf_code
                else "数据不可用（该板块未配置对应ETF）"
            ),
            rank_text=(
                f"第 {context.rank} 名 / 共 {context.total_sectors} 个板块"
                if context.rank and context.total_sectors else "数据不可用"
            ),
        )

        try:
            # deepseek-v4-flash 等推理模型的思维链与正文共享 max_tokens 预算
            # （usage.completion_tokens_details.reasoning_tokens 计入 completion_tokens），
            # 实测思维链可达 1500+ tokens：预算偏小时正文 JSON 会被从中间截断，
            # 连 interpretation 字段都提取不到，整条解读退化为原始文本。
            # 故基准预算取 4000，并在解析失败时再放宽一倍重试一次。
            response = await self.llm.chat(messages, temperature=0.7, max_tokens=4000)
            result = self._parse_response(response, signal)
            if result is None:
                logger.warning(
                    f"{signal.get('sector_name', '')} 解读解析失败（输出可能被截断），提高 token 预算重试"
                )
                response = await self.llm.chat(messages, temperature=0.7, max_tokens=8000)
                result = self._parse_response(response, signal)
            if result is None:
                logger.warning("LLM 响应解析失败，使用原文")
                result = self._raw_analysis(response, signal)
            return result
        except Exception as e:
            logger.error(f"信号解读失败: {e}")
            return self._fallback_analysis(signal)

    async def analyze_signals(self, signals: list[dict], contexts: dict[str, MarketContext] = None) -> list[SignalAnalysis]:
        """批量解读信号（并行执行）"""
        if contexts is None:
            contexts = {}

        # 限制并发为 3，避免同时发起过多 LLM 请求
        sem = asyncio.Semaphore(3)

        async def _limited(signal, context):
            async with sem:
                return await self.analyze_signal(signal, context)

        tasks = []
        for signal in signals:
            sector_code = signal.get("sector_code", "")
            context = contexts.get(sector_code, MarketContext())
            tasks.append(_limited(signal, context))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        # 将异常转为 fallback 分析
        final = []
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                logger.error(f"信号解读异常: {r}")
                final.append(self._fallback_analysis(signals[i]))
            else:
                final.append(r)
        return final

    def _parse_response(self, response: LLMResponse, signal: dict) -> Optional[SignalAnalysis]:
        """解析 LLM 响应（输出被截断时退化为逐字段提取）

        连 interpretation 都无法提取（正文被从中间截断）时返回 None，由调用方决定重试或回退。
        """
        content = response.content.strip()
        data = None
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        for candidate in (json_match.group() if json_match else None, content):
            if not candidate:
                continue
            try:
                data = json.loads(candidate)
                break
            except (json.JSONDecodeError, ValueError):
                continue

        if data is None:
            # 输出被 max_tokens 截断时 JSON 无法闭合，逐字段提取已输出的部分
            data = self._extract_fields(content)
            if not data.get("interpretation"):
                return None
            logger.warning("LLM 响应非完整 JSON，已按字段提取（输出可能被截断）")

        return SignalAnalysis(
            sector_code=signal.get("sector_code", ""),
            sector_name=signal.get("sector_name", ""),
            direction=signal.get("direction", ""),
            interpretation=data.get("interpretation", ""),
            risk_factors=data.get("risk_factors", []),
            confidence=float(data.get("confidence", 0.5)),
            suggestion=data.get("suggestion") or "请结合其他分析综合判断",
            model=response.model,
            tokens_used=response.tokens_used,
            latency_ms=response.latency_ms,
        )

    @staticmethod
    def _extract_fields(content: str) -> dict:
        """从（可能被截断的）响应文本中逐字段提取已输出内容"""
        def _unescape(raw: str) -> str:
            try:
                return json.loads(f'"{raw}"')
            except (json.JSONDecodeError, ValueError):
                return raw.replace("\\n", "\n").replace('\\"', '"').strip()

        def _str_field(name: str) -> str:
            m = re.search(rf'"{name}"\s*:\s*"((?:[^"\\]|\\.)*)"', content, re.DOTALL)
            return _unescape(m.group(1)) if m else ""

        risk_factors: list[str] = []
        m = re.search(r'"risk_factors"\s*:\s*\[(.*)', content, re.DOTALL)
        if m:
            # 数组可能被截断，取到 confidence 字段为止的整段，再抽出其中的字符串
            seg = re.split(r'"confidence"\s*:', m.group(1))[0]
            risk_factors = [_unescape(s) for s in re.findall(r'"((?:[^"\\]|\\.)*)"', seg)]

        confidence = 0.5
        cm = re.search(r'"confidence"\s*:\s*([0-9.]+)', content)
        if cm:
            try:
                confidence = float(cm.group(1))
            except ValueError:
                confidence = 0.5

        return {
            "interpretation": _str_field("interpretation"),
            "risk_factors": risk_factors,
            "confidence": confidence,
            "suggestion": _str_field("suggestion"),
        }

    def _raw_analysis(self, response: LLMResponse, signal: dict) -> SignalAnalysis:
        """解析彻底失败时的回退：直接截断使用原始文本，便于前端展示与人工判断"""
        return SignalAnalysis(
            sector_code=signal.get("sector_code", ""),
            sector_name=signal.get("sector_name", ""),
            direction=signal.get("direction", ""),
            interpretation=response.content[:500],
            risk_factors=[],
            confidence=0.5,
            suggestion="请结合其他分析综合判断",
            model=response.model,
            tokens_used=response.tokens_used,
            latency_ms=response.latency_ms,
        )

    def _fallback_analysis(self, signal: dict) -> SignalAnalysis:
        """LLM 调用失败时的回退分析"""
        direction = signal.get("direction", "")
        sector_name = signal.get("sector_name", "")
        score = signal.get("score", 0)

        if direction == "BUY":
            interpretation = f"{sector_name}板块综合评分{score:.1f}分，模型建议买入。"
            suggestion = f"建议关注{sector_name}板块，控制仓位。"
        else:
            interpretation = f"{sector_name}板块评分下降，模型建议卖出。"
            suggestion = f"建议减仓{sector_name}板块。"

        return SignalAnalysis(
            sector_code=signal.get("sector_code", ""),
            sector_name=sector_name,
            direction=direction,
            interpretation=interpretation,
            risk_factors=["AI分析服务暂不可用，信号基于量化模型生成"],
            confidence=0.3,
            suggestion=suggestion,
            model="fallback",
            tokens_used=0,
            latency_ms=0,
        )
