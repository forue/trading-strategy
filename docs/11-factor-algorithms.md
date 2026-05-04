# 量化因子算法参考文档

> 版本: v1.1 | 更新日期: 2026-05-05 | 更新: 持续性因子截面定义与实现对齐

---

## 一、技术指标因子

### 1.1 RSI (Relative Strength Index) 相对强弱指标

**原理**: 衡量价格变动的速度和幅度，判断超买超卖状态。

**公式**:
```
RS = 平均上涨幅度 / 平均下跌幅度
RSI = 100 - 100 / (1 + RS)

其中:
  平均上涨幅度 = SMA(max(close - prev_close, 0), period)
  平均下跌幅度 = SMA(max(prev_close - close, 0), period)
  period = 14 (默认)
```

**评分映射**:
```
RSI < 30  → 超卖 → 得分 8-10 (买入机会)
RSI 30-50 → 偏弱 → 得分 5-7
RSI 50-70 → 偏强 → 得分 3-5
RSI > 70  → 超买 → 得分 0-2 (卖出信号)
```

**参考**: Wilder, J. Welles (1978). New Concepts in Technical Trading Systems.

---

### 1.2 MACD (Moving Average Convergence Divergence) 指数平滑异同移动平均线

**原理**: 通过快慢均线的差值判断趋势方向和强度。

**公式**:
```
EMA_fast = EMA(close, fast_period)     # fast_period = 12
EMA_slow = EMA(close, slow_period)     # slow_period = 26
DIF = EMA_fast - EMA_slow
DEA = EMA(DIF, signal_period)          # signal_period = 9
MACD_bar = 2 × (DIF - DEA)            # 柱状图

EMA计算:
  EMA_today = close × k + EMA_yesterday × (1 - k)
  k = 2 / (period + 1)
```

**评分逻辑**:
```
DIF > DEA 且 MACD_bar > 0     → 多头 → 得分 7-10
DIF > DEA 且 MACD_bar 递减    → 多头减弱 → 得分 4-6
DIF < DEA 且 MACD_bar < 0     → 空头 → 得分 0-3
DIF < DEA 且 MACD_bar 递增    → 空头减弱 → 得分 4-6
金叉 (DIF上穿DEA)             → 买入信号 → +2 分
死叉 (DIF下穿DEA)             → 卖出信号 → -2 分
```

**参考**: Gerald Appel (1979). Technical Analysis: Power Tools for Active Investors.

---

### 1.3 布林带 (Bollinger Bands)

**原理**: 基于统计学的价格通道，衡量波动率和价格位置。

**公式**:
```
中轨 = SMA(close, period)              # period = 20
标准差 = std(close, period)
上轨 = 中轨 + multiplier × 标准差      # multiplier = 2
下轨 = 中轨 - multiplier × 标准差

%B = (close - 下轨) / (上轨 - 下轨)     # 价格位置 (0-1)
带宽 = (上轨 - 下轨) / 中轨             # 波动率
```

**评分逻辑**:
```
%B < 0     → 价格低于下轨 → 超卖 → 得分 8-10
%B 0-0.2   → 接近下轨 → 偏低 → 得分 6-8
%B 0.2-0.8 → 通道内 → 中性 → 得分 4-6
%B 0.8-1   → 接近上轨 → 偏高 → 得分 2-4
%B > 1     → 价格高于上轨 → 超买 → 得分 0-2

带宽收窄 → 波动率低 → 可能突破 → 置信度降低
带宽扩大 → 波动率高 → 趋势明确 → 置信度提高
```

**参考**: John Bollinger (2001). Bollinger on Bollinger Bands.

---

### 1.4 KDJ 随机指标

**原理**: 衡量收盘价在一定周期内价格范围中的位置。

**公式**:
```
RSV = (close - lowest_low) / (highest_high - lowest_low) × 100
      period = 9

K = SMA(RSV, 3)     # 实际使用 EMA 平滑
D = SMA(K, 3)
J = 3 × K - 2 × D

SMA平滑:
  K_today = 2/3 × K_yesterday + 1/3 × RSV_today
  D_today = 2/3 × D_yesterday + 1/3 × K_today
```

