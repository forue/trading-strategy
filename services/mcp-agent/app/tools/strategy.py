"""MCP 工具 - 策略分析"""
import httpx
from datetime import datetime
from loguru import logger


class StrategyTools:
    """策略分析工具集"""

    def __init__(self, strategy_url: str):
        self.strategy_url = strategy_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=120)

    async def get_strategy_signals(self, strategy_type: str = "MODERATE", date: str = None) -> dict:
        """获取策略信号"""
        date = date or datetime.now().strftime("%Y-%m-%d")
        try:
            resp = await self._client.get(
                f"{self.strategy_url}/signals/today",
                params={"strategy_type": strategy_type},
            )
            data = resp.json()
            return {"code": data.get("code"), "data": data.get("data", []), "date": date}
        except Exception as e:
            logger.error(f"获取策略信号失败: {e}")
            return {"error": str(e)}

    async def run_backtest(
        self,
        strategy_type: str = "MODERATE",
        start_date: str = "",
        end_date: str = "",
        initial_capital: float = 1000000,
        params: dict = None,
    ) -> dict:
        """运行回测"""
        try:
            body = {
                "strategy_type": strategy_type,
                "start_date": start_date,
                "end_date": end_date,
                "initial_capital": initial_capital,
            }
            if params:
                body["params"] = params
            resp = await self._client.post(f"{self.strategy_url}/backtest", json=body)
            data = resp.json()
            if data.get("code") == 200:
                result = data["data"]
                return {
                    "total_return": result.get("total_return"),
                    "annual_return": result.get("annual_return"),
                    "max_drawdown": result.get("max_drawdown"),
                    "sharpe_ratio": result.get("sharpe_ratio"),
                    "win_rate": result.get("win_rate"),
                    "trade_count": result.get("trade_count_actual"),
                    "trading_days": result.get("trading_days"),
                    "params": result.get("params"),
                }
            return {"error": data.get("message", "回测失败")}
        except Exception as e:
            logger.error(f"运行回测失败: {e}")
            return {"error": str(e)}

    async def get_strategy_configs(self, strategy_type: str = None) -> dict:
        """获取策略配置"""
        try:
            resp = await self._client.get(f"{self.strategy_url}/configs")
            data = resp.json()
            if data.get("code") == 200:
                configs = data["data"]
                if strategy_type:
                    configs = [c for c in configs if c.get("strategy_type") == strategy_type]
                return {"configs": configs}
            return {"error": "获取配置失败"}
        except Exception as e:
            logger.error(f"获取策略配置失败: {e}")
            return {"error": str(e)}
