# AI 决策服务设计文档

> 版本: v1.3 | 创建日期: 2026-05-01 | 更新日期: 2026-09-23 | 更新内容: 信号解读预算放开至 4000 并支持截断重试（见 3.3）；新增外部数据源容错与 push2 熔断（见 3.5）；市场上下文构建增加重试与显式降级标记（见 3.6）

---

## 一、模块概述

AI 决策服务为轮动策略系统提供智能化辅助决策能力，包括信号解读、风险预警、市场复盘和对话式投研。采用插件化模型适配器架构，支持云端 API（OpenAI/Claude/通义千问）和本地模型（Ollama）无缝切换。

| 属性 | 值 |
|------|-----|
| 服务名 | backend-ai-decision |
| 端口 | 8007 |
| 语言 | Python 3.11 |
| 框架 | FastAPI |
| 依赖 | RabbitMQ(事件驱动) + Redis(缓存) + InfluxDB(数据源) |
| 外部依赖 | OpenAI API / Ollama（可配置） |

---

## 二、技术架构

```
┌──────────────────────────────────────────────────────────────────┐
│                    AI 决策服务 (:8007)                            │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                    FastAPI Application                    │   │
│  │                                                          │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐      │   │
│  │  │ REST API    │  │ RabbitMQ    │  │ Scheduler   │      │   │
│  │  │ 端点        │  │ Consumer    │  │ (APScheduler)│      │   │
│  │  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘      │   │
│  │         │                │                │              │   │
│  │  ┌──────▼────────────────▼────────────────▼──────┐      │   │
│  │  │              AI Service Layer                  │      │   │
│  │  │  ┌──────────────┐  ┌──────────────┐           │      │   │
│  │  │  │ SignalAnalyzer│  │ RiskMonitor  │           │      │   │
│  │  │  │ (信号解读)     │  │ (风险预警)    │           │      │   │
│  │  │  └──────┬───────┘  └──────┬───────┘           │      │   │
│  │  │         │                 │                    │      │   │
│  │  │  ┌──────▼─────────────────▼──────┐            │      │   │
│  │  │  │       Prompt Engine           │            │      │   │
│  │  │  │  (模板管理 + 上下文组装)       │            │      │   │
│  │  │  └──────────────┬────────────────┘            │      │   │
│  │  │                 │                             │      │   │
│  │  │  ┌──────────────▼────────────────┐            │      │   │
│  │  │  │      Model Adapter            │            │      │   │
│  │  │  │  ┌─────────┐  ┌─────────┐    │            │      │   │
│  │  │  │  │ OpenAI  │  │ Ollama  │    │            │      │   │
│  │  │  │  │ Client  │  │ Client  │    │            │      │   │
│  │  │  │  └─────────┘  └─────────┘    │            │      │   │
│  │  │  └───────────────────────────────┘            │      │   │
│  │  └───────────────────────────────────────────────┘      │   │
│  └──────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
         │              │              │              │
    ┌────▼────┐   ┌────▼────┐   ┌────▼────┐   ┌────▼────┐
    │ RabbitMQ│   │  Redis  │   │ InfluxDB│   │ LLM API │
    │  :5672  │   │  :6379  │   │  :8086  │   │ (外部)  │
    └─────────┘   └─────────┘   └─────────┘   └─────────┘
```

---

## 三、核心组件设计

### 3.1 模型适配器 (Model Adapter)

**设计原则**: 策略模式 + 工厂模式，运行时切换模型后端。

