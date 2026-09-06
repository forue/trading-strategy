# 策略引擎服务设计文档

> 版本: v2.0 | 更新日期: 2026-09-06 | 更新: T+1回测、19因子体系、动态权重

---

## 一、模块概述

策略引擎是系统的核心模块，负责基于板块日线与资金流等数据，经 **因子注册中心 + 因子合成** 得到综合评分，再按三档规则输出买卖信号。评分主路径为 **多因子绝对分** 与可选 **截面排名分** 的线性混合，辅以市场过滤、相对调仓阈值与波动倒数仓位（均可由 `StrategyParams` 关闭或调参）。

| 属性 | 值 |
|------|-----|
| 服务名 | backend-strategy |
| 端口 | 8002 |
| 语言 | Python 3.11 |
| 框架 | FastAPI |
| 依赖 | InfluxDB(数据源) + Redis(缓存) + RabbitMQ(通知) |
| 核心算法 | 板块资金轮动评分模型 |

### 架构说明

核心逻辑集中在 `scoring.py`（策略引擎核心），包含评分计算、信号生成、回测引擎。`factors/` 目录实现 19 个量化因子，`combiner/` 实现因子合成引擎。

```
services/strategy/app/
├── main.py          # API 端点
├── scoring.py       # 策略引擎核心（评分、信号、回测）
├── factors/         # 因子引擎（19个因子）
│   ├── trend.py         # 趋势因子（MA均线/板块离散度）
├── combiner/        # 因子合成引擎
├── models.py        # 数据模型
├── influx_query.py  # InfluxDB 查询
└── config.py        # 配置
```

---

## 二、评分模型设计（与 `scoring.py` 一致）

### 2.1 主路径：因子引擎 + 合成

1. 对每个板块：`FactorRegistry.calculate_all(sector_data, history, context)`，其中 `context.changes_by_date` 由当日全板块 `_history` 聚合，供轮动类因子使用。
2. `FactorCombiner.combine_weighted` 得到 **绝对综合分**（类内置信度 × 因子权重，类间 `StrategyWeights`，见 `combiner/weighted.py`）。
3. 若当日有效板块数 ≥ 3 且 `cross_section_alpha > 0`：`combine_ranking` 得到 **截面综合分**，最终  
   `composite_score = (1 − α) × 绝对分 + α × 截面分`。

### 2.2 回退路径

因子引擎异常时使用 `_calculate_composite_score_fallback`（简化资金+动量+估值），并标记 `engine_fallback`（单板块分析 API 返回该字段）。

### 2.3 策略参数补充（`models.StrategyParams`）

| 参数 | 含义 |
|------|------|
| `cross_section_alpha` | 截面排名分权重 α，0 表示仅绝对分 |
| `use_relative_score_gap` | 是否启用相对调仓缺口（与绝对 `score_gap_threshold` 取 max） |
| `relative_score_gap_ratio` | 相对缺口：比例 × max(ε, \|当前持仓最高分\|, \|新建议最高分\|, 1) |
| `use_inverse_vol_weights` | 入选标的中是否按波动倒数分配 `position_ratio`（无 `_history` 时近似等权） |
| `use_zscore_normalization` | 是否对因子评分进行截面Z-Score归一化（将硬阈值分替换为板块间相对排名得分） |
| `market_bull_threshold` | 上涨板块占比达到此值判定为牛市（默认 0.5） |
| `market_bear_threshold` | 上涨板块占比低于此值判定为熊市（默认 0.4） |
| `favorable_confirm_days` | 连续 N 天同向状态才确认（默认 2，防摇摆） |
| `max_empty_days` | 最大空仓天数，超时强制试探建仓（默认 10） |
| `capital_pct_bull_boost` | 牛市加仓比例（默认 0.3） |
| `emergency_exit_score` | 持仓板块评分低于此值触发紧急退出（默认 1.0） |
| `trailing_stop_loss` | 移动止损：从近期高点回撤超此比例触发（默认 8%） |
| `max_drawdown_stop` | 最大回撤止损：从初始资金累计亏损超此比例清仓（默认 15%） |
| `benchmark_stop_loss` | 基准相对止损：累计落后大盘超此比例触发（默认 10%） |
| `ma_stop_days` | 均线止损窗口天数（默认 20） |
| `ma_stop_loss` | 均线止损阈值：跌破N日均线超此比例触发（默认 5%） |
| `ma_take_profit_days` | 均线止盈窗口天数（默认 20） |
| `ma_take_profit_thresholds` | 各级止盈触发阈值列表（递减），NAV高于均线X%时减仓（默认 [5%, 3%, 1%]） |
| `ma_take_profit_ratios` | 各级减仓比例列表（按原始仓位计算），每次卖出原始仓位的X%（默认 [30%, 40%, 30%]） |
| `drawdown_ma_window` | 回撤控制用的均线窗口（默认 20） |

