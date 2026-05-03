# MCP 金融 Agent 服务设计文档

> 版本: v1.0 | 创建日期: 2026-05-02 | 内容: MCP Server + 金融 Agent 架构

---

## 一、模块概述

MCP (Model Context Protocol) 金融 Agent 服务是一个独立微服务，将后端 API 封装为标准化的 MCP 工具，供 AI 模型通过自然语言调用。内置 4 个专业金融 Agent，根据不同语境自动选择工具组合完成任务。

| 属性 | 值 |
|------|-----|
| 服务名 | backend-mcp |
| 端口 | 8008 |
| 语言 | Python 3.11 |
| 框架 | FastAPI + MCP SDK |
| 协议 | MCP (SSE/stdio) |
| 依赖 | Redis + RabbitMQ + InfluxDB |

---

## 二、架构设计

```
┌─────────────────────────────────────────────────────────────────┐
│                      AI 客户端 (前端/第三方)                      │
│                                                                 │
│   用户: "帮我分析银行板块最近走势"                                  │
│         ↓ MCP 协议 (SSE)                                        │
├─────────────────────────────────────────────────────────────────┤
│                    MCP Server (:8008)                            │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                   Agent Router                           │   │
│  │   根据用户意图自动路由到对应 Agent                          │   │
│  └───────────┬──────────┬──────────┬──────────┬─────────────┘   │
│              │          │          │          │                  │
│  ┌───────────▼──┐ ┌─────▼────┐ ┌───▼────┐ ┌──▼──────────┐     │
│  │ 市场分析师   │ │ 策略顾问  │ │信号解读 │ │ 数据查询员  │     │
│  │ MarketAnalyst│ │ Strategy │ │Signal  │ │ DataQuery   │     │
│  │              │ │ Advisor  │ │Reader  │ │             │     │
│  └──────┬───────┘ └────┬─────┘ └───┬────┘ └──────┬──────┘     │
│         │              │           │              │             │
│  ┌──────▼──────────────▼───────────▼──────────────▼──────┐     │
│  │                 MCP Tools Layer                        │     │
│  │                                                       │     │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ │     │
│  │  │分析板块  │ │获取信号  │ │运行回测  │ │查询数据  │ │     │
│  │  │资金流向  │ │今日信号  │ │参数寻优  │ │历史行情  │ │     │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘ │     │
│  └───────────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────────┘
         │              │              │              │
    ┌────▼────┐   ┌────▼────┐   ┌────▼────┐   ┌────▼────┐
    │InfluxDB │   │  Redis  │   │RabbitMQ │   │ LLM API │
    │:8086    │   │  :6379  │   │  :5672  │   │ (外部)  │
    └─────────┘   └─────────┘   └─────────┘   └─────────┘
```

---

## 三、MCP 工具定义

### 3.1 市场分析工具

| 工具名 | 描述 | 参数 |
|--------|------|------|
| `analyze_sector_flow` | 分析板块资金流向 | sector_code, date |
| `get_market_overview` | 获取市场概览 | date |
| `get_sector_ranking` | 板块涨跌排行 | date, metric, limit |
| `get_north_bound` | 北向资金分析 | date |

### 3.2 策略工具

| 工具名 | 描述 | 参数 |
|--------|------|------|
| `get_strategy_signals` | 获取策略信号 | strategy_type, date |
| `run_backtest` | 运行回测 | strategy_type, start_date, end_date, params |
| `optimize_params` | 参数寻优 | strategy_type, start_date, end_date, n_trials |
| `get_strategy_configs` | 获取策略配置 | strategy_type |

### 3.3 信号工具

| 工具名 | 描述 | 参数 |
|--------|------|------|
| `get_today_signals` | 今日信号 | strategy_type |
| `explain_signal` | 解读信号 | sector_code, strategy_type |
| `get_signal_history` | 信号历史 | strategy_type, start_date, end_date |

### 3.4 数据查询工具

| 工具名 | 描述 | 参数 |
|--------|------|------|
| `query_sector_data` | 查询板块数据 | sector_code, start_date, end_date |
| `get_trade_dates` | 获取交易日历 | start_date, end_date |
| `get_data_availability` | 数据可用范围 | - |

---

## 四、Agent 设计

### 4.1 市场分析师 (MarketAnalyst)

```python
MARKET_ANALYST_SYSTEM = """你是一个专业的A股市场分析师。
你的职责是分析板块资金流向、市场情绪、板块轮动趋势。

可用工具:
- analyze_sector_flow: 分析特定板块的资金流向
- get_market_overview: 获取整体市场概览
- get_sector_ranking: 获取板块涨跌排行
- get_north_bound: 分析北向资金动向

分析要点:
1. 主力资金净流入/流出趋势
2. 北向资金偏好变化
3. 板块轮动节奏和热点切换
4. 市场情绪指标（涨跌比、量比）
"""
```

### 4.2 策略顾问 (StrategyAdvisor)

```python
STRATEGY_ADVISOR_SYSTEM = """你是一个量化策略顾问。
你的职责是分析策略表现、推荐参数配置、评估风险收益。

可用工具:
- get_strategy_signals: 获取策略信号
- run_backtest: 运行历史回测
- optimize_params: 参数寻优
- get_strategy_configs: 获取策略配置

分析要点:
1. 策略收益/风险比
2. 参数敏感性分析
3. 不同市场环境下的表现
4. 止损/止盈策略建议
"""
```

