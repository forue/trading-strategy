# 策略引擎服务设计文档

> 版本: v2.2 | 更新日期: 2026-09-21 | 更新: 复盘行情源改为 `sector_kline.open` + `sector_capital_flow.index_close`（5.13）；新增信号落库与复盘统计；北向资金相关采集/展示已停用
>
> 历史版本: v2.0 (2026-09-06) T+1回测、19因子体系、动态权重

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
├── signal_tracker.py # 信号落库、收益回填与复盘统计（见 5.13）
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
| `market_breadth_floor` | 市场宽度绝对下限：上涨占比低于此值直接判 BEAR，不受头部板块评分影响（默认 0.25，设 0 关闭）。见 6.1.1 |
| `favorable_confirm_days` | 连续 N 天同向状态才确认（默认 2，防摇摆） |
| `max_empty_days` | 最大空仓天数，超时强制试探建仓（默认 10） |
| `bear_reentry_days` | BEAR 空仓回补门控天数（默认 0 = 关闭，出厂当日不再确认 BEAR 即回补）。设置 2~3：BEAR 清仓后须连续 N 日非 BEAR（当日 BULL 也不放行）才允许重新建仓，把弱反弹/下跌中继的首日追高延后以压回撤，代价是牺牲 BEAR 后快速回补的反弹收益 |
| `risk_free_rate` | 无风险利率（年化，默认 2%）：夏普基准 + 空仓资金日计息 |
| `capital_pct` | 组合总仓位上限（单板块上限另见 `max_position`） |
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
| `stop_loss_mode` | 止损模式：`fixed`=沿用多重固定止损（固定/移动/最大回撤/基准相对/均线）；`trend_break`=仅在组合净值有效跌破长周期均线（趋势破位）时清仓，跳过其余固定止损与紧急退出（避免牛市低点踏空） |
| `trend_confirm` | 趋势确认：开启后强趋势中跳过阶梯均线止盈（让利润奔跑），且牛市不再降低换仓门槛以减少无效调仓 |
| `trend_ma_days` | 趋势破位判定的长均线窗口天数（仅 `stop_loss_mode="trend_break"` 生效，默认 60） |

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
  hold_days = 10          # 持有10日（提高调仓缺口阈值后低频换手，让利润奔跑）
  stop_loss = 12%         # 固定回撤止损12%
  trailing_stop_loss = 8%  # 移动止损8%（从近期高点）
  max_drawdown_stop = 15%  # 最大回撤止损15%（从初始资金）
  capital_pct = 70%      # 基础资金使用比例（牛市可达100%）
  min_score_threshold = 1.5   # 最小评分阈值
  score_gap_threshold = 2.0   # 与相对缺口取较大（牛市×0.7，熊市×1.5）
  relative_score_gap_ratio = 0.12  # 相对评分缺口 = (最高候选分 - 持仓最高分) / 最高候选分，与绝对阈值取 max
  cooldown_days = 6       # 调仓冷却期（止损后冷却更久，避免崩盘中追高二次挨打）
  stop_loss_mode = "trend_break"  # 仅趋势破位止损（避免牛市低点踏空）
  trend_confirm = True            # 强趋势跳过止盈、减少调仓，让利润奔跑
  trend_ma_days = 60              # 趋势破位判定窗口
  ma_stop_loss = 8%               # 趋势破位阈值（跌破60日均线8%）
  keep_overlap = true     # 保持重叠持仓
  allow_empty = true     # 允许空仓（单日弱广度确认，见 6.1.1）
  min_score_keep = 2.5   # 保持持仓的最小评分
  # 市场状态防御（回测验证：2日连续确认几乎不触发，致6/7月崩盘单月跑输大盘10pp+）
  market_bear_threshold = 0.40    # 上涨板块占比 < 40% 且均涨为负判定为 BEAR
  favorable_confirm_days = 1      # 单日 BEAR 即确认离场（次日开盘执行）
  commission_rate = 0.3‰ # 佣金费率（万三）
  stamp_tax_rate = 1.0‰  # 印花税率（千一，仅卖出）
  slippage_rate = 1.0‰   # 滑点费率（千一）