默认配置见源码；与旧「四维手写权重」文档不一致时以代码为准。

### 2.4 轮动方法架构（_rotation_core）

三档策略的买卖逻辑已合并为统一的 `_rotation_core()` 方法，根据 `StrategyType` 派生差异化参数（取前N名、最小评分阈值、持仓评分缺口、估值过滤、仓位分配等）。三个公开方法 (`_aggressive_rotation` / `_moderate_rotation` / `_conservative_rotation`) 退化为 ~5 行的薄包装层，仅负责传入 `StrategyType` 并调用核心方法。

---

## 三、三档策略逻辑

### 3.1 激进轮动策略

```
目标: 追求最大收益，高频率满仓轮换，动态适应市场状态

参数:
  top_n = 2              # 仅取前2名（牛市自动+1）
  max_position = 100%     # 满仓
  hold_days = 2           # 持有1-2日（动态调整）
  stop_loss = 12%         # 固定回撤止损12%
  trailing_stop_loss = 8%  # 移动止损8%（从近期高点）
  max_drawdown_stop = 15%  # 最大回撤止损15%（从初始资金）
  capital_pct = 70%      # 基础资金使用比例（牛市可达100%）
  min_score_threshold = 1.5   # 最小评分阈值
  score_gap_threshold = 1.0   # 与相对缺口取较大（牛市×0.7，熊市×1.5）
  cooldown_days = 1       # 调仓冷却期
  keep_overlap = true     # 保持重叠持仓
  allow_empty = true     # 允许空仓（连续2天BEAR确认）
  min_score_keep = 2.5   # 保持持仓的最小评分
  commission_rate = 0.3‰ # 佣金费率（万三）
  stamp_tax_rate = 1.0‰  # 印花税率（千一，仅卖出）
  slippage_rate = 1.0‰   # 滑点费率（千一）

买入逻辑:
  1. 按综合评分排序所有板块
  2. 选取评分最高的前2名（需满足min_score_threshold）
  3. 在 `max_position × capital_pct` 目标下，按 `use_inverse_vol_weights` 在入选标的中分配仓位（否则等权）
  4. 生成BUY信号（每条含 `position_ratio`）

卖出逻辑:
  1. 综合评分 < min_score_keep 的板块
  2. 生成SELL信号

信号示例:
  { direction: "BUY", sector: "银行", score: 8.23, position: 0.5,
    reason: "激进轮动: 资金强度排名#1, 综合评分8.23, 建议满仓轮换持有3日" }
```

### 3.2 稳健轮动策略

