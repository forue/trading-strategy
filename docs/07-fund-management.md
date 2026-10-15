# 资金管理服务文档（设计 + 实现）

> 版本: v2.0 | 更新日期: 2026-09-25
>
> 本文档由原《07-资金管理服务设计文档》(v1.0, 2026-04-18) 与
> 《14-fund-management 交易引擎实施方案》(v1.0, 2026-09-25) 合并而成。
> 两者同属 fund-management 服务（backend-fund）：07 描述「是什么」（架构、
> 数据模型、接口契约），14 描述「怎么落地」（模块拆解、修复记录、架构约束）。
>
> **重要**：实现过程中修正了原设计的资金模型与今日盈亏公式（见 4.1、4.6），
> 旧公式已废弃，一律以本文档为准。

---

## 一、模块概述

资金管理服务负责模拟/实盘的持仓管理、净值计算、收益统计和归因分析。根据策略信号模拟成交（考虑滑点和手续费），生成每日净值曲线。

| 属性 | 值 |
|------|-----|
| 服务名 | backend-fund |
| 端口 | 8005 |
| 语言 | Java 17 |
| 框架 | Spring Boot 3.2 + JPA |
| 存储 | PostgreSQL（主）+ Redis（缓存）+ InfluxDB（行情，经 data-collector） |
| 消息 | RabbitMQ（topic exchange `rotation`，消费 `signal.generated`） |

**职责边界**：只做账务（持仓、成交、净值），不感知数据源——行情价格由外部推送，信号由 RabbitMQ 送达。

---

## 二、技术架构

```
                    scheduler (:8006)  ──HTTP──>  收盘盯市 / 净值重算
                                                        │
  RabbitMQ signal.generated                             ▼
        │                                    ┌──────────────────────┐
        ▼                                    │  FundController      │
  SignalConsumer ──调用──> PositionService ─>│  (:8005 /api/fund)   │
                                │            └──────────┬───────────┘
                                ▼                       │
                        AccountNavService ──────────────┤
                                │                       │
                    ┌───────────┴────────┐              │
                    ▼                    ▼              ▼
            PositionRepository   AccountNavRepository  BankTransferRepository
                    │                    │              │
                    └────────────────────┴──────────────┘
                                         │
                                         ▼
                              PostgreSQL (:5432)
                        positions │ account_nav │ trades │ bank_transfers
                                         
  Redis: fund:summary:{user_id}  ← 概览缓存（TTL 5 分钟）
```

分层职责：

| 层 | 组件 | 职责 |
|----|------|------|
| 接入层 | `FundController` | 仅做参数解析与响应封装，不含业务逻辑 |
| 消费层 | `SignalConsumer` | 监听信号，按 `user_id` 调用开/平仓 |
| 业务层 | `PositionService` | 开仓/平仓、交易成本、资金与市值计算、盯市回写 |
| 业务层 | `AccountNavService` | 净值重算落库、账户概览、Redis 缓存 |
| 数据层 | JPA Repository | 只做持久化，查询下推 DB |

---

## 三、数据模型

### 3.1 Position - 持仓记录

```java
@Entity
@Table(name = "positions")
public class Position {
    private Long id;               // 主键
    private Long userId;           // 用户ID
    private String strategyType;   // 策略类型 (AGGRESSIVE/MODERATE/CONSERVATIVE)
    private String sectorCode;     // 板块代码 (如 SW801780)
    private String sectorName;     // 板块名称 (如 银行)
    private String etfCode;        // 实际交易标的（ETF 代码，如 512800）—— 收盘盯市按此回写价格
    private String direction;      // 方向 (BUY/SELL)
    private BigDecimal quantity;   // 持仓数量（100 的整数倍）
    private BigDecimal avgPrice;   // 平均成本价
    private BigDecimal currentPrice; // 当前价格（由盯市回写）
    private BigDecimal positionRatio; // 仓位占比 (0, 1]
    private LocalDateTime openedAt;  // 开仓时间（@PrePersist 写入）
    private LocalDateTime closedAt;  // 平仓时间
    private String status;          // 状态 (OPEN/CLOSED)
}
```

