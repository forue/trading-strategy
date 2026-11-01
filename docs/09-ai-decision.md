# AI 决策服务设计文档

> 版本: v1.3 | 创建日期: 2026-05-01 | 更新日期: 2026-10-22 | 更新内容: 信号解读预算放开至 4000 并支持截断重试（见 3.3）；新增外部数据源容错与 push2 熔断（见 3.5）；市场上下文构建增加重试与显式降级标记（见 3.6）；Ollama 能力探测改用 /api/show、错误带上响应体、工具消息格式归一化（见 8.4）

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

### 3.7 ReAct 取数策略：去重、上下文预算与成本控制 (2026-10-22)

**去重范围**：`run()` 内的 `tool_call_results` 是**单次回答**的局部字典，不跨轮次、不跨对话，
不同对话之间互不影响。命中重复（工具名 + 参数相同）时不再执行工具，直接复用首次的**真实结果**：
早期实现回填的是 `{"info": "相同调用已跳过..."}` 占位文案，一旦首次结果被上下文截断掉，
模型就完全拿不到数据，只能瞎编或回答"无数据"。

> 同一条 assistant 消息里的重复 tool_calls 仍会各自执行一次（结果相同，仅多花时间），
> 因为每个 tool_call 都必须有对应的 tool 消息，合并需要额外记账，暂不做。

**提示词（深度 ↔ 成本的平衡点）**：`AGENT_SYSTEM_PROMPT` 给出"各问题类型的取数清单"
（核心必取 + 按需补 1-3 项），要求**第 1 轮并行取全（4-6 个）**、**最多 4 轮**（2026-10-24 由 2 轮放宽，
详见 3.10），并要求正文
控制在 1200-2000 字、**至少 2 条"交叉验证/背离"结论**、建议写明触发条件、缺项用"数据说明"声明。
此前只写了"市场分析 → 三个数据源"，本地 9B 模型照做即收工（5 个工具、2 轮、正文 2832 字符、无交叉验证）；
改后同题可得 3 条背离结论 + 触发条件 + 缺项声明（实测正文 2056 字符、tokens 约 28k）。

**取数轮次硬约束**：本地小模型不会主动收敛（实测跑到 12 次工具调用触顶才作答，
每轮都要重发全量历史，是 token 与耗时的主要来源）。因此：

- `MAX_TOOL_CALLS` 保持 30（兜底，不用来控成本）；
- `MAX_TOOL_ROUNDS = 4`（2026-10-24 由 2 放宽，`TOTAL_TIMEOUT` 同步 240→360s）：超出后**不再执行工具**，
  为每个 tool_call 回填"取数轮次已用完"，
  并置 `force_final`——下一轮不带工具定义 + 注入"禁止再调用工具"的系统提示；若仍请求工具且有正文则直接输出正文；
- 每轮的迭代提示里带上"已取数工具清单"，明确换参数重复调用同一工具也会重复占用上下文。

**工具输出瘦身**：`MCPToolExecutor._PARAM_MAX` 在 `execute()` 入口钳制条数类参数
（`limit ≤ 15`、`top_n ≤ 10`，`days` 等时间窗口参数不动，避免改变分析语义），
工具 schema 里同步标注上限，实测单轮 7 个工具结果约 8200 字符 / 4000 tokens。

**分组截断（2026-10-22 bug 修复）**：`_truncate_messages` 原先逐条从新到旧保留，
预算不足时会先丢掉最老的 `assistant(tool_calls)`，于是它的所有 tool 结果都被"孤儿清理"删光——
模型**一条数据都看不到**，只能重复调用工具直到超时（实测出现"发送消息数量: 2"且单次请求 >600s）。
现在改为**整组截断**：`assistant(tool_calls)` 与其 tool 结果同进同退；单组仍放不下时保留
assistant 与尽量新的 tool 结果，并**同步裁剪 assistant 的 tool_calls**（否则 API 会因
"tool_call 缺少响应"报 400）。修复后同题：6 个工具、2 轮、tokens 15987、耗时 288s。