```
目标: 平衡收益与风险，半仓分散持有

参数:
  top_n = 3              # 取前3名
  max_position = 50%     # 半仓
  hold_days = 5           # 持有5日
  stop_loss = 10%        # 固定回撤止损10%
  trailing_stop_loss = 6%  # 移动止损6%
  benchmark_stop_loss = 8% # 基准相对止损8%（落后大盘）
  capital_pct = 30%      # 资金使用比例
  min_score_threshold = 2.0   # 最小评分阈值
  score_gap_threshold = 1.0   # 与相对缺口取较大，见 StrategyParams
  cooldown_days = 2       # 调仓冷却期
  keep_overlap = true     # 保持重叠持仓
  allow_empty = true     # 允许空仓
  min_score_keep = 3.0   # 保持持仓的最小评分
  commission_rate = 0.3‰ # 佣金费率（万三）
  stamp_tax_rate = 1.0‰  # 印花税率（千一，仅卖出）
  slippage_rate = 1.0‰   # 滑点费率（千一）

买入逻辑:
  1. 按综合评分排序
  2. 选取前3名（需满足min_score_threshold）
  3. 总目标仓位内按波动倒数或等权分配各 BUY 的 `position_ratio`

卖出逻辑:
  1. 综合评分 < min_score_keep 的板块
  2. 建议减仓

信号示例:
  { direction: "BUY", sector: "食品饮料", score: 7.56, position: 0.1667,
    reason: "稳健轮动: 综合排名#2, 评分7.56, 半仓分散持有5日" }
```

### 3.3 保守轮动策略

```
目标: 注重安全边际，低仓位配置

参数:
  top_n = 5                # 取满足条件的前5名
  max_position = 30%       # 仓位上限30%
  hold_days = 10           # 持有10日
  stop_loss = 8%           # 固定回撤止损8%
  trailing_stop_loss = 5%  # 移动止损5%
  ma_stop_loss = 3%        # 均线止损3%（跌破20日均线）
  capital_pct = 20%        # 资金使用比例
  valuation_pct_max = 50   # 估值分位≤50%
  min_score_threshold = 2.0   # 最小评分阈值
  score_gap_threshold = 1.0   # 与相对缺口取较大，见 StrategyParams
  cooldown_days = 3       # 调仓冷却期
  keep_overlap = true     # 保持重叠持仓
  allow_empty = true     # 允许空仓
  min_score_keep = 3.0   # 保持持仓的最小评分
  commission_rate = 0.3‰ # 佣金费率（万三）
  stamp_tax_rate = 1.0‰  # 印花税率（千一，仅卖出）
  slippage_rate = 1.0‰     # 滑点费率（千一）

买入逻辑:
  1. 按综合评分排序
  2. 筛选评分 ≥ min_score_threshold 的板块
  3. 选取前5名
  4. 单板块仓位上限30%，总仓位不超过100%

卖出逻辑:
  1. 综合评分 < min_score_keep 的板块
  2. 不满足安全边际

信号示例:
  { direction: "BUY", sector: "银行", score: 6.12, position: 0.2,
    reason: "保守轮动: 综合评分6.12, 估值分位≤50%, 仓位上限30%" }
```

---

## 四、数据流与处理流程

### 4.1 信号计算流程

```
触发方式: 
  1. 定时触发: 任务调度中心 15:00 数据采集后链式触发（或15:05备用触发）
  2. 手动触发: 前端策略管理页触发 /calculate
  3. 登录触发: 认证服务登录成功后触发 /collect + /calculate

计算流程:
  1. 非交易日检查: 使用AkShare交易日历判断，非交易日不生成信号

  2. 从Redis获取最新板块数据 (sector_capital_flow:latest)
      └─ 无缓存时，从InfluxDB读取最近3天数据
      └─ 仍无数据时，尝试读取最近30天数据

  3. 从Redis读取当前持仓 (positions:{strategy_type})

  4. 构建截面上下文（各板块 `_history` 中的 `date` + `index_change_pct` 按日合并）

  5. 遍历每个板块：因子引擎计算 → 绝对综合分；当日板块数≥3 时再算截面分并按 `cross_section_alpha` 混合

  6. 按综合分排序，根据策略类型生成信号:
      - 市场过滤: `_market_is_favorable`（激进与稳健/保守规则不同，见源码）
      - 买入: 前 N 名且过 `min_score_threshold`；调仓需超过有效评分缺口（绝对 + 相对）
      - 卖出: 调出不在新组合中的标的（配合 keep_overlap 等）
      - 仓位: `max_position × capital_pct` 内波动倒数或等权
      - 冷却期: 止损后 cooldown_days 内不建仓

  7. 信号处理:
      a. 更新持仓到Redis (positions:{type}, TTL: 7天)
      b. 写入Redis缓存 (key: signals:{type}:{date}, TTL: 24h)
      c. 通过RabbitMQ发布 signals_generated 事件
      d. 信号通知服务消费事件 → WebSocket推送给前端
```

