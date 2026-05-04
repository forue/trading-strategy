"""AI 决策服务 - 每日复盘报告生成器

自动收集当日市场数据和持仓表现，调用 LLM 生成复盘报告。
"""
from typing import Optional
from pydantic import BaseModel
from loguru import logger

from .model_adapter import BaseLLMClient
from .prompt_templates import get_template


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
    """复盘数据收集器"""

    def __init__(self, redis_client, influx_client=None):
        self.redis = redis_client
        self.influx = influx_client

    async def collect(self, date: str) -> MarketData:
        """收集复盘所需数据"""
        data = MarketData(date=date)

        # 1. 从 InfluxDB 读取市场数据
        if self.influx:
            try:
                market = self._query_market_data(date)
                data.sh_index = market.get("sh_index", 0)
                data.sh_change = market.get("sh_change", 0)
                data.total_turnover = market.get("total_turnover", 0)
                data.sector_performance = market.get("sector_performance", "")
            except Exception as e:
                logger.warning(f"从 InfluxDB 读取市场数据失败: {e}")

        # 2. 从 Redis 读取信号
        signals_text = []
        for st in ["AGGRESSIVE", "MODERATE", "CONSERVATIVE"]:
            raw = self.redis.get(f"signals:{st}:{date}")
            if raw:
                import json
                signals = json.loads(raw)
                if signals:
                    signals_text.append(f"{st} 策略: {len(signals)} 条信号")
                    for s in signals[:3]:
                        direction = "买入" if s.get("direction") == "BUY" else "卖出"
                        signals_text.append(f"  - {s.get('sector_name')} {direction} 评分{s.get('score', 0):.1f}")

        data.signals_text = "\n".join(signals_text) if signals_text else "今日无信号"

        # 3. 从 Redis 读取持仓
        portfolio_lines = []
        for st in ["AGGRESSIVE", "MODERATE", "CONSERVATIVE"]:
            raw = self.redis.get(f"positions:{st}")
            if raw:
                import json
                positions = json.loads(raw)
                if positions:
                    portfolio_lines.append(f"{st} 策略持仓:")
                    for code, weight in positions.items():
                        portfolio_lines.append(f"  - {code}: {weight*100:.1f}%")

        data.portfolio_text = "\n".join(portfolio_lines) if portfolio_lines else "暂无持仓"

        return data

    def _query_market_data(self, date: str) -> dict:
        """从 InfluxDB 查询当日市场数据"""
        if not self.influx:
            return {}

        query = f'''
        from(bucket: "{self.influx.bucket}")
          |> range(start: {date}T00:00:00Z, stop: {date}T23:59:59Z)
          |> filter(fn: (r) => r._measurement == "sector_capital_flow")
          |> pivot(rowKey: ["_time", "sector_code"], columnKey: ["_field"], valueColumn: "_value")
        '''
        try:
            tables = self.influx.query_api.query_data_frame(query)
            if isinstance(tables, list) and len(tables) == 0:
                return {}
            if hasattr(tables, "empty") and tables.empty:
                return {}

            records = tables.to_dict("records")
            if not records:
                return {}

            # 计算汇总数据
            total_turnover = sum(r.get("turnover", 0) for r in records)
            up_count = sum(1 for r in records if r.get("index_change_pct", 0) > 0)
            down_count = sum(1 for r in records if r.get("index_change_pct", 0) < 0)
            avg_change = sum(r.get("index_change_pct", 0) for r in records) / max(len(records), 1)

            # 板块涨跌排行
            sorted_sectors = sorted(records, key=lambda x: x.get("index_change_pct", 0), reverse=True)
            top5 = sorted_sectors[:5]
            bottom5 = sorted_sectors[-5:]

            sector_lines = [f"上涨: {up_count} 个, 下跌: {down_count} 个, 平均: {avg_change:+.2f}%"]
            sector_lines.append("涨幅前5:")
            for s in top5:
                sector_lines.append(f"  {s.get('sector_name')}: {s.get('index_change_pct', 0):+.2f}%")
            sector_lines.append("跌幅前5:")
            for s in bottom5:
                sector_lines.append(f"  {s.get('sector_name')}: {s.get('index_change_pct', 0):+.2f}%")

            return {
                "total_turnover": total_turnover,
                "up_count": up_count,
                "down_count": down_count,
                "avg_change": avg_change,
                "sector_performance": "\n".join(sector_lines),
            }
        except Exception as e:
            logger.error(f"查询市场数据失败: {e}")
            return {}