**上下文预算**：`_get_context_budget()` 按模型名推断，未命中已知名单的模型一律取 4000；
而系统提示词本身就占约 2540 tokens，中间只剩 ~930 tokens，约等于**只能留住 1 条工具结果**，
后续迭代的查询结果会被 `_truncate_messages` 丢弃。现在 Ollama 客户端从 `/api/show` 读取
`num_ctx`（如 `qw3.5-opus:latest` = 16384），取一半作为预算（8192），云端模型仍走模型名推断。

### 3.8 交易日历缓存时序 bug：首轮取数锚定到前一交易日 (2026-10-24)

**现象**：10-24 的远程模型分析把 `get_market_overview` / `get_market_breadth` /
`get_fund_flow_distribution` 全部标成"数据日 2026-10-22"（且无回退 note），而同一回答里
`get_sector_ranking` 用的却是 10-23，导致正文出现"个股 80% 上涨 vs 板块 88/90 下跌"的
自相矛盾结论，置信度被模型从 7 下调到 6。

**根因**：`_get_latest_trading_day()` 依赖模块级缓存 `_trade_dates_cache`，而缓存只在
`_query_with_fallback()` 内部（`_ensure_trade_dates`）刷新，**刷新发生在各工具解析日期之后**：

1. 进程内缓存由 10-22 03:03 那次请求建立，`/trade-dates` 只返回 `d <= today` 的日期，
   所以列表最大值恒为 `20261022`；
2. 10-24 12:24 新请求进来，5 个工具先各自 `_sanitize_date(None)` → 命中 10-22 的陈旧缓存
   → `date = 2026-10-22`，并把该日期作为显式 `start_date` 传给 `_query_with_fallback`；
3. 显式日期在合法范围内（非未来、非 60 天前），不再走 `_get_latest_trading_day()`，
   数据也确实存在（10-22 有 90 条），于是 `actual_date == date`，**不会写 note**；
4. 缓存直到 12:24:28 才被刷新（日志中同一毫秒两条"日历已刷新"，说明并发重复拉取），
   此时迭代 2 的 `get_sector_ranking` 才拿到 10-23。

**修复**（`tools.py`）：

- `MCPToolExecutor.execute()` 在分发 handler **之前** `await self._ensure_trade_dates()`，
  保证日期解析看到的是当天刷新过的日历；
- `_refresh_trade_dates_cache` 加 `asyncio.Lock` 并二次校验，消除首轮并发重复请求；
- 顺手删掉 `_get_market_overview` 里重复的 `partial_failures.append("板块数据")`。

**验证**：在容器内注入陈旧缓存（列表末尾 `20261022`、`cache_date=2026-10-22`，即故障时状态），
三个工具返回 `date=2026-10-23`，overview 内 `sectors: 84/90 上涨、avg +1.63%、主力 +987.38 亿`
与 `breadth: 80.4% 上涨` 同日一致，矛盾消失。InfluxDB 侧 10-19~10-23 每日均 90 条，数据未丢。

### 3.9 北向资金与板块技术/估值数据的可得性边界 (2026-10-24)

**北向资金：源头就没有数据，工具却伪造 0**。沪深港通自 2024-08-19 起停止披露北向成交净买额，
`scheduler.job_collect_north_bound` 已从调度器移除（保留实现待数据源恢复），
因此 `sector_capital_flow.north_net_inflow` 从不写入（Influx 实测该 field 0 条），
`north_bound_flow` 仅存 9 月历史值且全为 0。旧实现的后果：

- `get_north_bound` 无条件 `sum(s.get("north_net_inflow", 0))` → 返回 `total=0.0` 和两张全 0 榜单，
  模型看到的是"北向净流入 0"而不是"无数据"，只能自行推断"外资维度不可用"；
- `get_sector_ranking` / `analyze_sector` 输出 `north_inflow_yi: 0`，同样被当成真实零流入。

现在：`get_north_bound` 在字段全缺失时返回 `{"unavailable": true, "error": "...数据源已停止披露..."}`；
排行与单板块分析中该字段缺失时**直接省略**，不输出占位 0。