### 4.2 消息发布格式

```json
{
  "event": "signals_generated",
  "strategy_type": "AGGRESSIVE",
  "signal_date": "2026-04-18",
  "count": 5,
  "signals": [
    {
      "signal_date": "2026-04-18",
      "strategy_type": "AGGRESSIVE",
      "sector_code": "SW801780",
      "sector_name": "银行",
      "direction": "BUY",
      "position_ratio": 0.5,
      "score": 8.23,
      "reason": "激进轮动: 资金强度排名#1..."
    }
  ],
  "timestamp": "2026-04-18T15:05:20"
}
```

### 4.3 系统设置与缓存管理

```
系统设置 (Redis key: settings:*):
  - ws_push_enabled: WebSocket推送开关
  - ws_push_strategy_types: 推送的策略类型列表
  - data_source: 数据源类型 (akshare_ths)
  - cache_ttl_days: 缓存有效期天数
  - scheduler_enabled: 调度器开关
  - scheduler_times: 调度时间配置

缓存统计 (GET /cache/stats):
  - 返回Redis内存使用、key数量、各类数据计数

缓存清理:
  - DELETE /cache/clear: 清空所有缓存
  - DELETE /cache/expired: 为无TTL的key设置7天过期
```

---

## 五、接口设计

### 5.1 触发策略计算

```
POST /calculate?strategy_type=AGGRESSIVE&signal_date=2026-04-18

响应:
{
  "code": 200,
  "message": "策略计算完成",
  "data": [ ... signals ... ]
}
```

### 5.2 获取策略配置

```
GET /configs

响应:
{
  "code": 200,
  "data": [
    {
      "id": 1,
      "strategy_type": "AGGRESSIVE",
      "name": "激进轮动策略",
      "params": { "top_n": 2, "max_position": 1.0, "hold_days": 3, ... },
      "is_active": true
    },
    ...
  ]
}
```

### 5.3 更新策略配置

```
PUT /configs/{config_id}
Content-Type: application/json

请求:
{
  "strategy_type": "AGGRESSIVE",
  "name": "激进轮动策略",
  "params": { "top_n": 3, "max_position": 0.8, ... },
  "is_active": true
}
```

### 5.4 获取今日信号

```
GET /signals/today?strategy_type=AGGRESSIVE

响应: 从Redis缓存读取，无则返回空数组
```

### 5.5 获取信号日历

```
GET /signals/calendar?strategy_type=AGGRESSIVE&month=2026-04

响应: 从Redis缓存读取当月所有信号
```

### 5.6 策略回测

