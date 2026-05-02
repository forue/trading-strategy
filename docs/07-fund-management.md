# 资金管理服务设计文档

> 版本: v1.0 | 更新日期: 2026-04-18

---

## 一、模块概述

资金管理服务负责模拟/实盘的持仓管理、净值计算、收益统计和归因分析。根据策略信号模拟成交（考虑滑点和手续费），生成每日净值曲线。

| 属性 | 值 |
|------|-----|
| 服务名 | backend-fund |
| 端口 | 8005 |
| 语言 | Java 17 |
| 框架 | Spring Boot 3.2 + JPA |
| 数据库 | PostgreSQL + Redis + InfluxDB |

---

## 二、技术架构

```
┌─────────────────────────────────────────────────────────┐
│                 FundController (:8005)                    │
│                                                         │
│  GET /api/fund/positions   - 当前持仓查询                │
│  GET /api/fund/nav-curve  - 净值曲线                    │
│  GET /api/fund/attribution - 收益归因                    │
│  GET /api/fund/summary    - 账户概览                    │
│  GET /api/fund/daily-pnl  - 每日盈亏                    │
│  GET /api/fund/profit-curve - 收益曲线                  │
│  POST /api/fund/transfer  - 银行转账                    │
│  GET /api/fund/transfers  - 转账记录                    │
│  DELETE /api/fund/transfer/{id} - 删除转账              │
│  GET /api/fund/health     - 健康检查                    │
└──────────┬──────────────────────────┬───────────────────┘
           │                          │
    ┌──────▼──────┐          ┌───────▼───────┐
    │PositionRepo │          │AccountNavRepo │
    │ (JPA)       │          │ (JPA)         │
    └──────┬──────┘          └───────┬───────┘
           │                          │
           ▼                          ▼
    ┌─────────────────────────────────────┐
    │          PostgreSQL (:5432)          │
    │  positions │ account_nav │ trades    │
    └─────────────────────────────────────┘
```

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
    private String direction;      // 方向 (BUY/SELL)
    private BigDecimal quantity;   // 持仓数量
    private BigDecimal avgPrice;   // 平均成本价
    private BigDecimal currentPrice; // 当前价格
    private BigDecimal positionRatio; // 仓位占比
    private LocalDateTime openedAt;  // 开仓时间
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

**唯一约束**: (user_id, nav_date) — 每用户每日一条净值记录

### 3.3 数据库ER关系

```
users (1) ──── (N) positions
users (1) ──── (N) account_nav
users (1) ──── (N) trades

positions:
  - 每条记录代表一次持仓（开仓→平仓）
  - OPEN状态 = 当前持仓
  - CLOSED状态 = 历史持仓

account_nav:
  - 每日一条记录
  - total_assets = cash + market_value
  - daily_return = (今日total_assets / 昨日total_assets) - 1
  - cumulative_return = (今日total_assets / 初始资金) - 1
```

---

## 四、业务逻辑

### 4.1 持仓管理

```
开仓流程 (收到BUY信号):
  1. 解析信号: sector_code, position_ratio
  2. 计算目标市值 = 总资产 × position_ratio
  3. 计算买入数量 = 目标市值 / 当前价格
  4. 扣减现金: cash -= 买入金额 + 手续费
  5. 创建Position记录 (status=OPEN)
  6. 更新账户净值

平仓流程 (收到SELL信号):
  1. 查找OPEN状态的Position
  2. 计算卖出金额 = 数量 × 当前价格
  3. 增加现金: cash += 卖出金额 - 手续费
  4. 更新Position (status=CLOSED, closedAt=now)
  5. 更新账户净值
```

### 4.2 净值计算

```
每日收盘后计算:

  持仓市值 = Σ(持仓数量 × 当前价格)
  总资产 = 现金 + 持仓市值
  当日收益率 = (今日总资产 / 昨日总资产) - 1
  累计收益率 = (今日总资产 / 初始资金) - 1

交易成本:
  手续费 = 成交金额 × 0.03% (最低5元)
  印花税 = 卖出金额 × 0.1%
  滑点 = 0.1% (模拟)
```

### 4.3 收益归因

