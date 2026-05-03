"""Agent 路由器 - 根据用户意图选择 Agent"""
from typing import Optional
from .base import BaseAgent, AgentResponse
from .market_analyst import MarketAnalystAgent
from .strategy_advisor import StrategyAdvisorAgent
from .signal_reader import SignalReaderAgent
from .data_query import DataQueryAgent
from ..tools.market import MarketTools
from ..tools.strategy import StrategyTools
from ..tools.signal import SignalTools
from ..tools.data import DataTools


class AgentRouter:
    """Agent 路由器"""

    def __init__(
        self,
        market_tools: MarketTools,
        strategy_tools: StrategyTools,
        signal_tools: SignalTools,
        data_tools: DataTools,
    ):
        self.agents = {
            "market_analyst": MarketAnalystAgent(market_tools),
            "strategy_advisor": StrategyAdvisorAgent(strategy_tools),
            "signal_reader": SignalReaderAgent(signal_tools),
            "data_query": DataQueryAgent(data_tools),
        }

    async def route(self, user_message: str, agent_name: str = None, context: dict = None) -> AgentResponse:
        """路由到对应 Agent"""
        if agent_name and agent_name in self.agents:
            return await self.agents[agent_name].run(user_message, context)

        # 自动判断
        detected = self._detect_agent(user_message)
        return await self.agents[detected].run(user_message, context)

    def _detect_agent(self, message: str) -> str:
        """检测用户意图，选择 Agent"""
        message_lower = message.lower()

        # 信号相关
        signal_keywords = ["信号", "买入", "卖出", "持仓", "调仓", "今日信号", "今天买"]
        if any(kw in message_lower for kw in signal_keywords):
            return "signal_reader"

        # 策略相关
        strategy_keywords = ["回测", "参数", "策略", "优化", "收益", "风险", "止损"]
        if any(kw in message_lower for kw in strategy_keywords):
            return "strategy_advisor"

        # 市场相关
        market_keywords = ["资金", "北向", "板块", "市场", "涨跌", "排行", "流入", "流出"]
        if any(kw in message_lower for kw in market_keywords):
            return "market_analyst"

        # 数据查询
        data_keywords = ["数据", "行情", "历史", "交易日", "日历", "查询"]
        if any(kw in message_lower for kw in data_keywords):
            return "data_query"

        # 默认使用市场分析师
        return "market_analyst"

    def get_agent_info(self) -> list[dict]:
        """获取所有 Agent 信息"""
        return [
            {
                "name": agent.name,
                "description": agent.description,
            }
            for agent in self.agents.values()
        ]