```
POST /backtest
Content-Type: application/json

请求:
{
  "strategy_type": "MODERATE",
  "start_date": "2025-04-18",
  "end_date": "2026-04-18",
  "initial_capital": 1000000,
  "params": { ... }  // 可选，覆盖默认参数
}

响应:
{
  "code": 200,
  "data": {
    "total_return": 0.1523,
    "annual_return": 0.1523,
    "max_drawdown": 0.0856,
    "sharpe_ratio": 1.23,
    "win_rate": 0.56,
    "trade_count": 48,
    "buy_count": 20,
    "sell_count": 18,
    // 交易成本统计
    "total_commission": 1250.50,
    "total_stamp_tax": 850.20,
    "total_slippage_cost": 420.30,
    "total_trade_cost": 2521.00,
    "trade_count_actual": 52,
    "params": { "top_n": 3, ... },
    // 逐日净值曲线（每个交易日一条记录，不再采样）
    "nav_curve": [
      { "date": "2025-04-18", "nav": 1000000, "benchmark": 1000000, "stop_loss": false },
      ...
    ],
    // 每日信号 + 仓位明细
    "daily_signals": [
      {
        "date": "2025-04-18",
        "signals": [...],
        "strategy_return": 0.5,
        "benchmark_return": 0.3,
        "positions": {
          "THS801010": { "weight": 0.33, "amount": 330000 },
          "THS801020": { "weight": 0.33, "amount": 330000 }
        },
        "total_position_value": 660000,
        "cash": 340000
      }
    ],
    // 仓位调整明细（加仓/减仓/清仓/止损/紧急退出/熊市空仓）
    "position_changes": [
      {
        "date": "2025-04-18",
        "sector_code": "THS801010",
        "sector_name": "有色金属",
        "action": "ADD",
        "amount": 330000,
        "cost": 297.0,
        "remaining_weight": 0.33,
        "remaining_amount": 330000,
        "reason": "新建仓 权重33.00%"
      },
      {
        "date": "2025-04-25",
        "sector_code": "THS801010",
        "sector_name": "有色金属",
        "action": "REDUCE",
        "amount": 50000,
        "cost": 45.0,
        "remaining_weight": 0.25,
        "remaining_amount": 250000,
        "reason": "减仓 33.00% → 25.00%"
      },
      {
        "date": "2025-05-02",
        "sector_code": "THS801010",
        "sector_name": "有色金属",
        "action": "STOP_LOSS",
        "amount": 250000,
        "cost": 225.0,
        "remaining_weight": 0.0,
        "remaining_amount": 0,
        "reason": "止损 回撤8.50%"
      }
    ]
  }
}

position_changes.action 类型说明:
  - ADD:            加仓或新建仓
  - REDUCE:         减仓（权重降低）
  - CLEAR:          清仓（调仓卖出，非止损）
  - STOP_LOSS:      止损清仓（回撤超阈值）
  - EMERGENCY_EXIT: 紧急退出（单日跌幅>5%）
  - BEAR_EXIT:      熊市空仓（连续BEAR确认）
```

### 5.7 回测历史

```
GET /backtest/history?strategy_type=MODERATE

响应: 返回最近的回测记录列表（最多20条）
```

### 5.8 回测详情

```
GET /backtest/{bt_id}

响应: 返回指定回测ID的完整结果
```

### 5.9 交易日检查

```
GET /trade-day/check?date=2026-04-18

响应:
{
  "code": 200,
  "data": {
    "date": "2026-04-18",
    "is_trade_day": true,
    "message": "2026-04-18 是交易日"
  }
}
```

### 5.10 数据可用性查询

```
GET /data/availability

响应:
{
  "code": 200,
  "data": {
    "has_data": true,
    "min_date": "2025-01-02",
    "max_date": "2026-04-18"
  }
}
```

### 5.11 系统设置

```
GET /settings
PUT /settings

获取/更新系统设置（WebSocket推送、数据源配置等）
```

### 5.12 数据回放接口

```
GET /data/replay/dates           - 获取可回放日期列表
GET /data/replay/sectors        - 获取板块列表
GET /data/replay/sector/{code}  - 获取板块历史数据
GET /data/replay/day/{date}     - 获取某天数据
POST /data/replay/strategy-optimize  - 策略参数自动寻优（Optuna）
POST /data/replay/strategy-overlay  - 策略叠加回放
```

---

## 六、回测逻辑与交易成本

### 6.1 回测算法流程

