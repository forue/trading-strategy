"""MCP 工具 - 数据查询"""
import httpx
from datetime import datetime
from loguru import logger


class DataTools:
    """数据查询工具集"""

    def __init__(self, data_collector_url: str, strategy_url: str):
        self.data_collector_url = data_collector_url.rstrip("/")
        self.strategy_url = strategy_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=30)

    async def query_sector_data(self, sector_code: str, start_date: str = "", end_date: str = "") -> dict:
        """查询板块历史数据"""
        try:
            resp = await self._client.get(
                f"{self.data_collector_url}/query/sector-data",
                params={"sector_code": sector_code, "start_date": start_date, "end_date": end_date},
            )
            data = resp.json()
            if data.get("code") == 200:
                records = data.get("data", [])
                summary = {
                    "total_records": len(records),
                    "date_range": f"{records[0].get('date', '')} ~ {records[-1].get('date', '')}" if records else "",
                    "avg_change_pct": round(sum(r.get("index_change_pct", 0) for r in records) / max(len(records), 1), 2),
                    "total_main_inflow_yi": round(sum(r.get("main_net_inflow", 0) for r in records) / 1e8, 2),
                }
                return {"summary": summary, "records": records[-30:]}  # 最多返回30条
            return {"error": "查询失败"}
        except Exception as e:
            logger.error(f"查询板块数据失败: {e}")
            return {"error": str(e)}

    async def get_trade_dates(self, start_date: str = "", end_date: str = "") -> dict:
        """获取交易日历"""
        try:
            resp = await self._client.get(
                f"{self.data_collector_url}/trade-dates",
                params={"days": 365},
            )
            data = resp.json()
            if data.get("code") == 200:
                dates = data.get("data", [])
                if start_date:
                    dates = [d for d in dates if d >= start_date]
                if end_date:
                    dates = [d for d in dates if d <= end_date]
                return {"total": len(dates), "dates": dates}
            return {"error": "获取交易日历失败"}
        except Exception as e:
            logger.error(f"获取交易日历失败: {e}")
            return {"error": str(e)}

    async def get_data_availability(self) -> dict:
        """数据可用范围"""
        try:
            resp = await self._client.get(f"{self.strategy_url}/data/availability")
            data = resp.json()
            if data.get("code") == 200:
                return data["data"]
            return {"error": "查询失败"}
        except Exception as e:
            logger.error(f"查询数据可用范围失败: {e}")
            return {"error": str(e)}

    async def close(self):
        await self._client.aclose()