```python
from abc import ABC, abstractmethod
from pydantic import BaseModel

class LLMResponse(BaseModel):
    """统一的 LLM 响应格式"""
    content: str           # 生成的文本内容
    model: str             # 使用的模型名称
    tokens_used: int       # 消耗的 token 数
    latency_ms: int        # 响应延迟(毫秒)

class BaseLLMClient(ABC):
    """LLM 客户端基类"""
    
    @abstractmethod
    async def chat(self, messages: list[dict], temperature: float = 0.7) -> LLMResponse:
        """发送对话请求"""
        pass
    
    @abstractmethod
    async def health_check(self) -> bool:
        """检查模型服务是否可用"""
        pass

class OpenAIClient(BaseLLMClient):
    """OpenAI API 客户端 (兼容 Claude/通义千问等 OpenAI 格式 API)"""
    
    def __init__(self, api_key: str, base_url: str, model: str):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self._client = httpx.AsyncClient(timeout=60)

class OllamaClient(BaseLLMClient):
    """Ollama 本地模型客户端"""
    
    def __init__(self, base_url: str, model: str):
        self.base_url = base_url
        self.model = model
        self._client = httpx.AsyncClient(timeout=120)

class ModelAdapterFactory:
    """模型适配器工厂"""
    
    @staticmethod
    def create(config: "ModelConfig") -> BaseLLMClient:
        if config.provider == "openai":
            return OpenAIClient(config.api_key, config.base_url, config.model)
        elif config.provider == "ollama":
            return OllamaClient(config.base_url, config.model)
        raise ValueError(f"Unsupported provider: {config.provider}")
```

### 3.2 提示词引擎 (Prompt Engine)

**设计原则**: 模板化 + 上下文自动组装，支持多场景复用。

```python
class PromptTemplate:
    """提示词模板"""
    
    def __init__(self, name: str, system: str, user_template: str):
        self.name = name
        self.system = system
        self.user_template = user_template
    
    def render(self, **kwargs) -> str:
        """渲染模板"""
        return self.user_template.format(**kwargs)

class PromptEngine:
    """提示词引擎"""
    
    TEMPLATES = {
        "signal_interpretation": PromptTemplate(
            name="信号解读",
            system="你是一个A股量化分析师...",
            user_template="板块: {sector_name}\n方向: {direction}\n..."
        ),
        "risk_alert": PromptTemplate(...),
        "daily_review": PromptTemplate(...),
        "chat": PromptTemplate(...),
    }
```

### 3.3 信号解读器 (Signal Analyzer)

**职责**: 接收策略信号，组装市场上下文，调用 LLM 生成解读。

```
输入:
  - signal: TradeSignal (来自策略引擎)
  - market_context: 从 Redis/InfluxDB 聚合的市场数据

处理:
 1. 取板块近25天行情与资金流（数据采集服务 /query/sector-data）
 2. 取当日全板块涨跌，计算市场宽度与情绪（数据采集服务 /query/all-sectors）
 3. 取该策略近40天历史信号（信号服务 /signals/history），与该板块行情对齐，
    计算"信号后收益/胜率"填入 signal_history_text
 4. 组装 Prompt
 5. 调用 LLM（max_tokens=4000）
 6. 解析响应（先按完整 JSON 解析，失败则按字段正则抽取），提取结构化结果；
    连 interpretation 都提取不到时，提高预算到 8000 重试一次，仍失败才回退原文

输出:
  - SignalAnalysis {
      interpretation: str      # 信号解读
      risk_factors: list[str]  # 风险因素
      confidence: float        # 信心度 0-1
      suggestion: str          # 操作建议
    }
```

**响应容错**：LLM 输出可能因达到 `max_tokens` 而在 JSON 中途截断（历史曾出现
`max_tokens=1000` 时在 `"suggestion"` 字段处被截断）。`_parse_response()` 先尝试
`json.loads`，失败时调用 `_extract_fields()` 用正则逐字段抽取 `interpretation` /
`risk_factors` / `confidence` / `suggestion`，仅在 `interpretation` 也提取不到（正文被从
中间截断）时返回 `None`。