```
回测流程（T+1 盘后信号次日开盘价执行）:

     i. 检查待执行调仓（pending_rebalance）:
        - 若有 → 次日开盘价执行卖出/买入
        - 新仓首日收益 = open→close 日内收益（非全天）
        - 旧仓收益 = 全天收益
        - 记录 position_changes（日期=成交日，非信号日）
        - 设置持仓锁定和冷却期

     ii. 计算当日持仓收益（T+1 拆分）:
        - 已有持仓: weight × 当日涨跌幅
        - 今日新开仓: weight × (close - open) / open

     iii. 止损/紧急退出检查

     iv. 更新冷却期计数器

     v. 生成信号（记录待执行，不立即调仓）:
        - 信号日 = D，记录 pending_rebalance
        - 成交日 = D+1，实际执行

  5. 计算绩效指标:
     - 总收益率 = 最终资本 / 初始资本 - 1
     - 年化收益率 = (1 + 总收益率)^(252/交易日数) - 1
     - 最大回撤 = 基于逐日NAV计算
     - 夏普比率 = (日均收益 × 252) / (日收益标准差 × √252)
     - 胜率 = 正收益天数占比
     - 换手率、空仓天数占比、盈亏比、最大连续盈/亏天数
```

#### 基准数据来源

回测基准（大盘K线）按以下优先级获取:
1. **InfluxDB `market_kline`** — data-collector 采集并写入的大盘指数日K线（推荐）
2. **AkShare `stock_zh_index_daily_em`** — 实时查询上证指数 sh000001（回退）
3. **板块等权平均** — 所有板块当日涨跌幅的算术平均（最终回退）

#### 节假日管理

交易日判断基于可扩展的年度节假日字典 `_HOLIDAYS_BY_YEAR`:
- 包含 2025/2026/2027 年A股法定节假日
- 新增年份只需在字典中追加对应的日期集合
- 周末（周六、周日）自动识别为非交易日

### 6.1.1 动态市场状态

市场状态由上涨板块占比和平均涨跌幅决定:

| 状态 | AGGRESSIVE 条件 | 行为影响 |
|------|----------------|---------|
| BULL | 上涨占比 ≥ 50% 且 avg > 0 | capital_pct + 30%，top_n + 1，hold_days - 1，score_gap × 0.7 |
| NEUTRAL | 不满足 BULL/BEAR | 标准参数 |
| BEAR | 上涨占比 < 40% 且 avg < 0 | 空仓（连续2天确认），score_gap × 1.5 |

空仓管理:
- 确认: 连续 `favorable_confirm_days`（默认2）天 BEAR 才触发空仓
- 恢复: 连续2天非 BEAR 才恢复建仓
- 超时: 空仓超过 `max_empty_days`（默认10）天且市场为 NEUTRAL → 强制50%仓位建仓
- 紧急退出: 持仓板块单日跌幅 > 5% → 立即允许调仓（跳过 hold_days）

动态参数计算:
- `dynamic_capital_pct`: BULL = min(base + 0.3, 1.0)，NEUTRAL = base，BEAR = 0
- `dynamic_top_n`: BULL = min(base + 1, 5)，其余 = base
- `dynamic_hold_days`: BULL = max(base - 1, 1)，BEAR = base + 1，其余 = base
- `dynamic_score_gap`: BULL = floor × 0.7，BEAR = floor × 1.5，其余 = floor

### 6.2 交易成本计算规则

#### 佣金计算
- **费率**: 默认万三 (0.0003)
- **最低**: 5元
- **收取**: 买入和卖出都收取
- **公式**: `max(交易金额 × commission_rate, 5.0)`

#### 印花税计算  
- **费率**: 默认千一 (0.001)
- **最低**: 无
- **收取**: 仅卖出时收取
- **公式**: `交易金额 × stamp_tax_rate`

#### 滑点成本计算
- **费率**: 默认千一 (0.001)
- **最低**: 无
- **收取**: 买入和卖出都收取
- **公式**: `交易金额 × slippage_rate`

