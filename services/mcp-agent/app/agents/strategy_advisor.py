"""策略顾问 Agent"""
from .base import BaseAgent, AgentResponse
from ..tools.strategy import StrategyTools


class StrategyAdvisorAgent(BaseAgent):
    """策略顾问 - 分析策略表现、推荐参数配置、评估风险收益"""

    name = "strategy_advisor"
    description = "分析策略表现、推荐参数配置、评估风险收益"
    system_prompt = """你是一个量化策略顾问。你的职责是分析策略表现、推荐参数配置、评估风险收益。

分析要点:
1. 策略收益/风险比
2. 参数敏感性分析
3. 不同市场环境下的表现
4. 止损/止盈策略建议

请基于数据给出客观分析，不要夸大收益。"""

    def __init__(self, strategy_tools: StrategyTools):
        self.tools = strategy_tools

    async def run(self, user_message: str, context: dict = None) -> AgentResponse:
        tools_called = []
        results = []

        if "配置" in user_message or "参数" in user_message:
            result = await self.tools.get_strategy_configs()
            tools_called.append("get_strategy_configs")
            results.append(f"策略配置: {result}")

        if "回测" in user_message or "历史" in user_message:
            # 提取策略类型
            strategy_type = self._extract_strategy_type(user_message)
            result = await self.tools.run_backtest(
                strategy_type=strategy_type,
                start_date="2024-01-01",
                end_date="2026-05-01",
            )
            tools_called.append("run_backtest")
            results.append(f"回测结果: {result}")

        if "信号" in user_message:
            strategy_type = self._extract_strategy_type(user_message)
            result = await self.tools.get_strategy_signals(strategy_type)
            tools_called.append("get_strategy_signals")
            results.append(f"策略信号: {result}")

        if not results:
            result = await self.tools.get_strategy_configs()
            tools_called.append("get_strategy_configs")
            results.append(f"策略配置: {result}")

        return AgentResponse(
            content="\n\n".join(results),
            agent_name=self.name,
            tools_called=tools_called,
        )

    def _extract_strategy_type(self, text: str) -> str:
        """提取策略类型"""
        if "激进" in text:
            return "AGGRESSIVE"
        elif "保守" in text:
            return "CONSERVATIVE"
        return "MODERATE"