推理模型（如 `deepseek-v4-flash`）的思维链与正文**共享** `max_tokens` 预算
（`usage.completion_tokens_details.reasoning_tokens` 计入 `completion_tokens`），实测思维链可达
1500+ tokens。预算不足时正文 JSON 会被从中间截断，`interpretation` 无法正则匹配，整条解读退化
为原始 JSON 文本（前端展示为乱码）。因此基准预算取 4000，并在解析返回 `None` 时用 8000
重试一次，两次都失败才回退原文（`_raw_analysis()`）。

**数据可用性与提示词约束**：

- **北向净买额**：自 2024-08-19 起交易所停止披露，采集值恒为 0。`MarketContext.north_flow_available`
  为 `False` 时，提示词渲染为"数据不可用（交易所自2024-08-19起停止披露北向资金成交净买额）"
  而非"0亿"，并在 system prompt 中要求不得由数据缺失推断结论——否则 LLM 会把"0"误读为
  "外资缺席/流出"，得出与事实相反的资金面判断。
- **历史信号**：信号缓存 TTL 仅 7 天，`_format_signal_history()` 只按实际可得记录回溯，
  输出包含信号次数、可验证 BUY 样本数、胜率与平均收益，并显式标注样本量，避免 LLM 以
  "无历史信号数据"一笔带过或夸大胜率。
- **板块估值（PE/PB 与分位）**：`MarketContext` 新增 `pe_ttm` / `pb` / `pe_percentile` /
  `pb_percentile`，取自 data-collector 的申万宏源行业口径（口径与回填方式见
  `docs/04-data-collector.md` 3.5）。提示词新增「## 板块估值（申万行业口径）」段落，
  并要求结合估值分位判断是否低估；字段缺失时渲染为"数据不可用"，分位样本不足时
  渲染为"历史样本不足 10 个交易日不可用"，不得据此臆测估值高低。
- **资金持续性 / 标的 / 排名**：`MarketContext` 新增 `avg_flow_5d`（近 5 日主力资金日均净流入）、
  `etf_code` / `etf_name`（建议标的）、`rank` / `total_sectors`（板块当日排名），
  使提示词可结合短期资金持续性与横向相对位置，而非只看单日资金与绝对评分。

### 3.4 风险监控器 (Risk Monitor)

**职责**: 实时监控持仓和市场状态，触发风险预警。

```
监控维度:
  ┌─────────────────┬────────────────────────┬────────────┐
  │ 风险类型         │ 触发条件                │ 预警级别    │
  ├─────────────────┼────────────────────────┼────────────┤
  │ 集中度风险       │ 单板块仓位 > 40%        │ WARNING    │
  │ 回撤预警         │ 当日回撤 > 3%           │ WARNING    │
  │ 止损逼近         │ 回撤 > 止损线 × 80%     │ CRITICAL   │
  │ 市场异动         │ 大盘跌 > 2%             │ WARNING    │
  │ 信号冲突         │ 同板块3日内买卖交替      │ INFO       │
  │ 流动性风险       │ 板块成交额骤降 > 50%     │ WARNING    │
  └─────────────────┴────────────────────────┴────────────┘

输出:
  - RiskAlert {
      alert_type: str        # 预警类型
      level: str             # INFO / WARNING / CRITICAL
      title: str             # 预警标题
      description: str       # 详细描述
      suggestion: str        # 建议操作
      metrics: dict          # 相关指标
    }
```

### 3.5 外部数据源容错 (external_data.py)

Agent 工具（`get_market_overview` / `get_market_breadth` 等）依赖 `external_data.py` 获取行情。
所有外部数据统一遵循「主源 → 备用源 → 过期缓存（标记 `_stale`）→ `{"error": ...}`」四级降级链，
并按维度设置 TTL 缓存（大盘指数 60s、国际指数 300s、涨跌家数 120s）。

