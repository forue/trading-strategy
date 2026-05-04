"""AI 决策服务 - MCP Agent 工具定义

定义 AI 可调用的工具，用于获取实时交易数据。
支持非交易日自动回退：周末、节假日等无数据时，自动回退到最近有数据的交易日。
"""
import json
import httpx
from datetime import datetime, timedelta
from typing import Any
from loguru import logger


MAX_FALLBACK_DAYS = 7  # 最多回退天数


def _get_latest_trading_day() -> str:
    """获取最近交易日（周一到周五），仅处理周末回退"""
    today = datetime.now()
    if today.weekday() == 5:  # 周六
        target = today - timedelta(days=1)
    elif today.weekday() == 6:  # 周日
        target = today - timedelta(days=2)
    else:
        target = today
    return target.strftime("%Y-%m-%d")


# 工具定义（OpenAI function calling 格式）
MCP_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_market_overview",
            "description": "获取当日市场概览：涨跌家数、平均涨跌幅、市场情绪、北向资金等",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "日期 YYYY-MM-DD，默认今天"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_sector_ranking",
            "description": "获取板块涨跌排行，包括涨跌幅、主力净流入、北向资金",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "日期 YYYY-MM-DD，默认今天"},
                    "metric": {"type": "string", "enum": ["change", "inflow"], "description": "排序指标：change=涨跌幅，inflow=资金流入"},
                    "limit": {"type": "integer", "description": "返回数量，默认10"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_sector",
            "description": "分析单个板块：资金流向、涨跌幅、主力净流入、北向资金、技术指标",
            "parameters": {
                "type": "object",
                "properties": {
                    "sector_code": {"type": "string", "description": "板块代码，如 SW801780"},
                    "date": {"type": "string", "description": "日期 YYYY-MM-DD，默认今天"}
                },
                "required": ["sector_code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_today_signals",
            "description": "获取今日交易信号：买入/卖出信号、评分、仓位建议",
            "parameters": {
                "type": "object",
                "properties": {
                    "strategy_type": {"type": "string", "enum": ["AGGRESSIVE", "MODERATE", "CONSERVATIVE"], "description": "策略类型"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_north_bound",
            "description": "获取北向资金流入流出数据",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "日期 YYYY-MM-DD，默认今天"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_sector_history",
            "description": "获取板块历史数据序列（K线、资金流）",
            "parameters": {
                "type": "object",
                "properties": {
                    "sector_code": {"type": "string", "description": "板块代码"},
                    "days": {"type": "integer", "description": "天数，默认20"}
                },
                "required": ["sector_code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_backtest",
            "description": "运行策略回测，获取历史收益、回撤等指标",
            "parameters": {
                "type": "object",
                "properties": {
                    "strategy_type": {"type": "string", "enum": ["AGGRESSIVE", "MODERATE", "CONSERVATIVE"]},
                    "start_date": {"type": "string", "description": "开始日期"},
                    "end_date": {"type": "string", "description": "结束日期"}
                },
                "required": ["start_date", "end_date"]
            }
        }
    }
]


class MCPToolExecutor:
    """MCP 工具执行器"""

    def __init__(self, strategy_url: str, data_collector_url: str, signal_url: str):
        self.strategy_url = strategy_url.rstrip("/")
        self.data_collector_url = data_collector_url.rstrip("/")
        self.signal_url = signal_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=30)

    async def close(self):
        """关闭 HTTP 客户端"""
        await self._client.aclose()

    async def _query_with_fallback(self, url: str, params: dict, date_key: str = "date") -> tuple[dict, str]:
        """带自动回退的数据查询

        如果指定日期无数据，自动往前推一天重试，最多回退 MAX_FALLBACK_DAYS 天。
        返回 (响应数据, 实际查询日期)。
        """
        start_date = params.get("start_date", "")
        if not start_date:
            start_date = _get_latest_trading_day()
            params["start_date"] = start_date
            params["end_date"] = start_date

        current = datetime.strptime(start_date, "%Y-%m-%d")
        for i in range(MAX_FALLBACK_DAYS + 1):
            try_date = (current - timedelta(days=i)).strftime("%Y-%m-%d")
            params["start_date"] = try_date
            params["end_date"] = try_date

            try:
                resp = await self._client.get(url, params=params)
                data = resp.json()
                if data.get("code") == 200 and data.get("data"):
                    if i > 0:
                        logger.info(f"数据回退: {start_date} 无数据，使用 {try_date}")
                    return data, try_date
            except Exception:
                continue

        return None, start_date

    async def execute(self, tool_name: str, arguments: dict) -> dict:
        """执行工具调用"""
        try:
            if tool_name == "get_market_overview":
                return await self._get_market_overview(arguments)
            elif tool_name == "get_sector_ranking":
                return await self._get_sector_ranking(arguments)
            elif tool_name == "analyze_sector":
                return await self._analyze_sector(arguments)
            elif tool_name == "get_today_signals":
                return await self._get_today_signals(arguments)
            elif tool_name == "get_north_bound":
                return await self._get_north_bound(arguments)
            elif tool_name == "get_sector_history":
                return await self._get_sector_history(arguments)
            elif tool_name == "run_backtest":
                return await self._run_backtest(arguments)
            else:
                return {"error": f"未知工具: {tool_name}"}
        except Exception as e:
            logger.error(f"工具 {tool_name} 执行失败: {e}")
            return {"error": str(e)}

    async def _get_market_overview(self, args: dict) -> dict:
        date = args.get("date") or _get_latest_trading_day()
        try:
            data, actual_date = await self._query_with_fallback(
                f"{self.data_collector_url}/query/all-sectors",
                {"start_date": date, "end_date": date},
            )
            if data and data.get("data"):
                sectors = data["data"]
                up = sum(1 for s in sectors if s.get("index_change_pct", 0) > 0)
                down = sum(1 for s in sectors if s.get("index_change_pct", 0) < 0)
                avg = sum(s.get("index_change_pct", 0) for s in sectors) / max(len(sectors), 1)
                total_inflow = sum(s.get("main_net_inflow", 0) for s in sectors) / 1e8
                result = {
                    "date": actual_date,
                    "total_sectors": len(sectors),
                    "up_count": up,
                    "down_count": down,
                    "avg_change_pct": round(avg, 2),
                    "total_main_inflow_yi": round(total_inflow, 2),
                    "sentiment": "强势" if avg > 1 else "偏强" if avg > 0 else "偏弱" if avg > -1 else "弱势"
                }
                if actual_date != date:
                    result["note"] = f"{date} 无数据，已回退到最近交易日 {actual_date}"
                return result
            return {"error": f"近 {MAX_FALLBACK_DAYS} 天均无数据"}
        except Exception as e:
            return {"error": str(e)}

    async def _get_sector_ranking(self, args: dict) -> dict:
        date = args.get("date") or _get_latest_trading_day()
        metric = args.get("metric", "change")
        limit = args.get("limit", 10)
        try:
            data, actual_date = await self._query_with_fallback(
                f"{self.data_collector_url}/query/all-sectors",
                {"start_date": date, "end_date": date},
            )
            if data and data.get("data"):
                sectors = data["data"]
                if metric == "inflow":
                    sectors.sort(key=lambda x: x.get("main_net_inflow", 0), reverse=True)
                else:
                    sectors.sort(key=lambda x: x.get("index_change_pct", 0), reverse=True)
                result = {
                    "date": actual_date,
                    "ranking": [
                        {
                            "rank": i + 1,
                            "sector_name": s.get("sector_name", ""),
                            "change_pct": round(s.get("index_change_pct", 0), 2),
                            "main_inflow_yi": round(s.get("main_net_inflow", 0) / 1e8, 2),
                            "north_inflow_yi": round(s.get("north_net_inflow", 0) / 1e8, 2),
                        }
                        for i, s in enumerate(sectors[:limit])
                    ]
                }
                if actual_date != date:
                    result["note"] = f"{date} 无数据，已回退到最近交易日 {actual_date}"
                return result
            return {"error": f"近 {MAX_FALLBACK_DAYS} 天均无数据"}
        except Exception as e:
            return {"error": str(e)}

    async def _analyze_sector(self, args: dict) -> dict:
        sector_code = args.get("sector_code", "")
        date = args.get("date") or _get_latest_trading_day()
        try:
            data, actual_date = await self._query_with_fallback(
                f"{self.data_collector_url}/query/sector-data",
                {"sector_code": sector_code, "start_date": date, "end_date": date},
            )
            if data and data.get("data"):
                sector = data["data"][0] if data["data"] else {}
                result = {
                    "sector_code": sector_code,
                    "sector_name": sector.get("sector_name", ""),
                    "date": actual_date,
                    "change_pct": round(sector.get("index_change_pct", 0), 2),
                    "main_inflow_yi": round(sector.get("main_net_inflow", 0) / 1e8, 2),
                    "north_inflow_yi": round(sector.get("north_net_inflow", 0) / 1e8, 2),
                    "turnover_yi": round(sector.get("turnover", 0) / 1e8, 2),
                    "high": sector.get("index_high", 0),
                    "low": sector.get("index_low", 0),
                    "close": sector.get("index_close", 0),
                }
                if actual_date != date:
                    result["note"] = f"{date} 无数据，已回退到最近交易日 {actual_date}"
                return result
            return {"error": f"近 {MAX_FALLBACK_DAYS} 天均无数据"}
        except Exception as e:
            return {"error": str(e)}

    async def _get_today_signals(self, args: dict) -> dict:
        strategy_type = args.get("strategy_type", "MODERATE")
        try:
            resp = await self._client.get(f"{self.signal_url}/signals/today", params={"strategy_type": strategy_type})
            data = resp.json()
            if data.get("code") == 200:
                return {"strategy_type": strategy_type, "signals": data.get("data", [])}
            return {"error": "获取信号失败"}
        except Exception as e:
            return {"error": str(e)}

    async def _get_north_bound(self, args: dict) -> dict:
        date = args.get("date") or _get_latest_trading_day()
        try:
            data, actual_date = await self._query_with_fallback(
                f"{self.data_collector_url}/query/all-sectors",
                {"start_date": date, "end_date": date},
            )
            if data and data.get("data"):
                sectors = data["data"]
                total = sum(s.get("north_net_inflow", 0) for s in sectors) / 1e8
                top_in = sorted(sectors, key=lambda x: x.get("north_net_inflow", 0), reverse=True)[:5]
                top_out = sorted(sectors, key=lambda x: x.get("north_net_inflow", 0))[:5]
                result = {
                    "date": actual_date,
                    "total_north_inflow_yi": round(total, 2),
                    "top_inflow": [{"name": s["sector_name"], "yi": round(s.get("north_net_inflow", 0) / 1e8, 2)} for s in top_in],
                    "top_outflow": [{"name": s["sector_name"], "yi": round(s.get("north_net_inflow", 0) / 1e8, 2)} for s in top_out],
                }
                if actual_date != date:
                    result["note"] = f"{date} 无数据，已回退到最近交易日 {actual_date}"
                return result
            return {"error": f"近 {MAX_FALLBACK_DAYS} 天均无数据"}
        except Exception as e:
            return {"error": str(e)}

    async def _get_sector_history(self, args: dict) -> dict:
        sector_code = args.get("sector_code", "")
        days = args.get("days", 20)
        try:
            end = _get_latest_trading_day()
            start = (datetime.now() - timedelta(days=days * 2)).strftime("%Y-%m-%d")
            resp = await self._client.get(f"{self.data_collector_url}/query/sector-data", params={"sector_code": sector_code, "start_date": start, "end_date": end})
            data = resp.json()
            if data.get("code") == 200 and data.get("data"):
                records = data["data"][-days:]
                return {
                    "sector_code": sector_code,
                    "records": [
                        {
                            "date": r.get("date", ""),
                            "close": r.get("index_close", 0),
                            "change_pct": round(r.get("index_change_pct", 0), 2),
                            "main_inflow_yi": round(r.get("main_net_inflow", 0) / 1e8, 2),
                        }
                        for r in records
                    ]
                }
            return {"error": "无历史数据"}
        except Exception as e:
            return {"error": str(e)}

    async def _run_backtest(self, args: dict) -> dict:
        strategy_type = args.get("strategy_type", "MODERATE")
        start_date = args.get("start_date", "")
        end_date = args.get("end_date", "")
        try:
            resp = await self._client.post(f"{self.strategy_url}/backtest", json={
                "strategy_type": strategy_type,
                "start_date": start_date,
                "end_date": end_date,
                "initial_capital": 1000000,
            })
            data = resp.json()
            if data.get("code") == 200:
                r = data["data"]
                return {
                    "strategy_type": strategy_type,
                    "total_return": r.get("total_return"),
                    "annual_return": r.get("annual_return"),
                    "max_drawdown": r.get("max_drawdown"),
                    "sharpe_ratio": r.get("sharpe_ratio"),
                    "win_rate": r.get("win_rate"),
                    "trade_count": r.get("trade_count_actual"),
                }
            return {"error": "回测失败"}
        except Exception as e:
            return {"error": str(e)}
