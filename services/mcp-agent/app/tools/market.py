"""MCP 工具 - 市场分析"""
import httpx
from datetime import datetime
from loguru import logger


class MarketTools:
    """市场分析工具集"""

    def __init__(self, strategy_url: str, data_collector_url: str):
        self.strategy_url = strategy_url.rstrip("/")
        self.data_collector_url = data_collector_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=30)

    async def analyze_sector_flow(self, sector_code: str, date: str = None) -> dict:
        """分析板块资金流向"""
        date = date or datetime.now().strftime("%Y-%m-%d")
        try:
            resp = await self._client.get(
                f"{self.data_collector_url}/query/sector-data",
                params={"sector_code": sector_code, "start_date": date, "end_date": date},
            )
            data = resp.json()
            if data.get("code") == 200 and data.get("data"):
                sector = data["data"][0] if data["data"] else {}
                return {
                    "sector_code": sector_code,
                    "sector_name": sector.get("sector_name", ""),
                    "date": date,
                    "main_net_inflow_yi": round(sector.get("main_net_inflow", 0) / 1e8, 2),
                    "north_net_inflow_yi": round(sector.get("north_net_inflow", 0) / 1e8, 2),
                    "index_change_pct": round(sector.get("index_change_pct", 0), 2),
                    "turnover_yi": round(sector.get("turnover", 0) / 1e8, 2),
                }
            return {"error": f"{date} 无数据"}
        except Exception as e:
            logger.error(f"分析板块资金流向失败: {e}")
            return {"error": str(e)}

    async def get_market_overview(self, date: str = None) -> dict:
        """获取市场概览"""
        date = date or datetime.now().strftime("%Y-%m-%d")
        try:
            resp = await self._client.get(
                f"{self.data_collector_url}/query/all-sectors",
                params={"start_date": date, "end_date": date},
            )
            data = resp.json()
            if data.get("code") == 200 and data.get("data"):
                sectors = data["data"]
                up_count = sum(1 for s in sectors if s.get("index_change_pct", 0) > 0)
                down_count = sum(1 for s in sectors if s.get("index_change_pct", 0) < 0)
                avg_change = sum(s.get("index_change_pct", 0) for s in sectors) / max(len(sectors), 1)
                total_inflow = sum(s.get("main_net_inflow", 0) for s in sectors) / 1e8
                return {
                    "date": date,
                    "total_sectors": len(sectors),
                    "up_count": up_count,
                    "down_count": down_count,
                    "avg_change_pct": round(avg_change, 2),
                    "total_main_inflow_yi": round(total_inflow, 2),
                    "market_sentiment": "强势" if avg_change > 1 else "偏强" if avg_change > 0 else "偏弱" if avg_change > -1 else "弱势",
                }
            return {"error": f"{date} 无数据"}
        except Exception as e:
            logger.error(f"获取市场概览失败: {e}")
            return {"error": str(e)}

    async def get_sector_ranking(self, date: str = None, metric: str = "change", limit: int = 10) -> dict:
        """板块涨跌排行"""
        date = date or datetime.now().strftime("%Y-%m-%d")
        try:
            resp = await self._client.get(
                f"{self.data_collector_url}/query/all-sectors",
                params={"start_date": date, "end_date": date},
            )
            data = resp.json()
            if data.get("code") == 200 and data.get("data"):
                sectors = data["data"]
                if metric == "inflow":
                    sectors.sort(key=lambda x: x.get("main_net_inflow", 0), reverse=True)
                else:
                    sectors.sort(key=lambda x: x.get("index_change_pct", 0), reverse=True)
                ranking = []
                for s in sectors[:limit]:
                    ranking.append({
                        "sector_name": s.get("sector_name", ""),
                        "change_pct": round(s.get("index_change_pct", 0), 2),
                        "main_inflow_yi": round(s.get("main_net_inflow", 0) / 1e8, 2),
                    })
                return {"date": date, "metric": metric, "ranking": ranking}
            return {"error": f"{date} 无数据"}
        except Exception as e:
            logger.error(f"获取板块排行失败: {e}")
            return {"error": str(e)}

    async def get_north_bound(self, date: str = None) -> dict:
        """北向资金分析"""
        date = date or datetime.now().strftime("%Y-%m-%d")
        try:
            resp = await self._client.get(
                f"{self.data_collector_url}/query/all-sectors",
                params={"start_date": date, "end_date": date},
            )
            data = resp.json()
            if data.get("code") == 200 and data.get("data"):
                sectors = data["data"]
                total_north = sum(s.get("north_net_inflow", 0) for s in sectors) / 1e8
                top_inflow = sorted(sectors, key=lambda x: x.get("north_net_inflow", 0), reverse=True)[:5]
                top_outflow = sorted(sectors, key=lambda x: x.get("north_net_inflow", 0))[:5]
                return {
                    "date": date,
                    "total_north_inflow_yi": round(total_north, 2),
                    "top_inflow": [{"name": s["sector_name"], "yi": round(s.get("north_net_inflow", 0) / 1e8, 2)} for s in top_inflow],
                    "top_outflow": [{"name": s["sector_name"], "yi": round(s.get("north_net_inflow", 0) / 1e8, 2)} for s in top_outflow],
                }
            return {"error": f"{date} 无数据"}
        except Exception as e:
            logger.error(f"获取北向资金失败: {e}")
            return {"error": str(e)}

    async def close(self):
        await self._client.aclose()