买入逻辑:
  1. 按综合评分排序所有板块
  2. 选取评分最高的前2名（需满足min_score_threshold）
  3. 在 `capital_pct`（组合总仓位）目标下分配，单板块不超过 `max_position`，按 `use_inverse_vol_weights` 分配（否则等权）
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
  capital_pct = 60%      # 资金使用比例（2026-09调参：原30%暴露不足导致跑输大盘）
  min_score_threshold = 2.0   # 最小评分阈值
  score_gap_threshold = 1.0   # 与相对缺口取较大，见 StrategyParams
  cooldown_days = 2       # 调仓冷却期
  stop_loss_mode = "trend_break"  # 仅趋势破位止损（避免牛市低点踏空）
  trend_confirm = True            # 强趋势跳过止盈、减少调仓，让利润奔跑
  trend_ma_days = 60              # 趋势破位判定窗口
  ma_stop_loss = 8%               # 趋势破位阈值（跌破60日均线8%）
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
目标: 注重安全边际，收益稳健、回撤可控

参数:
  top_n = 3                # 取评分前3名（与稳健策略同量级，分散度适中）
  max_position = 30%       # 单板块仓位上限30%
  hold_days = 10           # 持有10日
  stop_loss = 8%           # 固定回撤止损8%
  trailing_stop_loss = 5%  # 移动止损5%
  ma_stop_loss = 5%        # 均线止损5%（跌破均线）
  capital_pct = 60%        # 资金使用比例（2026-09调参：原20%暴露不足、几乎长期空仓）
  valuation_pct_max = 50   # 估值分位≤50%（仅当存在估值分位数据时启用）
  min_score_threshold = 2.0   # 最小评分阈值
  score_gap_threshold = 1.0   # 与相对缺口取较大，见 StrategyParams
  cooldown_days = 3       # 调仓冷却期
  stop_loss_mode = "trend_break"  # 趋势破位止损（避免固定止损在正常波动中被反复打损）
  trend_confirm = True            # 趋势确认后减少止损触发
  trend_ma_days = 60              # 趋势破位判定窗口
  keep_overlap = true     # 保持重叠持仓
  allow_empty = true     # 允许空仓
  min_score_keep = 3.0   # 保持持仓的最小评分
  commission_rate = 0.3‰ # 佣金费率（万三）
  stamp_tax_rate = 1.0‰  # 印花税率（千一，仅卖出）
  slippage_rate = 1.0‰     # 滑点费率（千一）

买入逻辑:
  1. 按综合评分排序
  2. 筛选评分 ≥ min_score_threshold 的板块
  3. 选取前3名
  4. 单板块仓位上限30%，总仓位不超过100%
  5. 当回测/历史区间缺少估值分位数据（pe/pb_percentile 均缺失）时，
     自动退化为纯评分选股，避免"空有低估值预筛却无数据可用"导致长期空仓

> 估值分位数据可得性（2026-09-21）：板块 PE/PB 及分位由 data-collector 采集写入
> `sector_capital_flow`（口径与回填方式见 `docs/04-data-collector.md` 3.5）。
> 分位需 ≥10 个交易日样本，首次部署可调用 `POST /collect/backfill-valuation?days=365`
> 一次性回填 1 年历史，无需等待逐日积累。

卖出逻辑:
  1. 综合评分 < min_score_keep 的板块
  2. 趋势破位止损（组合净值有效跌破 trend_ma_days 均线超阈值）

信号示例:
  { direction: "BUY", sector: "银行", score: 6.12, position: 0.2,
    reason: "保守轮动: 综合评分6.12, 评分排名前3, 仓位上限30%" }
```

---

## 四、数据流与处理流程

### 4.1 信号计算流程

```
触发方式: 
  1. 定时触发: 任务调度中心 15:30 数据采集后链式触发（或15:35备用触发）
  2. 手动触发: 前端策略管理页触发 /calculate
  3. 登录触发: 认证服务登录成功后触发 /collect + /calculate