```
按板块统计盈亏贡献:

  板块贡献 = Σ(该板块所有已平仓交易的盈亏)
  盈亏 = (卖出均价 - 买入均价) × 数量 - 手续费 - 印花税

  占比 = 板块贡献 / 总收益 × 100%

示例:
  银行: +3.2% (28%)
  电子: +2.5% (22%)
  食品饮料: +1.8% (16%)
  医药生物: -1.2% (-10%)
  ...
```

---

## 五、接口设计

### 5.1 当前持仓

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

### 5.2 净值曲线

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
    },
    ...
  ]
}
```

### 5.3 收益归因

```
GET /api/fund/attribution?strategyType=MODERATE&startDate=2026-01-01&endDate=2026-04-18
Header: X-User-Id: 1

响应:
{
  "code": 200,
  "data": [
    { "sector_name": "银行", "contribution": 0.032, "percentage": 28.0 },
    { "sector_name": "电子", "contribution": 0.025, "percentage": 22.0 },
    { "sector_name": "食品饮料", "contribution": 0.018, "percentage": 16.0 },
    ...
  ]
}
```

### 5.4 账户概览

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

**计算逻辑**:

```
净入金 = Σ(入金) - Σ(出金)
现金 = 净入金 - 持仓市值
总资产 = 现金 + Σ(OPEN持仓的 数量×当前价)
今日盈亏 = 昨日总资产 × 当日收益率
累计收益率 = (总资产 / 初始资金) - 1
```

### 5.5 每日盈亏

```
GET /api/fund/daily-pnl?month=2026-04
Header: X-User-Id: 1

响应: 返回当月每日盈亏和收益率
```

### 5.6 收益曲线（按月统计）

```
GET /api/fund/profit-curve?months=3
Header: X-User-Id: 1

响应: 返回近N个月的收益曲线、月度收益率和统计指标
```

### 5.7 银行转账

```
POST /api/fund/transfer
Header: X-User-Id: 1
Body: { "transfer_date": "2026-04-18", "direction": "DEPOSIT", "amount": 100000, "remark": "入金" }

GET /api/fund/transfers?start_date=2026-04-01&end_date=2026-04-30
Header: X-User-Id: 1

DELETE /api/fund/transfer/{id}
Header: X-User-Id: 1
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

**计算逻辑**:

```
净入金 = Σ(入金) - Σ(出金)
现金 = 净入金 - 持仓市值
总资产 = 现金 + Σ(OPEN持仓的 数量×当前价)
今日盈亏 = 昨日总资产 × 当日收益率
累计收益率 = (总资产 / 初始资金) - 1
```

### 5.5 每日盈亏

```
GET /api/fund/daily-pnl?month=2026-04
Header: X-User-Id: 1

响应: 返回当月每日盈亏和收益率
```

### 5.6 收益曲线（按月统计）

```
GET /api/fund/profit-curve?months=3
Header: X-User-Id: 1

响应: 返回近N个月的收益曲线和月度收益率
```

### 5.7 银行转账

```
POST /api/fund/transfer
Header: X-User-Id: 1
Body: { "transfer_date": "2026-04-18", "direction": "DEPOSIT", "amount": 100000, "remark": "入金" }

GET /api/fund/transfers?start_date=2026-04-01&end_date=2026-04-30
Header: X-User-Id: 1

DELETE /api/fund/transfer/{id}
Header: X-User-Id: 1
```

---

## 六、与策略引擎的联动

### 6.1 信号消费（待实现）

```
RabbitMQ消费 signal.generated 事件:
  1. 解析信号列表
  2. BUY信号 → 执行开仓逻辑
  3. SELL信号 → 执行平仓逻辑
  4. 计算当日净值 → 写入account_nav
  5. 更新Redis缓存 (fund:summary:{user_id})
```

### 6.2 净值计算触发

```
触发时机:
  1. 信号到达时 (交易发生)
  2. 每日收盘后 (市值变化)
  3. 用户查询时 (实时计算)
```

---

## 七、扩展设计

### 7.1 实盘对接

```
当前为模拟盘，实盘扩展:
  - 券商API对接 (如QMT/恒生)
  - 实时行情订阅
  - 委托下单接口
  - 资金账号同步
  - 风控检查（单日亏损上限、单板块集中度上限）
```

### 7.2 高级分析

```
- 风险指标: VaR、最大回撤区间、Beta
- 归因分析: Brinson模型分解
- 压力测试: 极端行情模拟
- 基准对比: 沪深300/中证500
```
