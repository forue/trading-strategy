"""AI 决策服务 - 每日复盘报告生成器

自动收集当日市场数据和持仓表现，调用 LLM 生成复盘报告。
"""
from datetime import datetime
from typing import Optional

import httpx
from pydantic import BaseModel
from loguru import logger

from .model_adapter import BaseLLMClient
from .prompt_templates import get_template


def _safe_float(value, default: float = 0.0) -> float:
    """安全转换为 float，兼容 None / 空字符串 / 非数值"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class DailyReviewReport(BaseModel):
    """每日复盘报告"""
    date: str
    market_summary: str      # 市场概览
    sector_rotation: str     # 板块轮动分析
    portfolio_review: str    # 持仓表现归因
    tomorrow_outlook: str    # 明日展望
    model: str = ""
    tokens_used: int = 0


class MarketData(BaseModel):
    """市场数据"""
    date: str = ""
    sh_index: float = 0.0
    sh_change: float = 0.0
    sz_index: float = 0.0
    sz_change: float = 0.0
    cy_index: float = 0.0
    cy_change: float = 0.0
    total_turnover: float = 0.0
    sector_performance: str = ""
    portfolio_text: str = ""
    signals_text: str = ""


class DailyReviewer:
    """每日复盘报告生成器"""

    def __init__(self, llm_client: BaseLLMClient):
        self.llm = llm_client
        self.template = get_template("daily_review")

    async def generate_review(self, market_data: MarketData) -> DailyReviewReport:
        """生成每日复盘报告"""
        messages = self.template.to_messages(
            date=market_data.date,
            sh_index=f"{market_data.sh_index:.2f}",
            sh_change=f"{market_data.sh_change:+.2f}",
            sz_index=f"{market_data.sz_index:.2f}",
            sz_change=f"{market_data.sz_change:+.2f}",
            cy_index=f"{market_data.cy_index:.2f}",
            cy_change=f"{market_data.cy_change:+.2f}",
            total_turnover=f"{market_data.total_turnover:.0f}",
            sector_performance=market_data.sector_performance or "暂无数据",
            portfolio_text=market_data.portfolio_text or "暂无持仓",
            signals_text=market_data.signals_text or "今日无信号",
        )

        try:
            response = await self.llm.chat(messages, temperature=0.7, max_tokens=3000)
            content = response.content

            sections = self._parse_sections(content)

            return DailyReviewReport(
                date=market_data.date,
                market_summary=sections.get("market_summary", content[:500]),
                sector_rotation=sections.get("sector_rotation", ""),
                portfolio_review=sections.get("portfolio_review", ""),
                tomorrow_outlook=sections.get("tomorrow_outlook", ""),
                model=response.model,
                tokens_used=response.tokens_used,
            )
        except Exception as e:
            logger.error(f"复盘报告生成失败: {e}")
            return DailyReviewReport(
                date=market_data.date,
                market_summary=f"报告生成失败: {str(e)}",
                sector_rotation="",
                portfolio_review="",
                tomorrow_outlook="",
                model="error",
            )

    def _parse_sections(self, content: str) -> dict[str, str]:
        """解析报告章节"""
        sections = {}
        current_section = "market_summary"
        current_content = []

        section_markers = {
            "市场概览": "market_summary",
            "板块轮动": "sector_rotation",
            "持仓表现": "portfolio_review",
            "明日展望": "tomorrow_outlook",
            "操作建议": "tomorrow_outlook",
        }

        for line in content.split("\n"):
            matched = False
            for marker, section_name in section_markers.items():
                if marker in line and (line.startswith("#") or line.startswith("**") or line.startswith("一") or line.startswith("二") or line.startswith("三") or line.startswith("四")):
                    if current_content:
                        sections[current_section] = "\n".join(current_content).strip()
                    current_section = section_name
                    current_content = []
                    matched = True
                    break
            if not matched:
                current_content.append(line)

        if current_content:
            sections[current_section] = "\n".join(current_content).strip()

        return sections


class DailyReviewDataCollector:
    """复盘数据收集器

    数据统一来自各微服务 HTTP 接口，避免跨服务直连 Redis/InfluxDB：
      - 大盘指数：外部实时行情（新浪主源，见 external_data.get_market_indices）
      - 板块表现/成交额：data-collector /query/all-sectors
      - 信号：signal-notification /signals/history
      - 持仓：strategy /positions
    任一数据源失败只降级为占位文案，不影响其余数据与报告生成。
    """

    STRATEGIES = ("AGGRESSIVE", "MODERATE", "CONSERVATIVE")
    # 指数名称 → (点位字段, 涨跌幅字段)
    _INDEX_FIELDS = {
        "上证指数": ("sh_index", "sh_change"),
        "深证成指": ("sz_index", "sz_change"),
        "创业板指": ("cy_index", "cy_change"),
    }

    def __init__(self, strategy_url: str, data_collector_url: str, signal_url: str):
        self.strategy_url = strategy_url.rstrip("/")
        self.data_collector_url = data_collector_url.rstrip("/")
        self.signal_url = signal_url.rstrip("/")

    async def collect(self, date: str) -> MarketData:
        """收集复盘所需数据"""
        data = MarketData(date=date)

        # 1. 大盘指数（实时行情）
        await self._fill_indices(data, date)

        # 2. 板块表现与成交额（顺带取得 板块代码→名称 映射，供持仓展示用）
        sector_names = await self._fill_sectors(data, date)

        # 3. 信号
        data.signals_text = await self._collect_signals(date)

        # 4. 持仓
        data.portfolio_text = await self._collect_positions(sector_names)

        return data

    async def _fill_indices(self, data: MarketData, date: str):
        """填充三大指数点位与涨跌幅

        实时行情只能反映当前交易日；历史日期缺少可用的指数数据源
        （InfluxDB market_kline 仅含上证指数且未持续采集），
        因此非当日复盘不写入指数，避免把当日点位错标到历史日期上。
        """
        if date != datetime.now().strftime("%Y-%m-%d"):
            logger.info(f"复盘日期 {date} 非当日，跳过实时指数填充")
            return
        try:
            from .external_data import get_market_indices
            result = await get_market_indices()
        except Exception as e:
            logger.warning(f"获取大盘指数失败: {e}")
            return

        for item in result.get("indices", []):
            fields = self._INDEX_FIELDS.get(item.get("name"))
            if not fields:
                continue
            setattr(data, fields[0], _safe_float(item.get("price")))
            setattr(data, fields[1], _safe_float(item.get("change_pct")))

    async def _fill_sectors(self, data: MarketData, date: str) -> dict:
        """填充板块表现与成交额，返回 板块代码→名称 映射"""
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.get(
                    f"{self.data_collector_url}/query/all-sectors",
                    params={"start_date": date, "end_date": date},
                )
                sectors = (resp.json() or {}).get("data") or []
        except Exception as e:
            logger.warning(f"获取板块数据失败: {e}")
            data.sector_performance = "暂无数据"
            return {}

        if not sectors:
            data.sector_performance = "暂无数据"
            return {}

        name_map = {
            s.get("sector_code"): s.get("sector_name")
            for s in sectors if s.get("sector_code")
        }
        ranked = sorted(
            ((s, _safe_float(s.get("index_change_pct"))) for s in sectors),
            key=lambda x: x[1],
            reverse=True,
        )
        changes = [c for _, c in ranked]
        up_count = sum(1 for c in changes if c > 0)
        down_count = sum(1 for c in changes if c < 0)
        avg_change = sum(changes) / len(changes)

        data.total_turnover = sum(_safe_float(s.get("turnover")) for s in sectors) / 1e8

        lines = [
            f"板块总数: {len(sectors)}, 上涨: {up_count}, "
            f"下跌: {down_count}, 平均涨跌: {avg_change:+.2f}%"
        ]
        lines.append("涨幅前5:")
        for s, c in ranked[:5]:
            lines.append(f"  {s.get('sector_name')}: {c:+.2f}%")
        lines.append("跌幅前5:")
        for s, c in ranked[-5:]:
            lines.append(f"  {s.get('sector_name')}: {c:+.2f}%")
        data.sector_performance = "\n".join(lines)
        return name_map

    async def _collect_signals(self, date: str) -> str:
        """从 signal-notification 服务读取当日各策略信号"""
        lines = []
        async with httpx.AsyncClient(timeout=20) as client:
            for st in self.STRATEGIES:
                try:
                    resp = await client.get(
                        f"{self.signal_url}/signals/history",
                        params={"strategy_type": st, "start_date": date, "end_date": date},
                    )
                    signals = (resp.json() or {}).get("data") or []
                except Exception as e:
                    logger.warning(f"获取 {st} 策略信号失败: {e}")
                    continue
                if not signals:
                    continue
                lines.append(f"{st} 策略: {len(signals)} 条信号")
                for s in signals[:3]:
                    direction = {"BUY": "买入", "SELL": "卖出"}.get(
                        s.get("direction"), s.get("direction", "")
                    )
                    lines.append(
                        f"  - {s.get('sector_name')} {direction} "
                        f"评分{_safe_float(s.get('score')):.1f}"
                    )
        return "\n".join(lines) if lines else "今日无信号"

    async def _collect_positions(self, name_map: dict) -> str:
        """从 strategy 服务读取各策略当前持仓"""
        lines = []
        async with httpx.AsyncClient(timeout=20) as client:
            for st in self.STRATEGIES:
                try:
                    resp = await client.get(
                        f"{self.strategy_url}/positions",
                        params={"strategy_type": st},
                    )
                    positions = ((resp.json() or {}).get("data") or {}).get("positions") or {}
                except Exception as e:
                    logger.warning(f"获取 {st} 策略持仓失败: {e}")
                    continue
                if not positions:
                    continue
                lines.append(f"{st} 策略持仓:")
                for code, weight in positions.items():
                    lines.append(
                        f"  - {name_map.get(code) or code}: {_safe_float(weight) * 100:.1f}%"
                    )
        return "\n".join(lines) if lines else "暂无持仓"