#### 计算场景
1. **常规调仓**:
   - 卖出旧持仓：佣金 + 印花税 + 滑点
   - 买入新持仓：佣金 + 滑点
   - 细分: 清仓(CLEAR)、减仓(REDUCE)、加仓(ADD)、新建仓(ADD)
2. **止损触发**（多重止损机制，任一触发即清仓）:
   - 固定回撤止损 (`stop_loss`): 从最高点回撤超过阈值
   - 移动止损 (`trailing_stop_loss`): 从近期高点回撤超阈值（更灵敏的动态止盈）
   - 最大回撤止损 (`max_drawdown_stop`): 从初始资金累计亏损超阈值
   - 基准相对止损 (`benchmark_stop_loss`): 累计落后大盘超阈值
   - 均线止损 (`ma_stop_loss`): 净值跌破N日均线超阈值
   - 逐板块卖出所有持仓，记录 STOP_LOSS 明细
3. **均线止盈**（可选，`ma_take_profit_thresholds` 非空时启用）:
   - 仅在盈利时触发（NAV > N日均线），按递减阈值阶梯式减仓
   - 首次触发时记录原始仓位，后续各级按原始仓位比例计算减仓量
   - 例：原始仓位33%，阈值[5%,3%,1%]，比例[30%,40%,30%]
     → 高于均线5%减30%(9.9%) → 高于3%减40%(13.2%) → 高于1%减30%(9.9%) → 清仓
   - 止盈级别在止损/紧急退出/熊市清仓时重置
4. **紧急退出**:
   - 逐板块卖出所有持仓：佣金 + 印花税 + 滑点
   - 记录每笔 EMERGENCY_EXIT 明细
5. **熊市空仓**:
   - 逐板块卖出所有持仓：佣金 + 印花税 + 滑点
   - 记录每笔 BEAR_EXIT 明细

### 6.3 回测结果统计

回测结果包含以下字段:

基础指标:
- `total_return`: 总收益率
- `annual_return`: 年化收益率
- `max_drawdown`: 最大回撤
- `sharpe_ratio`: 夏普比率
- `win_rate`: 胜率
- `trading_days`: 交易日数
- `trade_count`: 估算交易笔数
- `buy_count` / `sell_count`: 买入/卖出信号数

交易成本统计:
- `total_commission`: 累计佣金
- `total_stamp_tax`: 累计印花税
- `total_slippage_cost`: 累计滑点成本
- `total_trade_cost`: 累计总交易成本
- `trade_count_actual`: 实际交易笔数

新增统计指标:
- `turnover_rate`: 换手率（总交易金额 / 初始资金）
- `empty_days_pct`: 空仓天数占比
- `profit_factor`: 盈亏比（盈利总额 / 亏损总额）
- `max_consecutive_wins`: 最大连续盈利天数
- `max_consecutive_losses`: 最大连续亏损天数

仓位跟踪（return_full=True 时返回）:
- `nav_curve`: 逐日净值曲线（每个交易日一条，含 nav、benchmark、stop_loss）
- `daily_signals`: 每日信号列表，每条含 positions（每板块 weight+amount）、cash、total_position_value
- `position_changes`: 仓位调整明细列表（ADD/REDUCE/CLEAR/STOP_LOSS/EMERGENCY_EXIT/BEAR_EXIT），每条含原因（触发指标）。T+1 模式下 date 为实际成交日（信号日+1）

---

## 七、扩展设计

### 7.1 策略优化方向

- **多因子模型**: 引入动量因子、波动率因子、情绪因子
- **机器学习**: LSTM预测资金流向、强化学习优化仓位
- **自适应参数**: 根据市场状态动态调整权重（牛/熊/震荡）

### 7.2 信号增强

- **信号过滤**: 加入成交量确认、趋势线突破验证
- **仓位优化**: Kelly公式动态仓位
- **风险控制**: 行业相关性约束，避免集中度风险
