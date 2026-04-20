# 策略引擎服务设计文档

> 版本: v1.1 | 更新日期: 2026-04-19 | 更新内容: 添加交易成本功能，修复回测算法

---

## 一、模块概述

策略引擎是系统的核心模块，负责基于板块资金流数据计算三档轮动策略的综合评分，输出每日买卖信号。采用四维加权评分模型，差异化输出激进/稳健/保守三种策略信号。

| 属性 | 值 |
|------|-----|
| 服务名 | backend-strategy |
| 端口 | 8002 |
| 语言 | Python 3.11 |
| 框架 | FastAPI |
| 依赖 | InfluxDB(数据源) + Redis(缓存) + RabbitMQ(通知) |
| 核心算法 | 板块资金轮动评分模型 |

---

## 二、评分模型设计

### 2.1 评分维度

| 维度 | 含义 | 计算方式 | 分值范围 |
|------|------|----------|---------|
| **资金强度** | 主力+北向资金净流入的绝对强度 | 标准化函数映射到0-10 | 0-10 |
| **资金斜率** | 过去N日资金净流入的趋势方向 | 线性回归斜率+强度修正 | 0-10 |
| **相对强弱** | 板块指数涨幅相对大盘的超额收益 | 涨跌幅线性映射 | 0-10 |
| **估值分位** | 当前估值在历史中的百分位 | 历史分位数计算 | 0-10 |

### 2.2 三档权重矩阵

| 维度 | 激进 | 稳健 | 保守 |
|------|------|------|------|
| 资金强度 | **60%** | 40% | 30% |
| 资金斜率 | 30% | 25% | 20% |
| 相对强弱 | 10% | 25% | 20% |
| 估值分位 | - | 10% | **30%** |

**设计逻辑**:
- 激进策略侧重资金强度（追强势），忽略估值
- 稳健策略均衡各维度，兼顾趋势与安全
- 保守策略最重视估值分位（买便宜），降低资金追涨权重

### 2.3 评分计算公式

```
综合评分 = Σ(维度得分 × 维度权重)

其中:
  资金强度得分 = normalize(main_net_inflow) × 0.7 + normalize(north_net_inflow) × 0.3
  
  normalize(flow) = 5.0 + flow / (2 × 10^8)
                   钳位到 [0, 10]
                   (以1亿为基准单位)

  资金斜率得分 = 5.0 + sign(main_net_inflow) × min(|main_net_inflow| / 10^8, 5.0)

  相对强弱得分 = 5.0 + index_change_pct × 1.5

  估值得分 = 历史分位数映射 (0-10)
```

---

## 三、三档策略逻辑

### 3.1 激进轮动策略

```
目标: 追求最大收益，高频率满仓轮换

参数:
  top_n = 2           # 仅取前2名
  max_position = 100% # 满仓
  hold_days = 3       # 持有1-3日
  stop_loss = 5%      # 止损5%
  capital_pct = 50%   # 资金使用比例
  commission_rate = 0.3‰ # 佣金费率（万三）
  stamp_tax_rate = 1.0‰  # 印花税率（千一，仅卖出）
  slippage_rate = 1.0‰   # 滑点费率（千一）

买入逻辑:
  1. 按综合评分排序所有板块
  2. 选取评分最高的前2名
  3. 等分仓位(各50%)买入
  4. 生成BUY信号

卖出逻辑:
  1. 综合评分 < 4.0 的板块
  2. 生成SELL信号

信号示例:
  { direction: "BUY", sector: "银行", score: 8.23, position: 0.5,
    reason: "激进轮动: 资金强度排名#1, 综合评分8.23, 建议满仓轮换持有3日" }
```

### 3.2 稳健轮动策略