### 3.2 AccountNav - 账户净值

```java
@Entity
@Table(name = "account_nav")
public class AccountNav {
    private Long id;                  // 主键
    private Long userId;              // 用户ID
    private LocalDate navDate;        // 净值日期
    private BigDecimal totalAssets;   // 总资产
    private BigDecimal cash;          // 现金
    private BigDecimal marketValue;   // 持仓市值
    private BigDecimal dailyReturn;   // 当日收益率
    private BigDecimal cumulativeReturn; // 累计收益率
    private LocalDateTime createdAt;  // 创建时间
}
```

**唯一约束**: `(user_id, nav_date)` — 每用户每日一条净值记录（重算为 upsert）。

### 3.3 Trade - 成交记录（实现阶段新增）

```java
@Entity
@Table(name = "trades")
public class Trade {
    private Long id;
    private Long userId;
    private String strategyType;
    private String sectorCode;
    private String sectorName;
    private Long positionId;       // 关联 positions(id)，开/平仓配对
    private String direction;      // BUY / SELL
    private BigDecimal quantity;
    private BigDecimal price;
    private BigDecimal amount;
    private BigDecimal commission; // 手续费
    private BigDecimal stampTax;    // 印花税（仅卖出）
    private BigDecimal slippage;    // 滑点
    private LocalDate signalDate;
    private LocalDateTime tradedAt; // @PrePersist 写入
}
```

### 3.4 数据库 ER 关系

```
users (1) ──── (N) positions
users (1) ──── (N) account_nav
users (1) ──── (N) trades
users (1) ──── (N) bank_transfers

positions (1) ──── (N) trades   （经 trades.position_id 关联）

positions:
  - 每条记录代表一次持仓（开仓→平仓）
  - OPEN = 当前持仓；CLOSED = 历史持仓
  - 同一 (user_id, strategy_type, sector_code) 仅允许一笔 OPEN

account_nav:
  - 每日一条记录
  - total_assets = cash + market_value
  - daily_return = (今日 total_assets / 上一净值日 total_assets) - 1
  - cumulative_return = (今日 total_assets / 最早净值日 total_assets) - 1
```

---

## 四、核心业务模型

### 4.1 资金模型（已修正，旧公式废弃）

> 历史设计（原 5.4 / 4.2）采用 `现金 = 净入金 − 持仓市值`，该式导致
> `总资产 = 现金 + 市值 ≡ 净入金`，**盈亏恒为 0**（详见 9.4 P0-1）。现以现金流口径为准。

```
净入金 = Σ(入金) − Σ(出金)

现金 = 净入金
       − Σ(买入金额 + 手续费 + 滑点)
       + Σ(卖出金额 − 手续费 − 印花税 − 滑点)

持仓市值 = Σ(OPEN 持仓 数量 × 当前价)
总资产   = 现金 + 持仓市值
```

要点：

- 交易成本在现金中真实扣减，不存在「免费交易」；
- 市值随 `current_price` 变动，行情涨跌即可体现为盈亏；
- 现金不为负（计算结果小于 0 时归零）。

**已废弃公式**（保留以说明演进，禁止再使用）：

```
~~现金 = 净入金 − 持仓市值~~
~~今日盈亏 = 昨日总资产 × 当日收益率~~
```

### 4.2 开仓流程（BUY 信号）

```
1. 校验当前价 > 0，且仓位比例 ∈ (0, 1]
2. 校验同 (user_id, strategy_type, sector_code) 无 OPEN 持仓（防重复开仓/僵尸持仓）
3. 目标市值 = 总资产 × position_ratio
4. 买入数量 = 目标市值 / 当前价，向下取整到 100 份（ETF 最小交易单位）
   - 不足 1 手则拒绝开仓
5. 计算成本：手续费 = 买入金额 × 0.03%（最低 5 元）、滑点 = 买入金额 × 0.1%
6. 落库 Position(status=OPEN, etf_code) 与 Trade(position_id, direction=BUY)
7. 重算当日净值
```

