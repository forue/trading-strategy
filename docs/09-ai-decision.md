# AI 决策服务设计文档

> 版本: v1.0 | 创建日期: 2026-05-01 | 内容: AI辅助决策系统设计

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
  1. 获取板块近期资金流向 (InfluxDB)
  2. 获取北向资金变化 (Redis)
  3. 获取该板块历史信号 (Redis)
  4. 组装 Prompt
  5. 调用 LLM
  6. 解析响应，提取结构化结果

输出:
  - SignalAnalysis {
      interpretation: str      # 信号解读
      risk_factors: list[str]  # 风险因素
      confidence: float        # 信心度 0-1
      suggestion: str          # 操作建议
    }
```

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

### 5.2 风险检查

```
POST /api/ai/risk-check

Response:
{
  "code": 200,
  "data": {
    "alerts": [
      {
        "alert_type": "concentration",
        "level": "WARNING",
        "title": "仓位集中度过高",
        "description": "银行板块仓位占比45%，超过40%阈值",
        "suggestion": "建议分散至2-3个板块",
        "metrics": {"sector": "银行", "weight": 0.45, "threshold": 0.40}
      }
    ],
    "overall_risk": "MEDIUM"
  }
}
```

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
    "model": "gpt-4o-mini"
  }
}
```

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
信号解读: 7天 (与信号同步)
风险预警: 3天
复盘报告: 30天
对话历史: 24小时
```

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