```
目标: 平衡收益与风险，半仓分散持有

参数:
  top_n = 3           # 取前3名
  max_position = 50%  # 半仓
  hold_days = 5       # 持有5日
  stop_loss = 3%      # 止损3%
  capital_pct = 30%   # 资金使用比例
  commission_rate = 0.3‰ # 佣金费率（万三）
  stamp_tax_rate = 1.0‰  # 印花税率（千一，仅卖出）
  slippage_rate = 1.0‰   # 滑点费率（千一）

买入逻辑:
  1. 按综合评分排序
  2. 选取前3名
  3. 等分仓位(各16.7%，总计50%)买入

卖出逻辑:
  1. 综合评分 < 3.0 的板块
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
  stop_loss = 2%           # 止损2%
  capital_pct = 20%        # 资金使用比例
  valuation_pct_max = 50   # 估值分位≤50%
  commission_rate = 0.3‰   # 佣金费率（万三）
  stamp_tax_rate = 1.0‰    # 印花税率（千一，仅卖出）
  slippage_rate = 1.0‰     # 滑点费率（千一）

买入逻辑:
  1. 按综合评分排序
  2. 筛选评分 ≥ 5.0 的板块
  3. 选取前5名
  4. 单板块仓位上限30%，总仓位不超过100%

卖出逻辑:
  1. 综合评分 < 3.5 的板块
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
  1. 定时触发: 任务调度中心 15:05 调用 POST /calculate
  2. 手动触发: 前端策略管理页触发

计算流程:
  1. 从Redis获取最新板块数据 (sector_capital_flow:latest)
     └─ 无缓存时，返回空信号（无数据）

  2. 遍历每个板块数据，计算四维评分:
     a. 资金强度得分 (normalize main_flow + north_flow)
     b. 资金斜率得分 (趋势方向判断)
     c. 相对强弱得分 (涨跌幅映射)
     d. 估值得分 (历史分位)

  3. 按策略权重计算综合评分:
     AGGRESSIVE: strength*0.6 + slope*0.3 + rs*0.1
     MODERATE:   strength*0.4 + slope*0.25 + rs*0.25 + val*0.1
     CONSERVATIVE: strength*0.3 + slope*0.2 + rs*0.2 + val*0.3

  4. 按评分排序，根据策略类型生成信号:
     - 买入: 选取前N名，计算仓位比例
     - 卖出: 低于阈值的板块

  5. 信号处理:
     a. 写入Redis缓存 (key: signals:{type}:{date}, TTL: 24h)
     b. 通过RabbitMQ发布 signal.generated 事件
     c. 信号通知服务消费事件 → WebSocket推送给前端
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

---

## 五、接口设计

### 5.1 触发策略计算

```
POST /api/strategy/calculate?strategy_type=AGGRESSIVE&signal_date=2026-04-18

响应:
{
  "code": 200,
  "message": "策略计算完成",
  "data": [ ... signals ... ]
}
```

### 5.2 获取策略配置

```
GET /api/strategy/configs

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
PUT /api/strategy/configs/{id}
Content-Type: application/json

请求:
{
  "strategy_type": "AGGRESSIVE",
  "name": "激进轮动策略",
  "params": { "top_n": 3, "max_position": 0.8, ... }
}
```

### 5.4 获取今日信号

```
GET /api/strategy/signals/today?strategy_type=AGGRESSIVE

响应: 从Redis缓存读取，无则返回空数组
```

### 5.5 策略回测

```
POST /api/strategy/backtest
Content-Type: application/json

请求:
{
  "strategy_type": "MODERATE",
  "start_date": "2025-04-18",
  "end_date": "2026-04-18",
  "initial_capital": 1000000
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
    // 交易成本统计
    "total_commission": 1250.50,
    "total_stamp_tax": 850.20,
    "total_slippage_cost": 420.30,
    "total_trade_cost": 2521.00,
    "trade_count_actual": 52,
    "nav_curve": [
      { "date": "2025-04-18", "nav": 1000000, "benchmark": 1000000, "stop_loss": false },
      ...
    ]
  }
}
```

---

## 六、回测逻辑与交易成本

### 6.1 回测算法流程

```
回测流程（基于真实历史数据逐日回放）:
  1. 从InfluxDB查询指定日期范围的板块历史数据
  2. 按日期排序，逐日执行策略逻辑
  3. 每日执行步骤:
     a. 计算当日收益（基于昨日持仓，用今日涨跌幅）
     b. 更新资本（加上当日收益）
     c. 更新历史最高净值
     d. 止损检查（回撤超线 → 卖出所有持仓 + 计算交易成本）
     e. 持仓天数递减（有持仓且计数器>0时才递减）
     f. 更新冷静期（止损冷静期递减）
     g. 检查调仓（冷静期结束且持仓天数≤0）
        - 计算卖出旧持仓成本
        - 计算买入新持仓成本  
        - 扣除总交易成本
     h. 记录净值曲线
  4. 计算绩效指标:
     - 总收益率 = 最终资本 / 初始资本 - 1
     - 年化收益率 = (1 + 总收益率)^(252/交易日数) - 1
     - 最大回撤 = 基于净值曲线计算
     - 夏普比率 = (日均收益 × 252) / (日收益标准差 × √252)
     - 胜率 = 正收益天数占比
```

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
2. **止损触发**:
   - 卖出所有持仓：佣金 + 印花税 + 滑点
   - 没有买入成本

### 6.3 回测结果统计

回测结果包含以下交易成本统计字段:
- `total_commission`: 累计佣金
- `total_stamp_tax`: 累计印花税  
- `total_slippage_cost`: 累计滑点成本
- `total_trade_cost`: 累计总交易成本
- `trade_count_actual`: 实际交易笔数

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
