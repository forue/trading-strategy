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
    turnover: float = 0.0
    market_change: float = 0.0
    market_sentiment: str = "中性"


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

        messages = self.template.to_messages(
            sector_name=signal.get("sector_name", "未知"),
            sector_code=signal.get("sector_code", ""),
            direction=signal.get("direction", ""),
            direction_cn=direction_cn,
            score=round(signal.get("score", 0), 2),
            position_pct=position_pct,
            strategy_type=signal.get("strategy_type", "MODERATE"),
            reason=signal.get("reason", ""),
            change_5d=round(context.change_5d, 2),
            change_10d=round(context.change_10d, 2),
            change_today=round(context.change_today, 2),
            main_flow=round(context.main_flow / 1e8, 2),
            north_flow=round(context.north_flow / 1e8, 2),
            turnover=round(context.turnover / 1e8, 2),
            market_change=round(context.market_change, 2),
            market_sentiment=context.market_sentiment,
            signal_history_text=getattr(context, 'signal_history_text', '无历史信号数据'),
        )

        try:
            response = await self.llm.chat(messages, temperature=0.7, max_tokens=1000)
            result = self._parse_response(response, signal)
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

    def _parse_response(self, response: LLMResponse, signal: dict) -> SignalAnalysis:
        """解析 LLM 响应"""
        try:
            content = response.content.strip()
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
            else:
                data = json.loads(content)

            return SignalAnalysis(
                sector_code=signal.get("sector_code", ""),
                sector_name=signal.get("sector_name", ""),
                direction=signal.get("direction", ""),
                interpretation=data.get("interpretation", ""),
                risk_factors=data.get("risk_factors", []),
                confidence=float(data.get("confidence", 0.5)),
                suggestion=data.get("suggestion", ""),
                model=response.model,
                tokens_used=response.tokens_used,
                latency_ms=response.latency_ms,
            )
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning(f"LLM 响应解析失败，使用原文: {e}")
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