### 4.3 平仓流程（SELL 信号）

```
1. 按 (user_id, strategy_type, sector_code) 定位 OPEN 持仓（查询下推 DB）
   - 未找到则抛异常
2. 平仓价取：传入价 > 持仓现价 > 均价（依次回退）
3. 卖出金额 = 数量 × 平仓价
4. 成本：印花税 = 卖出金额 × 0.1%、手续费 = 卖出金额 × 0.03%（最低 5 元）、滑点 = 0.1%
5. Position(status=CLOSED, closedAt=now) + Trade(direction=SELL)
6. 重算当日净值
```

### 4.4 交易成本参数

| 项目 | 费率 | 说明 |
|------|------|------|
| 手续费 | 成交金额 × 0.03% | 买卖双向，最低 5 元 |
| 印花税 | 卖出金额 × 0.1% | 仅卖出 |
| 滑点 | 成交金额 × 0.1% | 买卖双向（模拟） |

### 4.5 净值计算

```
持仓市值     = Σ(OPEN 持仓 数量 × 当前价)
总资产       = 现金 + 持仓市值
当日收益率   = (今日总资产 / 上一净值日总资产) − 1
累计收益率   = (今日总资产 / 最早净值日总资产) − 1
               （无净值记录时基准取净入金）
```

写入 `account_nav`，同一 `(user_id, nav_date)` 存在则更新（upsert）。

### 4.6 今日盈亏（金额口径）

```
今日盈亏 = 今日总资产 − 上一净值日总资产
```

不得使用「收益率 × 市值 / 总资产」近似——量纲错误，会导致前端盈亏金额失真（详见 9.4 P1-6）。

### 4.6.1 ETF 代码校验（未映射标的拦截）

未纳入映射的 ETF 无法采集收盘价 → 该持仓价格永不更新 → 盯市完整性为 false → **净值重算被中止**。
因此开仓前必须拦截，而不是等盯市时才发现。

**校验层次**（`EtfCodeValidator`，映射经 data-collector 查询并缓存 10 分钟）

| 层级 | 校验内容 | 失败结果 |
|------|---------|---------|
| L1 格式 | 6 位数字（沪市 5 开头 / 深市 15 开头） | 拒绝：「代码格式非法」 |
| L2 存在性 | 是否在映射全集（静态 + 后续动态） | 进入 L3 |
| L3 可交易性 | 能取到收盘价 **且** 最近交易日距今 ≤ 10 天 | 可交易 → 拒绝「未纳入映射」；不可交易 → 拒绝「代码不存在或已不可交易」 |

> 新鲜度阈值是必需的：实测 `159999` 能取到收盘价，但最后交易日停留在 `2023-03-10`（已退市），
> 仅判断「有价」会误判为可交易。

**处理策略**

- **代码缺失但板块可映射** → **自动填充**该板块默认标的（如家用电器 → `159996`），记 INFO；
- **未通过校验** → 拒绝开仓并抛出明确原因（含「请联系管理员添加映射」）；
- **映射服务不可用** → 降级为仅格式校验并放行（WARN），避免 data-collector 故障拖垮开仓；
- `fund.etf.strict-mapping=false` 时未映射代码放行并 WARN（仅供应急，该持仓将无法盯市）。

**后续规划**：P1 支持动态临时映射（免发版应急添加）与补采重算闭环；P2 增加未映射事件汇总通知。

### 4.7 收益归因

```
按板块统计盈亏贡献：

  板块贡献 = Σ(该板块所有已平仓交易的盈亏)
  盈亏 = (卖出均价 − 买入均价) × 数量 − 手续费 − 印花税
  占比 = 板块贡献 / 总收益 × 100%
```

---

## 五、收盘盯市与调度

### 5.1 为什么需要盯市

持仓的 `current_price` 若只在开仓时写入、此后永不更新，则市值恒等于成本、盈亏恒为 0。因此每日收盘必须按 `etf_code` 回写最新价。

