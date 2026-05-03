"""MCP 工具 - 信号分析"""
import httpx
from datetime import datetime
from loguru import logger


class SignalTools:
    """信号分析工具集"""

    def __init__(self, signal_url: str, strategy_url: str):
        self.signal_url = signal_url.rstrip("/")
        self.strategy_url = strategy_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=30)

    async def get_today_signals(self, strategy_type: str = "MODERATE") -> dict:
        """获取今日信号"""
        try:
            resp = await self._client.get(
                f"{self.signal_url}/signals/today",
                params={"strategy_type": strategy_type},
            )
            data = resp.json()
            return {"code": data.get("code"), "data": data.get("data", [])}
        except Exception as e:
            logger.error(f"获取今日信号失败: {e}")
            return {"error": str(e)}

    async def explain_signal(self, sector_code: str, strategy_type: str = "MODERATE") -> dict:
        """解读信号"""
        try:
            resp = await self._client.post(
                f"{self.strategy_url}/factors/analyze",
                json={"sector_code": sector_code, "strategy_type": strategy_type},
            )
            data = resp.json()
            if data.get("code") == 200:
                return data["data"]
            return {"error": data.get("message", "解读失败")}
        except Exception as e:
            logger.error(f"解读信号失败: {e}")
            return {"error": str(e)}

    async def get_signal_history(
        self, strategy_type: str = "MODERATE", start_date: str = "", end_date: str = ""
    ) -> dict:
        """获取信号历史"""
        try:
            resp = await self._client.get(
                f"{self.signal_url}/signals/history",
                params={
                    "strategy_type": strategy_type,
                    "start_date": start_date,
                    "end_date": end_date,
                },
            )
            data = resp.json()
            return {"code": data.get("code"), "data": data.get("data", [])}
        except Exception as e:
            logger.error(f"获取信号历史失败: {e}")
            return {"error": str(e)}
