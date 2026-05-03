"""数据查询员 Agent"""
from typing import Optional
from .base import BaseAgent, AgentResponse
from ..tools.data import DataTools


class DataQueryAgent(BaseAgent):
    """数据查询员 - 查询板块数据、历史行情、信号记录"""

    name = "data_query"
    description = "查询板块数据、历史行情、信号记录"
    system_prompt = """你是一个数据查询助手。你的职责是查询板块数据、历史行情、信号记录等。

使用要点:
1. 数据格式说明（涨跌幅为百分比，资金流为元/亿）
2. 日期格式为 YYYY-MM-DD
3. 板块代码格式为 SW801xxx 或 THS801xxx

请用清晰的格式展示数据，便于用户理解。"""

    def __init__(self, data_tools: DataTools):
        self.tools = data_tools

    async def run(self, user_message: str, context: dict = None) -> AgentResponse:
        tools_called = []
        results = []

        if "数据" in user_message or "行情" in user_message or "历史" in user_message:
            sector_code = self._extract_sector_code(user_message)
            if sector_code:
                result = await self.tools.query_sector_data(sector_code)
                tools_called.append("query_sector_data")
                results.append(f"板块数据: {result}")

        if "交易日" in user_message or "日历" in user_message:
            result = await self.tools.get_trade_dates()
            tools_called.append("get_trade_dates")
            results.append(f"交易日历: {result}")

        if "可用" in user_message or "范围" in user_message:
            result = await self.tools.get_data_availability()
            tools_called.append("get_data_availability")
            results.append(f"数据范围: {result}")

        if not results:
            result = await self.tools.get_data_availability()
            tools_called.append("get_data_availability")
            results.append(f"数据范围: {result}")

        return AgentResponse(
            content="\n\n".join(results),
            agent_name=self.name,
            tools_called=tools_called,
        )

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