### 5.2 数据源收口与职责边界

| 组件 | 唯一职责 | 明确不做 |
|------|---------|---------|
| data-collector | 采集外部行情（AkShare）、清洗、落库 InfluxDB | 不做调度、不做策略计算 |
| scheduler | 编排：按时间触发采集/计算/重算 | **不直连数据源**，不持有行情 SDK |
| strategy | 策略计算与信号生成 | 需要行情时**查询 data-collector**，不自采 |
| fund-management | 账务：持仓、成交、净值 | 不感知数据源，只接收价格与信号 |

### 5.3 数据流

```
AkShare(fund_etf_hist_sina 新浪ETF日线)
    └─> data-collector: collect_etf_quotes()
            └─> InfluxDB(measurement: etf_quote)
                    ├─> GET /query/etf-prices → strategy 填充信号 current_price
                    └─> scheduler(job_recalc_nav) → POST /api/fund/mark-to-market → fund 持仓盯市
                                                  → POST /api/fund/recalc-nav
```

**ETF 代码来源**：`services/shared/sector_etf_map.py` —— strategy 与 data-collector 共用同一份（100 个板块 / 76 只 ETF）。历史上两边各有一份且命名体系不同（申万一级 vs 同花顺细分），导致采集范围与策略标的错位，现已统一（详见 5.7）。

### 5.4 收盘时序

| 时间 | 任务 | 动作 |
|------|------|------|
| 15:30 | job_collect_data | 板块资金流 → **ETF 收盘价采集**（须早于策略计算，否则信号无价） |
| 15:35 | job_calculate_strategy | 备用触发（正常由采集链路链式触发） |
| 15:40 | job_recalc_nav | 查 ETF 收盘价 → 盯市回写持仓价 → 净值重算（查不到则补采一次兜底） |

### 5.5 数据完整性与失败处理

原则：**宁可不记账，也不用不完整的数据记账**。净值一旦写入即成为历史曲线的一部分，
用陈旧价格算出的错误净值会污染整条曲线且难以回溯修正。

| 环节 | 校验内容 | 失败处理 |
|------|---------|---------|
| 取价（scheduler） | HTTP 成功且返回非空 | 查询失败**抛异常**并 error 告警；触发一次补采，仍失败则带空价格进入盯市 |
| 盯市（fund） | 每个 OPEN 持仓的 `etf_code` 都有正价 | 返回 `complete=false` 与 `missing_etf_codes` |
| 重算（scheduler） | `complete=true` 才继续 | 不完整则**跳过 `/recalc-nav`** 并 error 告警，不写入当日净值 |
| 开仓（fund） | `current_price` 必须为正 | 抛 `IllegalArgumentException`，由 SignalConsumer 逐条捕获记录，不静默成交 |

盯市响应示例（覆盖不完整）：

```json
{
  "code": 200,
  "message": "盯市未完成：部分持仓缺少收盘价",
  "data": {
    "open_positions": 2,
    "updated": 1,
    "missing_etf_codes": ["512720"],
    "complete": false
  }
}
```

要点：

- **空仓例外**：无 OPEN 持仓时 `complete` 为 true（无缺失项），即使当日无价格也正常重算——净值等于现金，不依赖行情。
- **失败与无数据必须区分**：取价函数失败时抛异常而非返回空字典，否则「查询失败」会被误判为「当日无价格」而静默跳过、无人察觉。
- **告警可见**：不完整时记录 error 级日志，含缺失的 ETF 代码，便于定位是采集失败还是映射缺失。
- **strategy 侧同步**：当日无价格时信号不带价并告警，fund 因价格非正拒绝开仓，不会产生无价成交。

### 5.6 非交易日与兜底

- 非交易日：由 scheduler 的 `_is_non_trade_day()` 判断并跳过；fund 侧不保留本地定时任务。
- 兜底：查询为空时触发一次补采；仍不完整则按 5.5 中止（不再「仅重算净值」）。

