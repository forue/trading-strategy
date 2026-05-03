"""信号解读员 Agent"""
from typing import Optional
from .base import BaseAgent, AgentResponse
from ..tools.signal import SignalTools


class SignalReaderAgent(BaseAgent):
    """信号解读员 - 解读买卖信号、评估信号质量、给出操作建议"""

    name = "signal_reader"
    description = "解读买卖信号、评估信号质量、给出操作建议"
    system_prompt = """你是一个交易信号解读专家。你的职责是解读买卖信号、评估信号质量、给出操作建议。

解读要点:
1. 信号产生的原因（资金、动量、技术指标）
2. 信号的置信度和可靠性
3. 建议的仓位和持有期
4. 风险提示和止损建议

请用通俗易懂的语言解释，让普通投资者也能理解。"""

    def __init__(self, signal_tools: SignalTools):
        self.tools = signal_tools

    async def run(self, user_message: str, context: dict = None) -> AgentResponse:
        tools_called = []
        results = []

        if "今日" in user_message or "今天" in user_message:
            strategy_type = self._extract_strategy_type(user_message)
            result = await self.tools.get_today_signals(strategy_type)
            tools_called.append("get_today_signals")
            results.append(f"今日信号: {result}")

        if "解读" in user_message or "分析" in user_message or "为什么" in user_message:
            sector_code = self._extract_sector_code(user_message)
            if sector_code:
                result = await self.tools.explain_signal(sector_code)
                tools_called.append("explain_signal")
                results.append(f"信号解读: {result}")

        if "历史" in user_message or "过去" in user_message:
            strategy_type = self._extract_strategy_type(user_message)
            result = await self.tools.get_signal_history(strategy_type)
            tools_called.append("get_signal_history")
            results.append(f"信号历史: {result}")

        if not results:
            result = await self.tools.get_today_signals()
            tools_called.append("get_today_signals")
            results.append(f"今日信号: {result}")

        return AgentResponse(
            content="\n\n".join(results),
            agent_name=self.name,
            tools_called=tools_called,
        )

    def _extract_strategy_type(self, text: str) -> str:
        if "激进" in text:
            return "AGGRESSIVE"
        elif "保守" in text:
            return "CONSERVATIVE"
        return "MODERATE"

    def _extract_sector_code(self, text: str) -> Optional[str]:
        import re
        match = re.search(r'(SW|THS)\d{6}', text)
        if match:
            return match.group()
        sector_map = {
            "银行": "SW801780", "证券": "SW801790", "医药": "SW801150",
            "电子": "SW801080", "计算机": "SW801750", "新能源": "SW801730",
        }
        for name, code in sector_map.items():
            if name in text:
                return code
        return None