计算流程:
  1. 确定目标日期: signal_date（默认今天），并判断是否为交易日

  2. 按目标日期精确取板块数据（信号日期必须与数据日期一致，见 4.1.1）:
     └─ Redis 缓存 key: sector_capital_flow:{date}
     └─ 未命中时从 InfluxDB 按 (date, date) 精确查询（Flux stop 为 end+1 天，含当日）
     └─ 该日期无数据时：
        - allow_stale=false（默认，自动调度）→ 拒绝生成信号，返回 data_ready=false
        - allow_stale=true（手动/登录触发）→ 回退到最近有数据的交易日 D，并将信号日期修正为 D

  3. 从Redis读取当前持仓 (positions:{strategy_type})

  4. 构建截面上下文（各板块 `_history` 中的 `date` + `index_change_pct` 按日合并）
     历史序列一律以生效信号日期为界，避免混入信号日之后的走势

  5. 遍历每个板块：因子引擎计算 → 绝对综合分；当日板块数≥3 时再算截面分并按 `cross_section_alpha` 混合

  6. 按综合分排序，根据策略类型生成信号:
      - 市场过滤: `_market_is_favorable`（含市场宽度绝对下限，见 6.1.1）
      - 买入: 前 N 名且过 `min_score_threshold`；调仓需超过有效评分缺口（绝对 + 相对）
      - 卖出: 调出不在新组合中的标的（配合 keep_overlap 等）
      - 仓位: 总仓位 `capital_pct`（单板块上限 `max_position`），波动倒数或等权分配
      - 冷却期: 止损后 cooldown_days 内不建仓

  7. 信号处理（仅在数据就绪时执行）:
      a. 更新持仓到Redis (positions:{type}, TTL: 7天)
         - 仅在本次确实产生 BUY/SELL 信号时更新；无信号表示"维持现有持仓"，绝不写空仓位
      b. 写入Redis缓存 (key: signals:{type}:{date}, TTL: 7天)
      c. 信号落库 PostgreSQL (trade_signals，按当日+唯一键幂等去重，见 5.13)
      d. 通过RabbitMQ发布 signals_generated 事件
      e. 信号通知服务消费事件 → WebSocket推送给前端