### 5.7 数据源实测结论（2026-09-25）

对 9 个候选数据源逐一实测（data-collector 容器内网环境，目标标的 512800 银行ETF，最近交易日 2026-09-24）。

**可用**

| 数据源 | 用途 | 稳定性 | 平均耗时 | 说明 |
|--------|------|--------|---------|------|
| `fund_etf_hist_sina`（新浪 ETF 日线） | **ETF 收盘价（本项目采用）** | 3/3 | 0.27s | 字段 `date/open/high/low/close/volume/amount` 完整；按代码逐只请求（沪市 `sh`、深市 `sz` 前缀） |
| `stock_board_industry_index_ths`（同花顺） | 板块指数收盘价 | 3/3 | 0.17s | 字段完整；为**指数点位**，非 ETF 价格，不可用于持仓盯市 |
| `stock_zh_index_daily`（新浪） | 大盘指数收盘 | 3/3 | 0.32s | 基准对照用 |

**不可用**

| 数据源 | 失败原因 |
|--------|---------|
| `fund_etf_spot_em`（东财，原采用） | `ConnectionError: Remote end closed connection`，稳定失败（0/2），失败耗时约 5s |
| `fund_etf_hist_em`（东财） | 同上，快速失败 0.08s |
| `index_zh_a_hist`（东财） | 同上，5.02s |
| `stock_zh_index_spot_em`（东财） | 同上，0.12s |
| `fund_etf_spot_ths`（同花顺） | 口径不符：返回场外基金净值，无场内 ETF 代码与价格 |
| `stock_board_industry_summary_ths` | 无收盘价字段（仅有均价、涨跌幅、净流入） |

东财系列排查：域名可达（push2 根路径返回 404）、容器外网可达（baidu 200），属**接口侧拒绝**（反爬/接口变更），非容器网络问题，且稳定失败而非偶发。

**实测结果**

- 采集 2026-09-24：**77/77（覆盖率 100%）**，无缺失；耗时约 16s（8 线程并发）。
- 采集 2026-09-25（当日未开盘）：**0/77**，日志 WARNING 明确列出全部缺失代码，不写入任何价格。

**家电类标的替换**

`159746`（家电ETF）在新浪日线接口返回空列（数据源侧异常，无法取价），是原唯一缺失项。
实测 12 只家电类 ETF 全部可用后，选取历史最完整的 `159996`（家电ETF国泰，1587 个交易日）为首选、
`561120`（家电ETF富国）为沪市次选，覆盖 `家用电器/白色家电/黑色家电/小家电/厨卫电器` 五个板块
及 `SECTOR_ETF_MAP` 中 7 条对应条目；替换后覆盖率由 98.7% 升至 100%。

**映射统一（方案 B 落地）**

原 data-collector 持有独立的旧版映射（30 条、申万一级命名），仅覆盖策略实际使用标的的 35.5%（27/76），
49 只 ETF 采不到价 → 盯市必然 incomplete → 净值重算被中止。现将映射抽到 `services/shared/sector_etf_map.py`
（以 strategy 的完整映射为准：100 板块 / 76 ETF，同花顺细分命名），两边共用，覆盖率升至 98.7%。

采集支持两种模式：

- 全集采集（15:30，供 strategy 填信号价）：并发 8 线程，76 只约 17s；
- 按持仓驱动（15:40 盯市前）：scheduler 先查 `GET /api/fund/etf-codes` 取当前持仓标的，只补采缺失代码。

**准确性校验**

- 512800 近 60 日 OHLC 自洽（`close` 落在 `[low, high]` 内，异常 0 行）；
- 9/24 ETF 涨跌 +0.72% vs 银行板块指数 +0.30%，方向一致（差 0.42pp，属正常跟踪误差）。

**口径提醒**：新浪日线疑似含复权处理，价格绝对值与东财实时价口径不同。**开仓价与盯市价必须同源**（均取本服务采集结果），混用会直接算错盈亏。

---

## 六、接口设计

