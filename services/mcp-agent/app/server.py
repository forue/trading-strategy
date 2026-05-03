"""MCP Server 核心 - 完整 MCP 协议实现"""
import json
from typing import Any
from mcp.server import Server
from mcp.types import Tool, TextContent
from loguru import logger

from .tools.market import MarketTools
from .tools.strategy import StrategyTools
from .tools.signal import SignalTools
from .tools.data import DataTools


class MCPServer:
    """MCP Server - 实现标准 MCP 协议"""

    def __init__(
        self,
        market_tools: MarketTools,
        strategy_tools: StrategyTools,
        signal_tools: SignalTools,
        data_tools: DataTools,
    ):
        self.server = Server("finance-agent")
        self.market_tools = market_tools
        self.strategy_tools = strategy_tools
        self.signal_tools = signal_tools
        self.data_tools = data_tools
        self._setup_handlers()

    def _setup_handlers(self):
        """设置 MCP 协议处理器"""

        @self.server.list_tools()
        async def list_tools() -> list[Tool]:
            return self._get_all_tools()

        @self.server.call_tool()
        async def call_tool(name: str, arguments: dict) -> list[TextContent]:
            result = await self._dispatch_tool(name, arguments)
            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, default=str))]

    def _get_all_tools(self) -> list[Tool]:
        """注册所有 MCP 工具"""
        return [
            # 市场分析工具
            Tool(
                name="analyze_sector_flow",
                description="分析板块资金流向，包括主力净流入、北向资金等",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "sector_code": {"type": "string", "description": "板块代码，如 SW801780"},
                        "date": {"type": "string", "description": "日期 YYYY-MM-DD，默认今天"},
                    },
                    "required": ["sector_code"],
                },
            ),
            Tool(
                name="get_market_overview",
                description="获取市场概览，包括涨跌家数、平均涨跌幅、市场情绪",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "date": {"type": "string", "description": "日期 YYYY-MM-DD，默认今天"},
                    },
                },
            ),
            Tool(
                name="get_sector_ranking",
                description="获取板块涨跌排行",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "date": {"type": "string", "description": "日期"},
                        "metric": {"type": "string", "enum": ["change", "inflow"], "description": "排序指标"},
                        "limit": {"type": "integer", "description": "返回数量，默认10"},
                    },
                },
            ),
            Tool(
                name="get_north_bound",
                description="分析北向资金动向",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "date": {"type": "string", "description": "日期"},
                    },
                },
            ),
            # 策略工具
            Tool(
                name="get_strategy_signals",
                description="获取策略信号",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "strategy_type": {"type": "string", "enum": ["AGGRESSIVE", "MODERATE", "CONSERVATIVE"]},
                        "date": {"type": "string", "description": "日期"},
                    },
                },
            ),
            Tool(
                name="run_backtest",
                description="运行历史回测",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "strategy_type": {"type": "string", "enum": ["AGGRESSIVE", "MODERATE", "CONSERVATIVE"]},
                        "start_date": {"type": "string", "description": "开始日期"},
                        "end_date": {"type": "string", "description": "结束日期"},
                        "initial_capital": {"type": "number", "description": "初始资金"},
                    },
                    "required": ["start_date", "end_date"],
                },
            ),
            Tool(
                name="get_strategy_configs",
                description="获取策略配置",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "strategy_type": {"type": "string", "enum": ["AGGRESSIVE", "MODERATE", "CONSERVATIVE"]},
                    },
                },
            ),
            # 信号工具
            Tool(
                name="get_today_signals",
                description="获取今日交易信号",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "strategy_type": {"type": "string", "enum": ["AGGRESSIVE", "MODERATE", "CONSERVATIVE"]},
                    },
                },
            ),
            Tool(
                name="explain_signal",
                description="解读特定板块的信号",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "sector_code": {"type": "string", "description": "板块代码"},
                        "strategy_type": {"type": "string", "enum": ["AGGRESSIVE", "MODERATE", "CONSERVATIVE"]},
                    },
                    "required": ["sector_code"],
                },
            ),
            Tool(
                name="get_signal_history",
                description="获取信号历史",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "strategy_type": {"type": "string", "enum": ["AGGRESSIVE", "MODERATE", "CONSERVATIVE"]},
                        "start_date": {"type": "string"},
                        "end_date": {"type": "string"},
                    },
                },
            ),
            # 数据查询工具
            Tool(
                name="query_sector_data",
                description="查询板块历史数据",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "sector_code": {"type": "string", "description": "板块代码"},
                        "start_date": {"type": "string"},
                        "end_date": {"type": "string"},
                    },
                    "required": ["sector_code"],
                },
            ),
            Tool(
                name="get_trade_dates",
                description="获取交易日历",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "start_date": {"type": "string"},
                        "end_date": {"type": "string"},
                    },
                },
            ),
            Tool(
                name="get_data_availability",
                description="查询数据可用范围",
                inputSchema={"type": "object", "properties": {}},
            ),
        ]

    async def _dispatch_tool(self, name: str, arguments: dict) -> Any:
        """分发工具调用"""
        try:
            if name == "analyze_sector_flow":
                return await self.market_tools.analyze_sector_flow(**arguments)
            elif name == "get_market_overview":
                return await self.market_tools.get_market_overview(**arguments)
            elif name == "get_sector_ranking":
                return await self.market_tools.get_sector_ranking(**arguments)
            elif name == "get_north_bound":
                return await self.market_tools.get_north_bound(**arguments)
            elif name == "get_strategy_signals":
                return await self.strategy_tools.get_strategy_signals(**arguments)
            elif name == "run_backtest":
                return await self.strategy_tools.run_backtest(**arguments)
            elif name == "get_strategy_configs":
                return await self.strategy_tools.get_strategy_configs(**arguments)
            elif name == "get_today_signals":
                return await self.signal_tools.get_today_signals(**arguments)
            elif name == "explain_signal":
                return await self.signal_tools.explain_signal(**arguments)
            elif name == "get_signal_history":
                return await self.signal_tools.get_signal_history(**arguments)
            elif name == "query_sector_data":
                return await self.data_tools.query_sector_data(**arguments)
            elif name == "get_trade_dates":
                return await self.data_tools.get_trade_dates(**arguments)
            elif name == "get_data_availability":
                return await self.data_tools.get_data_availability()
            else:
                return {"error": f"Unknown tool: {name}"}
        except Exception as e:
            logger.error(f"Tool {name} failed: {e}")
            return {"error": str(e)}
