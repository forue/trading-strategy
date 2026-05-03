"""市场分析师 Agent"""
from typing import Optional
from .base import BaseAgent, AgentResponse
from ..tools.market import MarketTools


class MarketAnalystAgent(BaseAgent):
    """市场分析师 - 分析板块资金流向、市场情绪、板块轮动趋势"""

    name = "market_analyst"
    description = "分析板块资金流向、市场情绪、板块轮动趋势"
    system_prompt = """你是一个专业的A股市场分析师。你的职责是分析板块资金流向、市场情绪、板块轮动趋势。

分析要点:
1. 主力资金净流入/流出趋势
2. 北向资金偏好变化
3. 板块轮动节奏和热点切换
4. 市场情绪指标（涨跌比、量比）

请用简洁专业的语言分析，给出明确的结论和建议。"""

    def __init__(self, market_tools: MarketTools):
        self.tools = market_tools

    async def run(self, user_message: str, context: dict = None) -> AgentResponse:
        tools_called = []
        results = []

        # 根据用户意图调用工具
        if "资金" in user_message or "流入" in user_message:
            # 提取板块代码（简化处理）
            sector_code = self._extract_sector_code(user_message)
            if sector_code:
                result = await self.tools.analyze_sector_flow(sector_code)
                tools_called.append("analyze_sector_flow")
                results.append(f"板块资金流向: {result}")

        if "市场" in user_message or "概览" in user_message or "整体" in user_message:
            result = await self.tools.get_market_overview()
            tools_called.append("get_market_overview")
            results.append(f"市场概览: {result}")

        if "排行" in user_message or "涨跌" in user_message or "排名" in user_message:
            result = await self.tools.get_sector_ranking()
            tools_called.append("get_sector_ranking")
            results.append(f"板块排行: {result}")

        if "北向" in user_message or "外资" in user_message:
            result = await self.tools.get_north_bound()
            tools_called.append("get_north_bound")
            results.append(f"北向资金: {result}")

        # 如果没有匹配到特定工具，获取市场概览
        if not results:
            result = await self.tools.get_market_overview()
            tools_called.append("get_market_overview")
            results.append(f"市场概览: {result}")

        return AgentResponse(
            content="\n\n".join(results),
            agent_name=self.name,
            tools_called=tools_called,
        )

    def _extract_sector_code(self, text: str) -> Optional[str]:
        """从文本中提取板块代码"""
        import re
        match = re.search(r'(SW|THS)\d{6}', text)
        if match:
            return match.group()
        # 尝试匹配中文板块名
        sector_map = {
            "银行": "SW801780", "证券": "SW801790", "保险": "SW801790",
            "医药": "SW801150", "电子": "SW801080", "计算机": "SW801750",
            "新能源": "SW801730", "汽车": "SW801880", "房地产": "SW801180",
        }
        for name, code in sector_map.items():
            if name in text:
                return code
        return None