统一前缀 `/api/fund`，用户通过 Header `X-User-Id` 传递（默认 1）。

### 6.1 当前持仓

```
GET /api/fund/positions?strategyType=AGGRESSIVE
Header: X-User-Id: 1

响应:
{
  "code": 200,
  "data": [
    {
      "id": 1,
      "strategyType": "AGGRESSIVE",
      "sectorCode": "SW801780",
      "sectorName": "银行",
      "etfCode": "512800",
      "direction": "BUY",
      "quantity": 5000,
      "avgPrice": 3856.42,
      "currentPrice": 3920.15,
      "positionRatio": 0.5,
      "openedAt": "2026-04-15T15:05:00",
      "status": "OPEN"
    }
  ]
}
```

### 6.2 净值曲线

```
GET /api/fund/nav-curve?strategyType=MODERATE&startDate=2026-01-01&endDate=2026-04-18
Header: X-User-Id: 1

响应:
{
  "code": 200,
  "data": [
    {
      "nav_date": "2026-01-02",
      "total_assets": 1000000.00,
      "cash": 500000.00,
      "market_value": 500000.00,
      "daily_return": 0.0015,
      "cumulative_return": 0.0
    }
  ]
}
```

### 6.3 收益归因

```
GET /api/fund/attribution?strategyType=MODERATE&startDate=2026-01-01&endDate=2026-04-18
Header: X-User-Id: 1

响应:
{
  "code": 200,
  "data": [
    { "sector_name": "银行", "contribution": 0.032, "percentage": 28.0 },
    { "sector_name": "电子", "contribution": 0.025, "percentage": 22.0 }
  ]
}
```

### 6.4 账户概览

```
GET /api/fund/summary
Header: X-User-Id: 1

响应:
{
  "code": 200,
  "data": {
    "total_assets": 1152300.00,
    "cash": 500000.00,
    "market_value": 652300.00,
    "today_pnl": 3200.00,
    "cumulative_return": 0.1523,
    "net_deposit": 1000000.00
  }
}
```

计算逻辑（见 4.1、4.6）：现金由真实现金流推导；`today_pnl` 为「今日总资产 − 上一净值日总资产」的金额差。

### 6.5 每日盈亏

```
GET /api/fund/daily-pnl?month=2026-04
Header: X-User-Id: 1

响应: 返回当月每日盈亏和收益率；daily_pnl_amount 为相邻净值日总资产之差（金额）
```

### 6.6 收益曲线（按月统计）

```
GET /api/fund/profit-curve?months=3
Header: X-User-Id: 1

响应: 返回近 N 个月的收益曲线、月度收益率和统计指标（总收益、最大回撤等）
```

### 6.7 银行转账

```
POST /api/fund/transfer
Header: X-User-Id: 1
Body: { "transfer_date": "2026-04-18", "direction": "DEPOSIT", "amount": 100000, "remark": "入金" }

GET /api/fund/transfers?start_date=2026-04-01&end_date=2026-04-30
Header: X-User-Id: 1

DELETE /api/fund/transfer/{id}
Header: X-User-Id: 1
```

转账新增/删除后会刷新 `fund:summary:{user_id}` 缓存。

### 6.8 收盘盯市（新增）

```
POST /api/fund/mark-to-market
Body: { "prices": { "512800": 1.2345, "512720": 0.9876 } }

响应: { "code": 200, "message": "盯市完成", "data": { "updated": 2 } }
```

按 `etf_code` 回写 OPEN 持仓最新价；由 scheduler 收盘任务调用。

### 6.9 净值重算（新增）

```
POST /api/fund/recalc-nav
Header: X-User-Id: 1

响应: { "code": 200, "message": "净值已重算", "data": { ...AccountNav... } }
```

### 6.10 内部执行端点（默认关闭，新增）

```
POST /api/fund/execute
Body: { "strategyType", "sectorCode", "sectorName", "etfCode", "direction", "positionRatio", "currentPrice" }
```