**技术指标 / 估值：数据齐全，工具没被调用**。实测 `get_technical_indicators('THS881121')`
返回 RSI 29.77（超卖）、MACD 空头、MA5/10/20；`get_sector_valuation('THS881121')`
返回 PE 59.04、PB 6.51、pe_percentile 0、pb_percentile 14.2——数据链路正常。缺位来自设计：

- 两者都是**单板块**接口（`required: ["sector_code"]`），必须先 `list_sectors` 取 `THS88xxxx`，
  一次只能算一个板块，覆盖 90 个板块不现实；
- `AGENT_SYSTEM_PROMPT` 的取数清单把二者列在"板块分析/板块对比"行，"市场整体/大盘"行的补充项是
  heatmap / margin / global，因此"今天市场整体情况"这类问题不会触发它们；
- 叠加 `MAX_TOOL_ROUNDS = 2`，实测第 1 轮 5 个市场级工具、第 2 轮只剩 2 个槽位
  （被 `get_trading_dates` + `get_sector_ranking` 占掉），技术面/估值就没有机会被调用。

若需要"超买/超卖程度"这类全市场结论，得新增**聚合扫描**工具（一次算全部板块的 RSI、
偏离 MA20、估值分位，只回极端榜单）。单板块接口无论怎么调都补不上这个洞，此项未实现。

**顺带修复**：`get_technical_indicators` 的 `latest_date` 之前恒为空串——`/query/sector-data`
只返回 `_time` 没有 `date` 字段，已改为 `date or _time` 兜底。

> 另注意 `pe_percentile = 0.0` 会被 `_valuation_level()` 判成"极度低估"（半导体 PE 59x / PB 6.5x
> 显然不便宜）。百分位是采集侧按固定窗口算好落库的，短期 PE 快速回落就会被算成 60 日最低，
> 该标签只能当"相对自身历史"读，不能当绝对估值结论。

### 3.10 跨市场/情绪维度补全与轮次上限放宽 (2026-10-24)

原工具集缺四类信息：商品与汇率（外部冲击、输入型通胀、外资情绪）、股指期货基差（机构预期）、
利率曲线结构（只有中美利差裸序列）、情绪与资金质量（只有主力净额一个口径）。本轮补齐 6 个新工具
并改造 1 个，同时把取数轮次 2 → 4。

| 工具 | 数据源（均已实测） | 输出体积 | 回答什么问题 |
|---|---|---|---|
| `get_overseas_commodity_fx` | 新浪外盘 `hq.sinajs.cn`（hf_CL/hf_OIL/hf_GC/hf_SI/hf_HG/hf_NG/hf_CHA50CFD）+ 央行中间价 | ~760 字符 | 外部冲击、输入型通胀、外资情绪（A50 期货 + 汇率） |
| `get_index_futures_basis` | `ak.futures_main_sina` IF0/IH0/IC0/IM0 + 新浪宽基指数收盘 | ~1010 字符 | 机构预期：贴水收窄/加深、持仓量变化 |
| `get_commodity_futures_trend` | `ak.futures_main_sina` SC0/RB0/I0/CU0 | ~650 字符 | 石化/钢铁/有色周期板块的成本与景气 |
| `get_limit_up_stats` | `ak.stock_zt_pool_em` + `stock_zt_pool_zbgc_em` + `stock_lhb_detail_em` | ~600 字符 | 情绪温度、连板梯队、题材集中度、机构龙虎榜 |
| `get_market_fund_structure` | `ak.stock_market_fund_flow` | ~810 字符 | 超大单(机构)/小单(散户)背离，判断上涨质量 |
| `get_full_market_valuation` | `ak.stock_a_ttm_lyr` + `stock_index_pe_lg`(沪深300/中证500) | ~390 字符 | 市场整体估值位置（与板块级估值互补） |
| `get_bond_spread`（改造） | `ak.bond_zh_us_rate` | 30 天裸序列 → **364 字符摘要** | 期限利差、中美利差及变化（bp） |

**取不到、因此没做的**（实测失败，不要重复尝试）：北向/南向（源头停止披露）、
`stock_sector_fund_flow_rank`（push2 域 `RemoteDisconnected`，已有 `all-sectors` 覆盖）、
`hf_DX` 美元指数与 `hf_VIX`（新浪返回空）、南华商品指数（当前 akshare 无此函数）、
ETF 溢价（Influx `etf_quote` 为 0 条）。