| 数据 | 主源 | 备用源 | 说明 |
|------|------|--------|------|
| A股主要指数 | 新浪 `hq.sinajs.cn`（完整行情，含开高低收/成交额） | 东财 `push2`（`ak.stock_zh_index_spot_em`） | 新浪响应约 0.4s，东财被阻断时单次耗时 20s+ |
| 全球指数 | 东财（字段最多，含 DAX/CAC40/KOSPI） | 新浪 `int_*`（仅 6 个主要指数） | |
| 涨跌家数 | 东财全A行情 `ak.stock_zh_a_spot_em`（含涨跌幅分布） | 乐咕乐股 `ak.stock_market_activity_legu`（无分布字段） | |

东方财富 **push2 行情集群**（`push2.eastmoney.com` / `82.push2...` / `push2his...`）在部分网络环境
会被直接重置连接（`RemoteDisconnected`），且 akshare 内部重试叠加退避后单次调用耗时 20s+。
为此设置了 **push2 熔断**：连续失败后 300s 内 `_push2_available()` 返回 `False`，各数据直接走备用源，
避免每次调用都白白等待。任一 push2 调用成功即清除熔断。

> `datacenter-web.eastmoney.com`（估值、国债收益率等）不受影响，可正常访问。

- **大盘指数主源改新浪的原因**：新浪完整行情本身已提供开高低收与成交额，字段不逊于东财，而东财
  在受限网络下几乎不可达，故不再作为首选。
- **全球指数与涨跌家数仍以东财为主源**：它们的备用源在字段完整性上确有损失（缺少
  DAX/CAC40/KOSPI、缺少涨跌幅分布），因此保留东财优先，仅靠熔断避免重复等待。

### 3.6 市场上下文构建与降级 (2026-09-23)

信号解读前需向 data-collector 拉取真实行情（全市场板块 + 各板块近 25 天历史），
构建 `MarketContext` 供提示词使用。下游采集任务本身是长耗时的同步 IO，
因此这一环节同时做了**重试**与**显式降级**两件事。

**重试**：`_get_with_retry()` 对 `/query/all-sectors` 与 `/query/sector-data` 各尝试 3 次
（`timeout=6s`，退避 2s / 4s）。单次超时不代表数据不可得，短暂排队后通常即可恢复。

**降级标记**：`MarketContext.data_available` 默认 `False`，只有真正取到该板块行情时才置 `True`。
取值失败时写入占位上下文，提示词据此把全部数值字段渲染为"数据不可用"：

| 字段 | 正常 | 降级 (`data_available=False`) |
|------|------|------------------------------|
| 涨跌幅 / 主力净流入 / 成交额 | 真实数值 | 数据不可用 |
| 板块平均涨跌幅 | `±x.xx%` | 数据不可用（全市场缺失时传 `None`，不再传 0.0） |
| 市场情绪 | 强势/偏强/中性/偏弱/弱势 | 数据不可用（本次市场数据获取失败） |
| 市场情绪（全市场为空） | — | 未知（全市场板块数据获取失败） |

配套约定：

- 提示词新增规则 7：当"板块近期表现"整段均为"数据不可用"时，须在风险因素中说明该局限，
  信心度不得高于 0.4，且不得据此给出方向性判断。
- 异常日志统一使用 `type(e).__name__: {str(e) or '无附加信息'}`。`httpx` 异步客户端超时抛出的
  `ReadTimeout` / `ConnectTimeout` 其 `str()` 为空，仅打印 `{e}` 会得到一条没有任何信息的日志
  （2026-09-22 故障即因此难以定位）。
- 统计市场情绪前必须先判断全市场数据是否为空；把空数据当成"0 家上涨"会误判为"弱势"。

> 注意 `e or '默认值'` 对异常对象恒为真（`Exception` 未定义 `__bool__`），必须写 `str(e) or ...`。

---

## 四、事件驱动设计

### 4.1 RabbitMQ 事件流