仅用于本地联调（不依赖 RabbitMQ 即验证 Service 层）。由 `fund.internal.enabled` 控制，**默认 false**，未启用时返回 403，避免无鉴权下单风险。

### 6.11 健康检查

```
GET /api/fund/health
响应: { "status": "healthy", "service": "fund-management" }
```

---

## 七、信号消费（与策略引擎联动）

原设计标注「待实现」，现已实现（`consumer/SignalConsumer.java`）：

```
RabbitMQ 消费 signal.generated（topic exchange: rotation）:
  1. 解析消息：strategy_type、user_id、signals[{sector_code, sector_name, etf_code,
     direction, position_ratio, current_price}]
  2. BUY  → PositionService.openPosition(...)
  3. SELL → PositionService.closePosition(...)
  4. 逐条异常隔离（单条失败不影响其余），全部处理完重算当日净值
  5. 更新 Redis 缓存 fund:summary:{user_id}
```

要点：

- 用户取自消息体 `user_id`（不再硬编码 1），支持多用户；
- ETF 代码随持仓落库，供后续盯市按标的价格回写。

净值计算触发时机：

1. 信号成交后（实时）；
2. 每日收盘后（市值变动）——由 scheduler 编排；
3. 用户查询时（实时计算，命中缓存则直接返回）。

---

## 八、缓存与前端集成

- 缓存键：`fund:summary:{user_id}`，TTL 5 分钟；成交、重算、转账后刷新。
- 序列化：金额启用 `WRITE_BIGDECIMAL_AS_PLAIN`，避免 BigDecimal 反序列化为 Double 丢精度。
- 前端 `frontend/src/views/Fund.vue` 接入：
  - 账户概览卡片（`/summary`）；
  - 净值曲线 ECharts（`/nav-curve`，用 `useBreakpoint` 的 `bp.labelInterval`）；
  - 收益归因（`/attribution`，饼/柱图）；
  - 每日盈亏表（`<div class="responsive-table">` 包裹 `el-table`）。
- 遵循前端规范：设计变量 `var(--bg-*)`、`page-card` 布局、响应式断点、图表 `autoresize`。
- 验证：`npm run typecheck` + `npm run lint` 通过。

---

## 九、实施记录

### 9.1 实施背景（2026-09-25 核查）

实施前 `FundController` 直连 repository，只有查询/展示层，**无任何业务逻辑层**：无 Service、无信号消费、`account_nav`/`positions` 无数据生成入口、前端 `Fund.vue` 仅占位。

### 9.2 模块拆解（按依赖顺序）

**模块 1：持仓交易 Service** — `PositionService`（开仓/平仓/交易成本/资金与市值/盯市）、实体扩展（`Position.etf_code`、`Trade.position_id`）、`FundController` 触发端点（默认关闭）、单测。

**模块 2：信号消费接入** — 引入 `spring-boot-starter-amqp`、`SignalConsumer` 监听 `signal.generated`、解析消息并按用户下单、成交后重算净值。

**模块 3：净值计算落库** — `AccountNavService.recalcNav`（upsert）、信号成交后实时调用、每日收盘由 scheduler 统一调度、summary 逻辑收敛到 Service。

**模块 4：缓存与前端集成** — Redis 缓存 + `Fund.vue` 接入真实数据。

### 9.3 决策结论

1. 实施范围：模块 1+2+3+4 全做（含前端对接）。
2. Service 组织：拆 `PositionService`（持仓/交易/资金）+ `AccountNavService`（净值/缓存）。
3. 净值定时重算归属：scheduler 收盘任务统一调度；fund 侧本地 `@Scheduled` 已移除（避免双写）。
4. 当前价来源：开仓价取信号携带的 ETF 价；收盘盯市由 data-collector 采集、scheduler 推送。

### 9.4 Review 后修复记录（2026-09-25）

验证：`mvn test` 10 个单测全通过 + Python 语法检查通过。

**P0 核心逻辑**