**两个实现坑（已修）**：

- 龙虎榜同一只票有多条"解读"行，直接取 top3 会出现重复个股 → 按名称去重取最大净买额；
- 美债收益率序列早期存在缺失，中美利差用固定 20 行做基准会算出 `null` →
  中债变化用真实 20 交易日基准，美债/利差变化改用"最近一个中美都有值的行"，
  并输出 `change_base_date` 说明基准日（实测基准退到 10-22，故不再标注"20日"）。

**轮次放宽的影响**（同题"今天市场整体情况如何"）：放宽后 3 轮 11 个工具、tokens 31,295、耗时 40.8s；
宽松前 2 轮 6 个工具、tokens 15,987。**token 翻倍主要来自新增工具结果本身**，因此：
`MAX_TOOL_CALLS` 仍保持 30，取数清单要求"按需选 1-3 个补充项"，并明确"同一维度二选一"
（heatmap 与 sector_ranking、资金分布与资金结构）。若后续成本敏感，优先收紧取数清单而不是退回 2 轮。

**实测 10-23 数据**（证明链路真实可用）：IF0 基差率 -1.23%（前值 -1.64%，贴水收窄）、
涨停 82/炸板 12（炸板率 12.8%，最高 6 板）、超大单 +81.0 亿 vs 小单 +131.5 亿（散户抬轿）、
全 A 中位 PE 35.28（10 年分位 59.4%）、WTI 103.49(+4.04%)、USD/CNY 中间价 6.718（20 日 -0.59%）。

### 3.11 输出长度限制：本地受限、在线不限 (2026-10-31)

对话回答此前在 `agent.py` 里硬编码 `max_tokens=4000`，中文加 Markdown 表格约 1.5 token/字，
4000 token 只够写 2500 字左右，长复盘会被**从句子中间掐断**（实测同一问题回答停在"说明A股"）。
截断还是静默的：`LLMResponse` 没有 `finish_reason`，日志只打 `tokens_used`。

改法是按部署形态区分，而不是统一给一个大值：

| 部署形态 | 输出预算 | 实现 |
|---|---|---|
| 在线模型（OpenAI 兼容） | **不限制** | `output_budget()` 返回 0，`_build_payload` 在 `max_tokens <= 0` 时**不下发该字段**，由服务端按模型上限决定 |
| 本地模型（Ollama） | 按 `num_ctx` 收敛 | `min(4000, int(num_ctx * 0.4))`，`num_ctx` 未知时回退 4000；再经 `options.num_predict` 下发 |

本地必须留限的原因：输入预算已占 `num_ctx` 的一半（`context_budget()`），小上下文模型（如 4k）
再给 4000 输出会撞上下文窗口，Ollama 会直接停在窗口边界。取 40% 后：4k→1638、8k→3276、
32k→4000（封顶）。

**静默截断已消除**：`LLMResponse` 新增 `finish_reason`（OpenAI 取 `finish_reason`、
Ollama 取 `done_reason`，`length` 归一化），Agent 在命中 `length` 时打印告警。

同题实测：改动前 2545 字且半句截断 → 改动后 4784 字、以"数据说明"正常收尾，耗时 42.7s，无截断告警。

> 两处**未**改动的硬编码预算：`daily_reviewer.py` 3000、`signal_analyzer.py` 4000（解析失败放宽 8000）。
> 它们仍显式下发 `max_tokens`，因为产出的是需要解析的结构化 JSON/分节文本，放开后篇幅不可控。
> 若每日复盘与信号解读也要"在线不限"，需单独评估。
> 另注意提示词里仍写着"正文 1200-2000 字"，这是模型的**自我约束**（不是 API 限制），
> 在线模型放开后实测写到 4784 字即包含表格与建议，如需更长可放宽该句。

### 3.12 push2 集群访问控制：串行 + 限流 + 递增熔断 (2026-10-31)