```
Exchange: rotation (topic, durable)

事件订阅:
  ┌─────────────────────┬────────────────────┬──────────────────┐
  │ Routing Key          │ 事件来源            │ AI 服务响应       │
  ├─────────────────────┼────────────────────┼──────────────────┤
  │ signal.generated     │ 策略引擎            │ 信号解读 + 推送   │
  │ data.updated.*       │ 数据采集            │ 风险检查          │
  │ risk.alert           │ AI 服务 (自身发布)   │ 信号通知服务推送  │
  └─────────────────────┴────────────────────┴──────────────────┘

事件发布:
  ┌─────────────────────┬──────────────────────────────────────┐
  │ Routing Key          │ 说明                                  │
  ├─────────────────────┼──────────────────────────────────────┤
  │ ai.signal.analyzed   │ 信号解读完成，通知信号服务广播         │
  │ ai.risk.alert        │ 风险预警触发，通知信号服务推送         │
  │ ai.review.ready      │ 复盘报告生成完成                      │
  └─────────────────────┴──────────────────────────────────────┘
```

### 4.2 消息格式

```json
// signal.generated → AI 服务消费
{
  "event": "signals_generated",
  "strategy_type": "AGGRESSIVE",
  "signal_date": "2026-05-01",
  "signals": [
    {
      "sector_code": "SW801780",
      "sector_name": "银行",
      "direction": "BUY",
      "score": 8.23,
      "position_ratio": 0.3
    }
  ]
}

// ai.signal.analyzed → 信号通知服务消费
{
  "event": "signal_analyzed",
  "strategy_type": "AGGRESSIVE",
  "signal_date": "2026-05-01",
  "analyses": [
    {
      "sector_code": "SW801780",
      "sector_name": "银行",
      "direction": "BUY",
      "interpretation": "银行板块主力资金连续3日净流入...",
      "risk_factors": ["估值偏高", "短期涨幅过大"],
      "confidence": 0.75,
      "suggestion": "仓位不超过30%，设8%止损"
    }
  ]
}
```

---

## 五、REST API 设计

### 5.1 信号解读

```
POST /api/ai/analyze-signal
Content-Type: application/json

Request:
{
  "strategy_type": "AGGRESSIVE",
  "signal_date": "2026-05-01"
}

Response:
{
  "code": 200,
  "data": {
    "analyses": [
      {
        "sector_code": "SW801780",
        "sector_name": "银行",
        "direction": "BUY",
        "interpretation": "银行板块近期表现...",
        "risk_factors": ["..."],
        "confidence": 0.75,
        "suggestion": "..."
      }
    ],
    "model": "gpt-4o-mini",
    "tokens_used": 1250,
    "latency_ms": 2300
  }
}
```

**失败语义**：同日结果缓存 30 天（`ai:analysis:{strategy_type}:{date}`），命中即返回；
信号被重新计算时 AI 服务会先作废该日缓存（见 6.3），避免日历回放展示过期结论。
signal-notification 不可用或返回非 200 时接口返回 **502**，不会退化成"当日无信号"。

### 5.2 风险检查

```
POST /api/ai/risk-check

Request（除 strategy_type 外均可省略，省略时服务端自动补齐）:
{
  "strategy_type": "MODERATE",          // 缺省 MODERATE
  "positions": {"THS881175": 0.14},     // 省略时读取 Redis DB1 的 positions:{strategy_type}
  "total_assets": 1000000,
  "daily_pnl": -1.8,                    // 省略时用持仓板块加权涨跌幅估算
  "max_drawdown": 5.2,
  "market_change": -1.2                 // 省略时取实时上证指数涨跌幅
}

Response:
{
  "code": 200,
  "data": {
    "alerts": [
      {
        "alert_type": "concentration",
        "level": "WARNING",
        "title": "仓位集中度偏高: THS881175",
        "description": "板块 THS881175 仓位占比 45%，超过 35% 预警线",
        "suggestion": "建议适当分散仓位",
        "metrics": {"sector": "THS881175", "weight": 0.45, "threshold": 0.35}
      }
    ],
    "alert_count": 1,
    "overall_risk": "MEDIUM"
  }
}
```