```

#### 4.1.1 信号日期与数据日期强一致

> 背景：2026-09-11 曾出现"用 9/10 数据生成 9/11 信号"的问题——采集任务与备用计算任务因 misfire 并发执行，
> 策略在当日数据入库前读到 T-1 快照，且该快照被写入全局 `latest` 缓存（TTL 1h），
> 导致后续两个策略同样使用 T-1 数据，最终推送了基于 9/10 资金流的银行/证券买入信号，
> 而 9/11 真实行情是银行 -1.09%、证券 -3.60% 且资金转为净流出。

约束与实现:
- **约束**：信号日期必须等于所用板块数据的日期，禁止用 T-1 数据生成 T 日信号
- 板块快照缓存由全局键 `sector_capital_flow:latest` 改为按日期分键 `sector_capital_flow:{date}`，杜绝跨交易日复用
- `/calculate` 默认严格模式（`allow_stale=false`）：当日数据未入库或非交易日时返回 `data_ready=false`，
  不写信号缓存、不动持仓、不推送事件，由调度层保留重试机会
- 手动/登录触发可显式传 `allow_stale=true`：回退到最近有数据的交易日 D，并把**信号日期一并修正为 D**，
  保证"信号日期 == 数据日期"，不会出现"周六信号用周五数据"的错配
- 回退场景下若 D 已有信号，默认直接返回已有信号（`force=true` 才重算），避免重复触发覆盖当日持仓

### 4.2 消息发布格式

```json
{
  "event": "signals_generated",
  "strategy_type": "AGGRESSIVE",
  "signal_date": "2026-04-18",
  "count": 5,
  "position_status": "HOLD",
  "empty_reason": "",
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
  - scheduler_times: 调度时间配置 (默认 {"collect":"15:30","calculate":"15:35","north_bound":"16:00"})

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
POST /calculate?strategy_type=AGGRESSIVE&signal_date=2026-04-18&allow_stale=false&force=false
```

| 参数 | 默认 | 说明 |
|------|------|------|
| `strategy_type` | 必填 | AGGRESSIVE / MODERATE / CONSERVATIVE |
| `signal_date` | 今天 | 期望的信号日期 |
| `allow_stale` | `false` | 目标日期无数据（非交易日或数据未入库）时，允许回退到最近有数据的交易日，并同步修正信号日期 |
| `force` | `false` | 回退场景且该日期已有信号时，强制重算覆盖（默认直接返回已有信号） |

响应:
```json
{
  "code": 200,
  "message": "策略计算完成，共生成 2 条信号",
  "data": [ ... signals ... ],
  "strategy_type": "AGGRESSIVE",
  "signal_date": "2026-04-18",
  "requested_date": "2026-04-18",
  "data_ready": true,
  "stale": false,
  "note": ""
}
```

- `data_ready=false`：目标日期无可用数据且未允许回退，未生成任何信号（不写缓存、不动持仓、不推送）
- `stale=true`：`signal_date` 已回退到最近有数据的交易日（与 `requested_date` 不同）
- `position_status`：`HOLD`=持有、`EMPTY`=空仓、`NO_DATA`=未计算
- `market_regime`：`BULL` / `NEUTRAL` / `BEAR`
- `empty_reason`：空仓原因（如"市场判定熊市，空仓观望（上涨板块占比6%, 平均涨跌-2.04%）"）

#### 5.1.1 空仓必须被显式表达

> 背景：市场判定 BEAR 时，轮动逻辑原先直接返回空信号列表，接口表现为"什么都没发生"——
> 前端无法区分"今天没算"和"算出来空仓"，且持有仓位时不会卖出，市场转差也无法离场。

语义约定:
- 空仓不是"无信号"，而是一个**明确的状态**，必须同时满足：
  1. 接口返回 `position_status=EMPTY` 与 `empty_reason`
  2. 持有仓位且市场已连续确认 BEAR 时，输出**清仓 SELL 信号**（而非静默不动）
- 连续确认：按 `favorable_confirm_days` 判定（激进=1 即单日确认，稳健/保守=2），
  与回测的 BEAR 确认口径一致；未达确认天数时只"不买入"，不主动卖出，避免假信号频繁清仓
- 回测路径不传 `regime_history`，保持"只不买入"的原行为，其熊市清仓仍由回测自身的 `BEAR_EXIT` 流程处理，
  因此本次改动不影响已验证的回测结果
- 当日市场状态写入 `market_regime:{strategy_type}:{date}`（TTL 30 天），供跨交易日连续确认
- **重算保留清仓留痕**：`/calculate` 写缓存前，若本次重算得到空仓（无任何信号），而该日缓存中
  已存在清仓 SELL 记录（`direction=SELL` 且 `reason` 含"清仓"），则保留这些清仓记录并同步写入
  `:status`（`position_status=EMPTY`、`empty_reason` 取清仓理由），避免"空仓重算"用空列表
  覆盖掉"当日已清仓"的历史事实
- **日历空仓标记**：`/signals/calendar` 对"已计算但空仓"的日期输出标记记录
  （`direction=EMPTY` / `is_empty_position=true`），供前端日历以独立颜色区分空仓与未计算，
  详见 `docs/06-signal-notification.md` 5.3

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

> 注意：`params` 支持部分字段提交，后端仅合并已提交字段（`exclude_unset`），未提交字段保留原值，避免前端部分提交将调仓阈值/止损模式/仓位比例等关键参数意外重置为默认值。

### 5.3.1 恢复默认配置

```
POST /configs/{config_id}/reset
```

将指定策略的 `name` / `is_active` / `params` 一键恢复为代码内置出厂默认值（模块启动时的 `DEFAULT_CONFIG_TEMPLATES` 快照），并同步写入 Redis 持久化。前端策略卡片提供"恢复默认"按钮调用此接口。

### 5.4 获取今日信号

```
GET /signals/today?strategy_type=AGGRESSIVE

响应: 从Redis缓存读取，无则返回空数组
```

### 5.4.1 获取策略持仓

```
GET /positions?strategy_type=AGGRESSIVE

响应: 从 Redis（positions:{strategy_type}）读取当前持仓权重
{
  "code": 200,
  "data": {
    "positions": {"881101": 0.15, "881105": 0.12},
    "total_weight": 0.27,
    "count": 2
  }
}
```

- 只读暴露，持仓由 `/calculate` 计算流程写入（键 `positions:{strategy_type}`，TTL 7 天）；
- AI 决策复盘（`DailyReviewDataCollector`）与 Agent 工具 `get_current_positions` 均调用此接口。

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

> 注意：`params` 为可选字段级覆盖，语义同 5.3「部分字段提交」。未提交字段会保留该策略当前配置值（merge），不会回落为模型默认值——例如仅提交 `top_n`/`hold_days`/`stop_loss` 等表单可见字段时，`stop_loss_mode`、`min_score_threshold`、`cooldown_days` 等仍取策略配置值，确保回测结果与配置页保存的配置一致。

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

### 5.13 信号复盘统计

> 实现在 `signal_tracker.py`。解决"信号只存 Redis（TTL 7 天）、`trade_signals` 长期空置、无法复盘胜率"的问题，
> 为前端「策略复盘」页提供数据。

**存储**

| 表 | 说明 |
|----|------|
| `trade_signals` | 信号落库（`/calculate` 生成信号后写入，唯一键去重），并作为幂等自愈的持久层 |
| `signal_outcomes` | 信号结果回填表，唯一键 `(signal_date, strategy_type, sector_code, direction, horizon_days)`；索引 `idx_signal_outcomes_perf` |

建表在服务启动时由 `ensure_schema()` 幂等执行（失败降级，不影响主链路）。

**统计口径**

信号在 T 日收盘后（15:35）生成，当天已无法成交，因此：

- 持有期 `HORIZONS = (1, 3, 5, 10)` 交易日，默认口径 5 日
- 成交假设：**T+1 开盘价买入，第 T+horizon 个交易日收盘价卖出**（entry = `open(T+1)`、
  exit = `close(T+horizon)`）。不使用 T 日收盘价作基准——那等于假设收盘前已知信号，属于前视偏差
- 三层收益全部落库，便于审计：

  | 字段 | 含义 |
  |------|------|
  | `forward_return` | 板块价格变动 `exit/entry − 1`，未调整方向、未扣成本 |
  | `direction_return` | 方向收益 = `forward_return ×`（买入 +1 / 卖出 −1） |
  | `net_return` | 净收益 = `direction_return − cost_rate` |

- **卖出信号必须按方向取号**：SELL 后板块下跌才是策略盈利。若直接拿板块价格变动当策略收益，
  "胜率"与"命中率"会互相矛盾（同一份数据里出现"胜率 87.5% / 命中率 50%"）
- 成本 `cost_rate` 取自策略配置（往返 = 2×(佣金+滑点) + 印花税，见第六章），与回测同口径；
  复盘是收益率口径，不考虑回测里"佣金 5 元下限"的绝对金额约束
- **"胜率"与"准确率"旧口径已合并为命中率**：命中率 = `direction_return > 0` 的占比（方向判定正确率）
- **持有期未走完的信号计 `pending`**；`open(T+1)` 缺失的信号计 `no_quote`，两者都不进入命中率分母
- 行情序列由两个数据源合并（缺一不可）：
  - **收盘价**取 `sector_capital_flow.index_close`，与策略因子、打分同源
  - **开盘价**取 `sector_kline.open`（同花顺行业指数真实 OHLC），对 K 线表缺失的日期回退用资金流表的 `open`
  - `sector_capital_flow` 的 `open` 只在手动调用 `/collect/history` 时才写入，日常定时采集为空字段；
    若以它作为唯一开盘价来源，绝大多数信号会因取不到 T+1 开盘价而全部落空（实测 `evaluated=0`、`no_quote=23`）
  - `sector_kline` 由调度器每日刷新最近 15 个自然日的 OHLC（见 `docs/08-scheduler.md` 3.6），
    既写入当日行情，也能补齐此前数据源未就绪而缺失的开盘价
- 累计收益曲线按**结算日** `end_date` 聚合，且用**算术累计**（非复利连乘）：同一时刻存在
  horizon 个头寸，按每日满仓复利会放大波动，该曲线仅用于观察信号质量的时序趋势

**接口**

```
GET  /signals/performance?strategy_type=MODERATE&horizon_days=5&start_date=&end_date=
     - 复盘统计：signal_count / evaluated_count / pending_count / cost_rate /
       hit_count / hit_rate / avg_return（净）/ avg_return_gross（毛）/ median_return /
       best_return / worst_return / profit_factor（净）/ profit_factor_gross /
       buy / sell（分方向命中率与净/毛收益）/ monthly（月度命中率）/ sectors（板块）/
       equity_curve（按结算日算术累计）/ horizons

POST /signals/sync?lookback_days=7
     - 从 Redis 信号缓存补录到 trade_signals（缓存 TTL 内可用，用于历史信号回填入库）

POST /signals/backfill?lookback_days=365
     - 为已走完 1/3/5/10 交易日持有期的信号结算，写入 signal_outcomes（幂等）
     - 返回 signals / evaluated / pending / no_quote，其中 pending、no_quote 按"信号"计数
     - 由调度器在采集/计算链路成功后及每次启动时触发，详见 docs/08-scheduler.md 3.6
```

> 口径变更迁移：`signal_outcomes` 新增 `direction_return` / `cost_rate` / `net_return` 三列，
> 启动时由 `ensure_schema()` 幂等补列，并清除旧口径数据（`direction_return IS NULL`），
> 随后由回填链路重算。该表是纯派生数据，可由 `trade_signals` + 行情完整重建。

前端页面为「策略复盘」（`frontend/src/views/Review.vue`，路由 `/review`），提供策略档位与持有期切换、
总览指标卡（命中率 / 平均净收益 / 平均毛收益 / 盈亏比）、分方向命中率、月度命中率、
板块明细与累计净收益曲线；页头标注成交口径与实际使用的往返成本率。

---

## 六、回测逻辑与交易成本

### 6.1 回测算法流程

```
成交模型（全部交易统一为 T 日收盘决策 → T+1 开盘按开盘价成交）:

     i. 开盘执行昨日挂起的订单:
        - 风险单优先（STOP_LOSS / EMERGENCY_EXIT / BEAR_EXIT / TAKE_PROFIT），其次调仓单
        - 卖出：按 T+1 开盘价成交
        - 买入：金额 = 目标市值 - 当前市值，受可用现金约束（不允许透支）
        - 继续持有判断只使用信号日(T日)已公开的评分与涨跌，杜绝未来函数

     ii. 收盘按份额逐仓重估（市值记账，权重随价格自然漂移）:
        - 组合权益 = 现金 + Σ 份额 × 收盘价
        - 已卖出份额当日只贡献 prev_close→open 的隔夜跳空
        - 未交易持仓贡献 prev_close→close 的全天涨跌
        - 新建仓份额贡献 open→close 的日内收益
        - 现金按日无风险利率计息（空仓日收益 = 无风险利率日收益）

     iii. 风险检查（触发后挂单，次日开盘执行，不在触发日收盘价成交）:
        - 多重止损 / 紧急退出 / 熊市清仓 / 阶梯均线止盈

     iv. 更新冷却期计数器

     v. 收盘后生成信号（记录待执行，不立即成交）:
        - 信号日 = D，记录 pending_rebalance（含信号日各板块涨跌）
        - 成交日 = D+1 开盘，实际执行

  5. 计算绩效指标:
     - 总收益率 = 最终权益 / 初始资金 - 1
     - 年化收益率 = (1 + 总收益率)^(252/交易日数) - 1
     - 最大回撤 = 基于逐日NAV计算
     - 夏普比率 = (日均超额收益 × 252) / (超额收益标准差 × √252)，超额收益 = 日收益 - 无风险日利率
     - 胜率 = 盈利平仓笔数 / 平仓笔数（交易级）；日胜率另见 daily_win_rate
     - 年化双边换手率、空仓天数占比、盈亏比、最大连续盈/亏天数
```

#### 记账与价格口径

- 采用份额记账：`positions = {板块: {shares, avg_cost}}`，目标仓位由信号给出的权重换算为金额后再折算为份额。
- 价格序列优先取数据源的 `index_close` / `open`；缺失时用最近收盘价与 `index_change_pct` 合成，保证只有涨跌幅的数据源也能得到自洽价格。
- 缺少 `open` 时按 `prev_close` 处理（隔夜跳空为 0）。
- 因子历史预加载回溯 400 自然日（约 270 个交易日），覆盖最长因子窗口（trend 60日均线、technical 35日）。

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
| BEAR | 上涨占比 < 40% 且 avg < 0 | 空仓（单日触发确认），score_gap × 1.5 |

**市场宽度绝对下限**（优先于上表判定）：上涨板块占比低于 `market_breadth_floor`（默认 0.25）时，
无论头部板块评分多高都直接判定 BEAR。

> 背景：2026-09-10 全市场仅 11.1% 板块上涨、主力净流出 802 亿，银行/证券因"相对抗跌 + 资金逆势流入"
> 在截面打分中拿到最高分（capital_flow 9.17/9.15），按旧规则 top10 有达标标的即判 NEUTRAL 放行买入，
> 次日证券 -3.60%、银行 -1.09%。这是典型的**相对动量陷阱**：全市场普跌时"相对少跌"并不等于绝对强势。

回测验证（MODERATE，覆盖两个独立区间）:

| `market_breadth_floor` | 2026-03-11~2026-09-11 | 2025-11-11~2026-05-11 |
|---|---|---|
| 0（旧行为） | +0.23%，夏普 0.03，回撤 13.48% | — |
| **0.25（默认）** | +12.85%，夏普 1.09，回撤 12.74% | **+16.48%，夏普 1.41，回撤 20.16%** |
| 0.30 | +16.96%，夏普 1.41，回撤 13.05% | **+0.23%，夏普 0.04，回撤 27.71%** |

> 阈值 0.30 虽在区间①更优，但在区间②严重劣化（收益 16.48%→0.23%、回撤 20.2%→27.7%），
> 属于对单区间的过拟合；0.25 在两个区间均稳健，故作为默认值。需要更保守时可经 `/configs` 调整。

空仓管理:
- 确认: AGGRESSIVE 连续1天 BEAR 即触发空仓（`favorable_confirm_days=1`）；其余策略默认连续2天
- 恢复: 当日市场不再确认 BEAR（非连续 `favorable_confirm_days` 天 BEAR）即恢复回补
- 回补门控(可选): 若需压制"弱反弹首日追高、下跌中继二次套牢"型回撤，可开启 `bear_reentry_days`（见 2.3），
  BEAR 清仓后须连续 N 日非 BEAR（当日 BULL 也不放行）才允许重新建仓。
  双窗口回测: `bear_reentry_days=3` 将 2026-07 月收益从 -19.5% 修复为 -2.7%、近一年 max_drawdown 从 23.1% 压至 15.0%，
  但近两年总收益从 +52.0% 降至 +7.3%（两年 21 次 BEAR 空仓中 14 次为假信号、快速回补贡献主要收益），故默认保持 0。
  开启示例（`PUT /configs/{id}`，body 需含必填字段，params 为合并式更新、其余参数保留）:
  ```json
  {"strategy_type": "AGGRESSIVE", "name": "激进策略", "is_active": true,
   "params": {"bear_reentry_days": 3}}
  ```
  回测验证用 `POST /backtest` 的 `params` 覆盖同名字段即可（无需改动配置）
- 超时: 空仓超过 `max_empty_days`（默认10）天且市场为 NEUTRAL → 强制50%仓位建仓（回补门控开启时超时试探仍会放行）
- 紧急退出: 持仓板块单日跌幅 > 5% → 次日开盘清仓（跳过 hold_days，成交日承担触发日全天跌幅）

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
   - 触发后挂单，**次日开盘**逐板块卖出所有持仓，记录 STOP_LOSS 明细（成交日为触发日+1）
  - 趋势破位止损（`stop_loss_mode="trend_break"`）: 仅在组合净值有效跌破 `trend_ma_days` 日均线超 `ma_stop_loss` 阈值时清仓，其余固定止损（固定/移动/最大回撤/基准相对/均线）与紧急退出均跳过。用于减少牛市中因短期回调过早离场导致的踏空；大级别熊市仍由 `_market_is_favorable` 空仓保护
3. **均线止盈**（可选，`ma_take_profit_thresholds` 非空时启用）:
   - 仅在盈利时触发（NAV > N日均线），按递减阈值阶梯式减仓
   - 首次触发时记录原始份额，后续各级按原始份额比例计算减仓量，次日开盘执行
   - 例：原始份额100份，阈值[5%,3%,1%]，比例[30%,40%,30%]
     → 高于均线5%减30份 → 高于3%减40份 → 高于1%减30份 → 清仓
   - 止盈级别在止损/紧急退出/熊市清仓时重置
4. **紧急退出**:
   - 持仓板块单日跌幅 > 5% 触发，次日开盘逐板块卖出所有持仓：佣金 + 印花税 + 滑点
   - 触发当日仍承担该板块全天跌幅，记录每笔 EMERGENCY_EXIT 明细
5. **熊市空仓**:
   - 连续确认 BEAR 后挂单，次日开盘逐板块卖出所有持仓：佣金 + 印花税 + 滑点
   - 记录每笔 BEAR_EXIT 明细

### 6.3 回测结果统计

回测结果包含以下字段:

基础指标:
- `total_return`: 总收益率
- `annual_return`: 年化收益率
- `max_drawdown`: 最大回撤
- `sharpe_ratio`: 夏普比率（以 `risk_free_rate` 为无风险利率，空仓期按无风险利率计息；波动趋零时置 0）
- `win_rate`: 胜率（交易级：盈利平仓笔数 / 平仓笔数）
- `daily_win_rate`: 日胜率（正收益交易日占比）
- `trading_days`: 交易日数
- `trade_count`: 估算交易笔数
- `buy_count` / `sell_count`: 买入/卖出信号数
- `closed_trades`: 平仓笔数（用于胜率分母）
- `risk_free_rate`: 本次回测使用的无风险利率

交易成本统计:
- `total_commission`: 累计佣金
- `total_stamp_tax`: 累计印花税
- `total_slippage_cost`: 累计滑点成本
- `total_trade_cost`: 累计总交易成本
- `trade_count_actual`: 实际交易笔数
- `total_traded_amount`: 累计成交额（买卖双边）

新增统计指标:
- `turnover_rate`: 年化双边换手率 = 累计成交额 / 平均资产规模 / 年数
- `empty_days_pct`: 空仓天数占比
- `profit_factor`: 盈亏比（平仓已实现盈利总额 / 亏损总额，含交易成本）
- `max_consecutive_wins`: 最大连续盈利天数
- `max_consecutive_losses`: 最大连续亏损天数

仓位跟踪（return_full=True 时返回）:
- `nav_curve`: 逐日净值曲线（每个交易日一条，含 nav、benchmark、stop_loss）
- `daily_signals`: 每日信号列表，每条含 positions（每板块 weight+amount，按收盘市值计算）、cash、total_position_value
- `position_changes`: 仓位调整明细列表（ADD/REDUCE/CLEAR/HOLD/STOP_LOSS/EMERGENCY_EXIT/BEAR_EXIT/TAKE_PROFIT），每条含原因（触发指标）。T+1 模式下 date 为实际成交日（信号日+1）
- `portfolio_snapshots`: 有成交日的收盘持仓快照（各板块权重、市值、当日涨跌与贡献）

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

---

## 八、单日信号与调参记录（2026-09）

### 8.1 算法修复

1. **趋势止损模式持仓锁定不再冻结**：原实现中 `stop_loss_mode="trend_break"` 时持仓锁定期倒计时被跳过，持仓被永久锁定（`position_hold_counter` 恒为初始值），导致调仓逻辑几乎失效。已修复为：趋势止损模式下锁定期每日照常倒计时，固定止损模式单独保留"单日跌幅>5% 紧急退出"。
2. **保守策略估值预筛无数据时不空仓**：当 pe/pb 估值分位数据整日缺失时，保守策略此前直接返回空信号（无持仓可用），表现为长期空仓。现改为当日无估值数据时自动退化为综合评分选股，不长期空仓跑输大盘。
3. **单日快照补充板块历史序列**：实时 `/calculate` 输入为 Redis 当日快照（无 `_history`），走势/技术类因子（ma_trend / mfi / vol_ratio 等）在因子引擎中因数据缺失被剔除。现改为在评分前按信号日期从板块历史 K 线（含资金流字段）补齐 `_history`，使单日信号同样结合走势与技术指标给出。
4. **信号日期与数据日期强一致**：板块快照缓存由全局 `sector_capital_flow:latest` 改为按日期分键 `sector_capital_flow:{date}`；`/calculate` 新增 `allow_stale` / `force` 参数，默认严格模式下当日数据未入库即拒绝生成信号，手动触发可回退到最近有数据的交易日并同步修正信号日期。详见 4.1.1。
5. **空信号不再清空持仓**：此前一次计算未产生任何信号时，仍会用空仓位覆盖 Redis `positions:{type}`，导致真实持仓被凭空清零（2026-09-11 首轮计算即触发），进而使下一轮被误判为"空仓首次建仓"而跳过评分缺口门槛直接买入。现仅在确实产生 BUY/SELL 信号时才更新持仓。
6. **市场宽度绝对下限**：新增 `market_breadth_floor`（默认 0.25），普跌行情下无论头部板块评分多高都判 BEAR，修复"全市场净流出时相对抗跌板块被误判为强势"的相对动量陷阱。回测数据与阈值敏感度见 6.1.1。
7. **空仓显式化**：市场判定 BEAR 时不再"什么都不返回"——接口输出 `position_status=EMPTY` 与空仓原因；持有仓位且连续确认 BEAR 时输出清仓 SELL 信号。回测路径行为保持不变（见 5.1.1）。

### 8.2 策略默认参数调整（全窗口基准：上证指数 +17.25%，2025-01-02 ~ 2026-09-04）

| 策略 | 主要参数调整 | 策略收益 | 基准收益 | 最大回撤 | 夏普 | 说明 |
|---|---|---|---|---|---|---|
| 激进 | `hold_days` 5→10；`score_gap_threshold` 1.0→2.0；`relative_score_gap_ratio` 0.06→0.12 | +68.8% | +17.25% | -23.1% | 1.25 | 拉长持有期 + 提高调仓缺口，减少高频换手 |
| 稳健 | `capital_pct` 0.3→0.6 | +33.7% | +17.25% | -19.7% | 0.83 | 提高资金使用率，解决暴露不足 |
| 保守 | `top_n` 5→3；`capital_pct` 0.2→0.6；`stop_loss_mode` "fixed"→"trend_break"；`trend_confirm=True` | +30.7% | +17.25% | -15.9% | 0.96 | 修正固定止损高频打损 + 空仓问题 |