**评分逻辑**:
```
K < 20 且 D < 20     → 超卖 → 得分 8-10
K > D 且 J > 0       → 多头 → 得分 5-8
K < D 且 J < 0       → 空头 → 得分 2-5
K > 80 且 D > 80     → 超买 → 得分 0-2
金叉 (K上穿D)        → 买入信号 → +2 分
死叉 (K下穿D)        → 卖出信号 → -2 分
```

**参考**: George Lane (1984). Lane's Stochastics.

---

### 1.5 ATR (Average True Range) 平均真实波幅

**原理**: 衡量市场波动率，用于止损和仓位管理。

**公式**:
```
TR = max(
  high - low,
  abs(high - prev_close),
  abs(low - prev_close)
)
ATR = SMA(TR, period)    # period = 14
```

**用途**:
- 波动率标准化: ATR / close → 相对波动率
- 止损距离: N × ATR
- 仓位调整: 目标风险 / ATR

---

## 二、市场情绪因子

### 2.1 涨跌家数比 (Advance-Decline Ratio)

**原理**: 衡量市场整体强弱的广度指标。

**公式**:
```
上涨家数 = count(sector where change > 0)
下跌家数 = count(sector where change < 0)
涨跌比 = 上涨家数 / (上涨家数 + 下跌家数)

AD线 = 累计(上涨家数 - 下跌家数)   # 涨跌线
```

**评分映射**:
```
涨跌比 > 0.7  → 强势市场 → 得分 8-10
涨跌比 0.5-0.7 → 偏强 → 得分 5-7
涨跌比 0.3-0.5 → 偏弱 → 得分 3-5
涨跌比 < 0.3  → 弱势市场 → 得分 0-2
```

**参考**: Granville, Joseph (1963). New Strategy of Daily Stock Market Timing.

---

### 2.2 量比 (Volume Ratio)

**原理**: 当日成交量与近期平均成交量的比值，衡量资金活跃度。

**公式**:
```
量比 = 当日成交量 / 近N日平均成交量
N = 5 (默认)

对数量比 = log(量比)   # 用于标准化
```

**评分逻辑**:
```
量比 > 2.0  → 显著放量 → 趋势确认 → 得分 7-10
量比 1.2-2.0 → 温和放量 → 得分 5-7
量比 0.8-1.2 → 正常 → 得分 4-6
量比 < 0.8  → 缩量 → 趋势减弱 → 得分 2-4

配合价格:
  放量上涨 → 强势买入信号
  放量下跌 → 弱势卖出信号
  缩量上涨 → 动能不足
  缩量下跌 → 抛压减轻
```

---

### 2.3 历史波动率 (Historical Volatility)

**原理**: 衡量价格变动的不确定性。

**公式**:
```
日收益率 = ln(close / prev_close)
HV = std(日收益率, period) × sqrt(252)
    period = 20 (默认)

年化波动率 = 日波动率 × sqrt(交易日数)
```

**评分逻辑**:
```
HV < 15%  → 低波动 → 稳健 → 得分 6-8 (保守偏好)
HV 15-25% → 中等波动 → 得分 4-6
HV 25-40% → 高波动 → 风险较高 → 得分 2-4
HV > 40%  → 极高波动 → 风险很高 → 得分 0-2

注: 激进策略对高波动容忍度更高
```

---

### 2.4 换手率 (Turnover Rate)

**原理**: 衡量板块资金流动性和活跃度。

**公式**:
```
换手率 = 成交额 / 流通市值
相对换手率 = 当日换手率 / 近N日平均换手率
```

**评分逻辑**:
```
相对换手率 > 2.0 → 资金高度关注 → 得分 7-10
相对换手率 1.0-2.0 → 正常活跃 → 得分 4-7
相对换手率 < 1.0 → 资金冷落 → 得分 0-4
```

---

## 三、轮动特征因子

### 3.1 板块持续性 (Persistence，`factors/rotation.py`)

**原理**: 近 `period` 个交易日中，该板块在**全市场横截面**按当日 `index_change_pct` 排序是否处于前 `top_k`；刻画「强势是否在多板块中持续靠前」。

**输入**:

- `history`：该板块按日升序，需含 `date`、`index_change_pct`。
- `context["changes_by_date"]`：由 `scoring` 预聚合，`date -> { sector_code -> index_change_pct }`，同一交易日至少 **3** 个板块才参与该日的截面排名。