**取值语义**：可选字段用 `None` 表示"未提供"，不能用 `0.0` 当哨兵——
否则平盘（`market_change=0`）或零盈亏会被误判为未提供并被自动值覆盖。
持仓缺省只读取请求 `strategy_type` 对应的键，不再按
AGGRESSIVE→MODERATE→CONSERVATIVE 顺序取第一个非空持仓，
否则请求稳健策略会拿到激进策略的持仓做风险判断。

**阈值**（见 `risk_monitor.py`）：单板块集中度 35%/50%，当日亏损 1.5%/3%，
最大回撤 5%/10%，大盘跌幅 1.0%/2.5%；`overall_risk` 有 CRITICAL 告警时为 HIGH。

### 5.3 每日复盘

```
POST /api/ai/daily-review
Content-Type: application/json

Request:
{
  "date": "2026-05-01"
}

Response:
{
  "code": 200,
  "data": {
    "date": "2026-05-01",
    "market_summary": "今日大盘...",
    "sector_rotation": "板块轮动...",
    "portfolio_review": "持仓表现...",
    "tomorrow_outlook": "明日展望...",
    "model": "deepseek-v4-flash"
  }
}
```

**失败语义**：报告正常缓存 30 天（`ai:review:{date}`）；LLM 调用失败时
`DailyReviewer` 返回 `model=error` 的报告，接口改为返回 502 并且**不写缓存**——
否则偶发故障会被当成正常报告固化 30 天（曾出现 `market_summary` 内容为
`生成失败: 'NoneType' object has no attribute 'chat'` 的假报告被缓存）。

**数据采集**：`DailyReviewDataCollector` 统一通过各微服务 HTTP 接口取数——
大盘指数用 `external_data.get_market_indices()`（外部实时行情），板块表现/成交额用
data-collector `GET /query/all-sectors`，信号用 signal-notification `GET /signals/history`，
持仓用 strategy `GET /positions`；任一来源失败只降级为占位文案，不影响报告生成。
指数为实时行情，仅在复盘日期为当日时填充（历史日期无可用指数源）。
详见 `docs/13-implementation-guide.md` 第 3 项。

### 5.4 对话式投研

```
POST /api/ai/chat
Content-Type: application/json

Request:
{
  "message": "帮我分析一下银行板块最近的走势",
  "conversation_id": "conv_abc123"  // 可选，支持多轮对话
}

Response:
{
  "code": 200,
  "data": {
    "reply": "银行板块近期...",
    "conversation_id": "conv_abc123",
    "model": "gpt-4o-mini"
  }
}
```

### 5.5 模型配置

```
GET /api/ai/config
PUT /api/ai/config

Request:
{
  "provider": "openai",          // openai / ollama
  "api_key": "sk-xxx",           // OpenAI API Key
  "base_url": "https://api.openai.com/v1",  // API 地址
  "model": "gpt-4o-mini",        // 模型名称
  "temperature": 0.7,            // 温度参数
  "max_tokens": 2000             // 最大输出 token
}
```

---

## 六、Redis 缓存策略

### 6.1 Key 设计

```
ai:config                          → 模型配置 JSON
ai:analysis:{strategy_type}:{date} → 信号解读结果列表
ai:alerts:{date}                   → 当日风险预警列表
ai:review:{date}                   → 复盘报告
ai:chat:{conversation_id}          → 对话历史 (list)
```

### 6.2 TTL 策略

```
信号解读: 30天 (代码实现值，便于日历回放)
风险预警: 3天
复盘报告: 30天
对话历史: 24小时
```

### 6.3 解读失效策略

信号每次（重新）生成时，`_handle_signals` 会**先作废该日期的旧解读**，再决定是否生成新解读：

- 有新信号 → 清除旧解读后重新解读
- 无信号（空仓/清仓）→ 仅清除旧解读，不生成新解读
- LLM 未初始化 → 同样清除旧解读，避免残留过期结论