### 4.3 信号解读员 (SignalReader)

```python
SIGNAL_READER_SYSTEM = """你是一个交易信号解读专家。
你的职责是解读买卖信号、评估信号质量、给出操作建议。

可用工具:
- get_today_signals: 获取今日信号
- explain_signal: 详细解读特定信号
- get_signal_history: 查询历史信号

解读要点:
1. 信号产生的原因（资金、动量、技术指标）
2. 信号的置信度和可靠性
3. 建议的仓位和持有期
4. 风险提示和止损建议
"""
```

### 4.4 数据查询员 (DataQuery)

```python
DATA_QUERY_SYSTEM = """你是一个数据查询助手。
你的职责是查询板块数据、历史行情、信号记录等。

可用工具:
- query_sector_data: 查询板块历史数据
- get_trade_dates: 获取交易日历
- get_data_availability: 查询数据可用范围

使用要点:
1. 数据格式说明（涨跌幅为百分比，资金流为元）
2. 日期格式为 YYYY-MM-DD
3. 板块代码格式为 SW801xxx 或 THS801xxx
"""
```

---

## 五、MCP 协议实现

### 5.1 传输方式

支持两种传输方式：
- **SSE (Server-Sent Events)**: HTTP 长连接，适合 Web 客户端
- **stdio**: 标准输入输出，适合本地 AI 工具

### 5.2 工具注册

```python
from mcp.server import Server
from mcp.types import Tool, TextContent

server = Server("finance-agent")

@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="analyze_sector_flow",
            description="分析板块资金流向，包括主力净流入、北向资金等",
            inputSchema={
                "type": "object",
                "properties": {
                    "sector_code": {"type": "string", "description": "板块代码"},
                    "date": {"type": "string", "description": "日期 YYYY-MM-DD"},
                },
                "required": ["sector_code"],
            },
        ),
        # ... 其他工具
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "analyze_sector_flow":
        result = await analyze_sector_flow(**arguments)
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]
```

### 5.3 Agent 路由

```python
class AgentRouter:
    """根据用户意图路由到对应 Agent"""
    
    AGENTS = {
        "market_analyst": MarketAnalystAgent,
        "strategy_advisor": StrategyAdvisorAgent,
        "signal_reader": SignalReaderAgent,
        "data_query": DataQueryAgent,
    }
    
    async def route(self, user_message: str) -> str:
        """使用 LLM 判断用户意图，选择 Agent"""
        # 简单关键词匹配 + LLM 分类
        if any(kw in user_message for kw in ["信号", "买入", "卖出"]):
            return "signal_reader"
        elif any(kw in user_message for kw in ["回测", "参数", "策略"]):
            return "strategy_advisor"
        elif any(kw in user_message for kw in ["资金", "北向", "板块"]):
            return "market_analyst"
        else:
            return "data_query"
```

---

## 六、目录结构

```
services/mcp-agent/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI + MCP Server
│   ├── config.py             # 配置
│   ├── server.py             # MCP Server 核心
│   ├── router.py             # Agent 路由
│   ├── tools/                # MCP 工具实现
│   │   ├── __init__.py
│   │   ├── market.py         # 市场分析工具
│   │   ├── strategy.py       # 策略工具
│   │   ├── signal.py         # 信号工具
│   │   └── data.py           # 数据查询工具
│   └── agents/               # Agent 实现
│       ├── __init__.py
│       ├── base.py           # Agent 基类
│       ├── market_analyst.py
│       ├── strategy_advisor.py
│       ├── signal_reader.py
│       └── data_query.py
├── Dockerfile
└── requirements.txt
```

---

## 七、API 设计

### 7.1 MCP SSE 端点

```
GET /mcp/sse
# SSE 连接端点，AI 客户端连接此处

POST /mcp/messages
# MCP 消息端点，处理工具调用
```

### 7.2 Agent 对话端点

```
POST /api/mcp/chat
Content-Type: application/json

Request:
{
  "message": "帮我分析银行板块最近走势",
  "conversation_id": "conv_123",
  "agent": "auto"  // auto / market_analyst / strategy_advisor / signal_reader / data_query
}

Response:
{
  "code": 200,
  "data": {
    "reply": "银行板块近期...",
    "agent_used": "market_analyst",
    "tools_called": ["analyze_sector_flow", "get_sector_ranking"],
    "conversation_id": "conv_123"
  }
}
```

### 7.3 工具列表端点

```
GET /api/mcp/tools

Response:
{
  "code": 200,
  "data": {
    "tools": [
      {
        "name": "analyze_sector_flow",
        "description": "分析板块资金流向",
        "parameters": {...}
      }
    ]
  }
}
```

---

## 八、实现阶段

| 阶段 | 内容 | 工作量 |
|------|------|--------|
| P0 | MCP Server 框架 + 基础工具 | 1天 |
| P1 | 市场分析师 Agent | 1天 |
| P2 | 策略顾问 + 信号解读 Agent | 1天 |
| P3 | 数据查询 Agent + Agent 路由 | 1天 |
| P4 | 前端集成 + SSE 连接 | 1天 |