东方财富 `push2`/`push2his` 集群按 **IP 级封禁**：请求过密时直接断开连接
（`RemoteDisconnected`），首次约 5 分钟恢复，**封禁期内反复重试会延长到 40 分钟以上**。
外部实测文档（a-stock-data#36）给出的触发线为：>5 req/s、并发 ≥10、1min ≥200、5min ≥300。

我们的调用量远低于该阈值，但有两个真实诱因：一是 Agent 一轮并行 5-6 个工具，
其中可同时命中 4 个 push2 维度（宽度/全球指数/资金结构/涨停）；二是原实现在
`RemoteDisconnected` 上仍重试 2-3 次，等于在封禁期持续敲打。

改造后所有 push2 请求统一经过 `_push2_guard()`（`external_data.py`）：

| 机制 | 参数 | 作用 |
|---|---|---|
| 全局串行 | `asyncio.Lock`，并发 1 | 消除并行扇出，单次问询 push2 请求 4-6 次，串行只增 1-2s |
| 最小间隔 | 1.0s + 抖动 0.1-0.5s | 避免节奏规律 |
| 限流即熔断 | 识别 `RateLimitError`/`RemoteDisconnected`/中文"临时限流" | 限流错误**不重试**；非限流错误才退避 1s→2s |
| 递增熔断 | 300 → 900 → 1800s | 连续失败才升级；距上次失败超 30 分钟计数归零；成功一次清零 |
| 排队期复核 | 取锁后再查熔断 | 并发工具不会各自撞一次限流（曾把 300s 叠到 1800s） |
| 缓存摊薄 | 宽度 120→300s、全球市场 300→600s | 全 A 快照是重请求，减少重复拉取 |

熔断期内各降级路径：宽度 → 乐咕涨跌家数、全球指数 → 新浪、资金结构 → 返回
`unavailable` 并在回答中说明；指数主源本就是新浪，不受影响。

**实测（2026-10-31，容器出口 IP 当时已处于限流态）**：改造前同一问题触发 5 次 push2 失败、
3 次重试，24.0s；改造后只 1 次失败即熔断 300s，其余维度直接走备用源，18.2s，
回答数据完整（外盘明确标注 sina 源）。

> push2ex（涨停/炸板池）属独立集群，未纳入本闸门，失败不影响 push2 熔断状态。
> 限流判定兼容两代 akshare：1.20+ 抛 `RateLimitError`（附中文说明），旧版抛
> `ConnectionError(RemoteDisconnected)`。

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

### 8.4 Ollama 本地模型排错 (2026-10-22)

**能力探测**：`OllamaClient` 首次调用时先请求 `/api/show` 读取模型 `capabilities`
（如 `["tools", "thinking", "completion"]`），据此决定是否发送原生 `tools` / `think` 参数；
`/api/show` 不可用时才回退到发送最小请求探测。探测结果按模型名缓存。

**错误定位**：Ollama 的真实原因放在响应体 `error` 字段里，客户端统一抛出
`Ollama HTTP {状态码}: {error}`，不要再只看状态码。

**消息格式**：Ollama 与 OpenAI 的 `tool_calls` 格式不同——Ollama 要求
`function.arguments` 是**对象**，OpenAI 是 **JSON 字符串**，直接透传字符串会被 400 拒绝。
`OllamaClient._build_payload` 发送前统一做 `_normalize_messages` 转换。

**典型故障：所有请求返回 HTTP 400**

```json
{"error":"Field 'repeat_last_n': Value must be between 0 <= value <= 2147483647, but got -1"}
```

这是模型 Modelfile 里的 `PARAMETER repeat_last_n -1` 被新版 Ollama 参数校验拒绝，
与该模型是否支持 tools 无关，会导致**每个** `/api/chat` 请求都失败。修复方式：

```powershell
ollama show <model> --modelfile | ForEach-Object { $_ -replace '^PARAMETER repeat_last_n -1$','PARAMETER repeat_last_n 64' } | Set-Content Modelfile -Encoding utf8
ollama create <model> -f Modelfile
```

已扫描过的本地模型中，`qw3.5-opus:latest` 存在该问题并已重建为 `repeat_last_n 64`。