**公式（截面模式）**:
```
对每个历史窗口内的交易日 t:
  若当日有效板块数 ≥ 3:
    计算本 sector_code 在 peers 中按涨跌幅降序的排名 rank_t
    in_top_k_t = 1 if rank_t <= top_k else 0
    计入有效日计数

持续性 = sum(in_top_k_t) / 有效截面日数
raw 得分映射: score = clamp(持续性 × 10, 0, 10)
置信度随「有效截面日数 / period」提高。
```

**无截面上下文或当日有效板块不足时**：回退为「窗口内正收益日占比 × 10」，置信度较低（见 `detail.mode`）。

**评分解读（与 0–10 分一致）**:
```
持续性 > 0.7  → 多数日在全市场前列 → 偏高得分
持续性 0.4-0.7 → 中等
持续性 < 0.4  → 偏弱
```

---

### 3.2 轮动速度 (Rotation Speed)

**原理**: 衡量板块轮动的剧烈程度。

**公式**:
```
每日TOP板块集合 = top_k 板块 (按评分)
Jaccard距离 = 1 - |A ∩ B| / |A ∪ B|
    A = 昨日TOP集合
    B = 今日TOP集合

轮动速度 = mean(Jaccard距离 over N days)
```

**用途**:
- 轮动速度快 → 市场热点切换频繁 → 缩短持仓周期
- 轮动速度慢 → 市场热点稳定 → 延长持仓周期

---

### 3.3 板块相关性 (Sector Correlation)

**原理**: 衡量板块间的联动程度。

**公式**:
```
板块收益率矩阵 R[i,t] (i=板块, t=日期)
相关系数矩阵 Corr[i,j] = corr(R[i], R[j])
平均相关性 = mean(Corr[i,j]) for all i < j
```

**评分逻辑**:
```
平均相关性 < 0.3 → 板块分化 → 轮动机会大 → 得分 7-10
平均相关性 0.3-0.6 → 中等联动 → 得分 4-7
平均相关性 > 0.6 → 高度联动 → 齐涨齐跌 → 得分 0-4
```

---

## 四、因子标准化方法

### 4.1 Min-Max 标准化

```
score = (value - min) / (max - min) × 10
钳位到 [0, 10]
```

### 4.2 Z-Score 标准化

```
z = (value - mean) / std
score = 5 + z × 1.5   # 映射到约 [0, 10]
钳位到 [0, 10]
```

### 4.3 百分位排名

```
rank = count(value_i < value) / total_count
score = rank × 10
```

### 4.4 选择标准

| 因子类型 | 推荐方法 | 原因 |
|---------|---------|------|
| 资金流 | Min-Max | 有明确的物理单位 |
| RSI/KDJ | 直接映射 | 本身已是0-100标准 |
| 布林带%B | 直接映射 | 本身已是0-1标准 |
| 波动率 | Z-Score | 无固定范围 |
| 涨跌比 | 直接映射 | 本身已是0-1标准 |
| 排名因子 | 百分位排名 | 相对排名有意义 |

---

## 五、数据质量要求

### 5.1 最小数据长度

| 因子 | 最小K线数 | 理想K线数 | 缺失处理 |
|------|----------|----------|---------|
| RSI(14) | 15 | 30 | 跳过 |
| MACD(12,26,9) | 35 | 50 | 跳过 |
| 布林带(20) | 21 | 40 | 跳过 |
| KDJ(9) | 10 | 20 | 跳过 |
| ATR(14) | 15 | 30 | 跳过 |
| 量比(5) | 6 | 10 | 使用默认值 |
| 波动率(20) | 21 | 40 | 跳过 |
| 持续性(10) | 11 | 20 | 跳过 |

### 5.2 异常值处理

```
1. 缺失值: 跳过该因子，confidence=0
2. 无穷大: 替换为边界值
3. NaN: 跳过该因子
4. 超出合理范围: 钳位到边界
```

---

## 六、参考资料

1. Wilder, J.W. (1978). New Concepts in Technical Trading Systems
2. Appel, G. (1979). Technical Analysis: Power Tools for Active Investors
3. Bollinger, J. (2001). Bollinger on Bollinger Bands
4. Lane, G. (1984). Lane's Stochastics
6. Fama, E. & French, K. (1993). Common risk factors in the returns on stocks and bonds
7. Jegadeesh, N. & Titman, S. (1993). Returns to buying winners and selling losers
8. Asness, C. et al. (2013). Value and Momentum Everywhere