1. **总资产恒等于净入金（盈亏永远为 0）**：原 `现金 = 净入金 − 持仓市值` ⇒ `总资产 ≡ 净入金`。修正为现金流模型（见 4.1）。
2. **无盯市机制**：`current_price` 仅开仓写入、永不更新。新增 `/mark-to-market` 与 `etf_code`（见第五章）。

**P1 模型与一致性**

3. `Position` 增加 `etf_code`；`Trade` 增加 `position_id`（开/平仓配对）。
4. 交易成本进入现金流，不再是「免费交易」。
5. 买入数量向下取整到 100 份，消除碎股（如 13333.33 份）。
6. 今日盈亏改为金额口径，修正 `/summary` 与 `/daily-pnl` 两处量纲错误。
7. 同一板块重复开仓被拒绝（防僵尸持仓）。
8. 转账新增/删除后刷新 `fund:summary:{userId}` 缓存。

**P2 多用户与生产化**

9. `SignalConsumer` 从消息体读取 `user_id`（不再硬编码 1）。
10. `/api/fund/execute` 增加开关 `fund.internal.enabled`（默认 false）。
11. 删除 fund 内 `ScheduledNavTask` 与 `@EnableScheduling`，统一由 scheduler 调度并判断非交易日。
12. 修正 scheduler 调用路径缺失 `/api/fund` 前缀（原 `/recalc-nav` 会 404）。

**P3 工程质量**

13. 补充单测 10 个：现金模型/盈亏量纲/取整/查重/平仓成本/信号多用户。
14. 净值查询下推 DB（`findTopBy...NavDateBefore...`、`findFirstBy...NavDateAsc`），去掉全量内存遍历。
15. 缓存金额启用 `WRITE_BIGDECIMAL_AS_PLAIN`。
16. `Dockerfile` 去掉 `-DskipTests`，镜像构建即跑测试。
17. 移除为迁就 Mockito 而在生产代码显式设置 `openedAt` 的写法（改由 `@PrePersist` 负责）。

**P4 配置与文档**

18. `application.yml` 凭据改为环境变量注入（`SPRING_DATASOURCE_*`、`SPRING_DATA_REDIS_*`、`SPRING_RABBITMQ_*`、`INFLUXDB_*`）。
19. `scripts/init-db.sql` 补齐 `positions.etf_code`、`trades.position_id`、`trades.stamp_tax`。
20. 本文档为 07 与 14 合并后的统一版本。

**架构重构（数据源收口）**

- 曾为快速修复让 scheduler 直连 AkShare，后按架构原则重构：采集收口到 data-collector，scheduler 移除 `akshare`/`pandas` 回到纯编排，strategy 信号带价改为查询 `/query/etf-prices`。
- 理由：职责边界（避免既是编排者又是采集者）、资源配额（scheduler limit 256M）、口径一致（开仓价与盯市价同源）、可回溯（价格落库可查可补采）、维护成本（数据源变更只改一处）。

---

## 十、扩展设计

### 10.1 实盘对接

当前为模拟盘，实盘扩展：

- 券商 API 对接（如 QMT / 恒生）；
- 实时行情订阅；
- 委托下单接口；
- 资金账号同步；
- 风控检查（单日亏损上限、单板块集中度上限）。

### 10.2 高级分析

- 风险指标：VaR、最大回撤区间、Beta；
- 归因分析：Brinson 模型分解；
- 压力测试：极端行情模拟；
- 基准对比：沪深300 / 中证500。

---

## 十一、实施纪律与关键约束

- 每模块一个独立 commit，遵循 `CONTRIBUTING.md` 的 scope 与提交信息规范（`feat(fund):`、`fix(fund):`）。
- 每步保证：可编译、可单测、可本地跑通；**未经验证不得提交**（Java 用 `mvn test`，Python 用语法检查与测试）。
- **任何删除文件动作执行前必须先获用户确认**（已写入 `CLAUDE.md` User Rules）。
- 跨服务职责不得交叉：数据源只由 data-collector 消费，调度只由 scheduler 编排，行情不得被业务服务直采。