> 背景：信号被重算或改为空仓后，若旧解读仍在，日历/信号详情会继续展示过期的
> 银行、证券等板块分析，且无任何"已清仓"提示，极易误导决策。

---

## 七、实现阶段

| 阶段 | 功能 | 核心组件 | 工作量 |
|------|------|----------|--------|
| P0 | 模型适配器 + 信号解读 | ModelAdapter, PromptEngine, SignalAnalyzer | 2天 |
| P1 | 风险预警 + 前端展示 | RiskMonitor, WebSocket集成 | 2天 |
| P2 | 每日复盘报告 | DailyReviewer, Scheduler集成 | 1天 |
| P3 | 对话式投研助手 | ChatService, 会话管理 | 3天 |

---

## 八、配置管理

### 8.1 环境变量

```env
# AI 模型配置
AI_PROVIDER=openai                    # openai / ollama
AI_API_KEY=sk-xxx                     # OpenAI API Key
AI_BASE_URL=https://api.openai.com/v1 # API 地址
AI_MODEL=gpt-4o-mini                  # 模型名称
AI_TEMPERATURE=0.7                    # 温度参数
AI_MAX_TOKENS=2000                    # 最大输出 token

# Ollama 配置 (当 AI_PROVIDER=ollama 时)
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:7b
```

### 8.2 docker-compose.yml

```yaml
backend-ai-decision:
  build:
    context: ./services
    dockerfile: ai-decision/Dockerfile
  container_name: rotation-ai-decision
  env_file: .env
  ports:
    - "8007:8007"
  environment:
    TZ: Asia/Shanghai
    AI_PROVIDER: ${AI_PROVIDER:-openai}
    AI_API_KEY: ${AI_API_KEY:-}
    AI_BASE_URL: ${AI_BASE_URL:-https://api.openai.com/v1}
    AI_MODEL: ${AI_MODEL:-gpt-4o-mini}
    REDIS_HOST: redis
    REDIS_PORT: 6379
    REDIS_PASSWORD: ${REDIS_PASSWORD}
    RABBITMQ_HOST: rabbitmq
    RABBITMQ_PORT: 5672
    RABBITMQ_USER: ${RABBITMQ_USER:-guest}
    RABBITMQ_PASSWORD: ${RABBITMQ_PASSWORD}
    INFLUXDB_URL: http://influxdb:8086
    INFLUXDB_TOKEN: ${INFLUXDB_TOKEN}
    INFLUXDB_ORG: ${INFLUXDB_ORG:-rotation}
    INFLUXDB_BUCKET: ${INFLUXDB_BUCKET:-market_data}
  depends_on:
    redis:
      condition: service_healthy
    rabbitmq:
      condition: service_healthy
    influxdb:
      condition: service_healthy
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:8007/health"]
    interval: 30s
    timeout: 10s
    retries: 3
```

### 8.3 LLM 提供商凭据解析

提供商凭据（api_key / base_url）统一保存在 Redis `ai:providers`；`ai:config` 里的
`provider` / `api_key` / `base_url` 是设置页不再写入的遗留字段（设置页只写
`temperature` / `max_tokens` / `signal_analysis_*`），其 `provider` 恒为占位值 `openai`。
因此默认 LLM 客户端（对话与复盘使用）按以下顺序解析凭据（`_resolve_default_llm_args`）：

1. 遗留字段 `provider` 对应的 `ai:providers` 凭据；
2. 回退 `signal_analysis_provider` 的凭据与模型（后端唯一由用户选定的提供商）；
3. 回退 `ai:config` 中直接写入的 `api_key`。

非 ollama 的提供商统一走 OpenAI 兼容协议分支。若三步都拿不到凭据，客户端保持未初始化，
`/api/ai/chat` 与 `/api/ai/daily-review` 返回 503 而不是 500。
