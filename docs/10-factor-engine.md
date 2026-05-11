# 因子引擎架构设计文档

> 版本: v1.2 | 更新日期: 2026-05-12 | 更新: Z-Score截面归一化、FlowAccelerationFactor

---

## 一、模块概述

因子引擎是对现有评分模型的系统性扩展，将单一的资金流+动量评分升级为多因子量化评估体系。采用插件化架构，每个因子独立计算、可配置权重、可独立验证，确保生产环境数据真实性和算法可追溯性。

| 属性 | 值 |
|------|-----|
| 所属服务 | backend-strategy |
| 核心路径 | `services/strategy/app/factors/` |
| 数据源 | InfluxDB (K线/资金流) + Redis (实时缓存) |
| 设计原则 | 插件化、可配置、数据真实、算法可追溯 |

---

## 二、架构设计

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                      评分模型 (scoring.py)                       │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                 因子合成引擎 (FactorCombiner)              │   │
│  │                                                          │   │
│  │   输入: 各因子得分 (0-10) + 置信度                         │   │
│  │   方法: 类内置信度加权 → 类间策略权重 → 可选截面排名混合    │   │
│  │   输出: 综合评分 (0-10)                                   │   │
│  └──────────────┬───────────────────────────────────────────┘   │
│                 │                                               │
│  ┌──────────────▼───────────────────────────────────────────┐   │
│  │                 因子注册中心 (FactorRegistry)              │   │
│  │                                                          │   │
│  │   ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐      │   │
│  │   │ 资金流  │ │ 动量    │ │ 技术指标│ │ 情绪    │      │   │
│  │   │ 因子    │ │ 因子    │ │ 因子    │ │ 因子    │      │   │
│  │   └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘      │   │
│  │        │           │           │           │            │   │
│  │   ┌────▼───────────▼───────────▼───────────▼────┐      │   │
│  │   │           BaseFactor (因子基类)               │      │   │
│  │   │  - name: str                                 │      │   │
│  │   │  - weight: float                             │      │   │
│  │   │  - calculate(data, history, context?) -> FactorResult │   │
│  │   └─────────────────────────────────────────────┘      │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                 数据查询层 (InfluxQuery)                  │   │
│  │                                                          │   │
│  │   query_daily_sectors()     → 每日板块数据                │   │
│  │   query_sector_kline()      → 板块K线序列                │   │
│  │   query_sector_history()    → 板块历史数据                │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 目录结构

```
services/strategy/app/
├── main.py              # FastAPI 主应用
├── scoring.py           # 评分模型 (调用因子引擎)
├── models.py            # 数据模型
├── influx_query.py      # InfluxDB 查询
├── config.py            # 配置
│
├── factors/             # 因子计算引擎
│   ├── __init__.py      # 导出所有因子
│   ├── base.py          # 因子基类 + 注册中心
│   ├── capital_flow.py  # 资金流因子 (现有逻辑重构)
│   ├── momentum.py      # 动量因子 (现有逻辑重构)
│   ├── technical.py     # 技术指标因子 (RSI/MACD/布林带/KDJ)
│   ├── sentiment.py     # 市场情绪因子 (涨跌比/量比/波动率)
│   ├── valuation.py     # 估值因子 (PE/PB分位)
│   └── rotation.py      # 轮动特征因子 (相关性/持续性/速度)
│
├── combiner/            # 因子合成引擎
│   ├── __init__.py
│   └── weighted.py      # StrategyWeights + FactorCombiner（加权合成、截面排名合成）
│
└── docs/                # 算法文档
    └── algorithms.md    # 因子算法参考
```

### 2.3 因子基类设计

```python
from abc import ABC, abstractmethod
from pydantic import BaseModel
from typing import Optional
from enum import Enum

class FactorCategory(str, Enum):
    """因子类别"""
    CAPITAL_FLOW = "capital_flow"    # 资金流
    MOMENTUM = "momentum"            # 动量
    TECHNICAL = "technical"          # 技术指标
    SENTIMENT = "sentiment"          # 市场情绪
    VALUATION = "valuation"          # 估值
    ROTATION = "rotation"            # 轮动特征

class FactorResult(BaseModel):
    """单因子计算结果"""
    name: str                    # 因子名称
    category: FactorCategory     # 因子类别
    raw_value: float             # 原始值
    score: float                 # 标准化得分 (0-10)
    weight: float                # 权重
    confidence: float            # 置信度 (0-1)
    detail: dict = {}            # 计算细节

class BaseFactor(ABC):
    """因子基类"""
    
    name: str = "base_factor"
    category: FactorCategory = FactorCategory.MOMENTUM
    default_weight: float = 0.0
    
    @abstractmethod
    def calculate(self, sector_data: dict, history: list = None, context: dict = None) -> FactorResult:
        """计算因子得分
        
        Args:
            sector_data: 当日板块数据 {sector_code, main_net_inflow, index_change_pct, ...}
            history: 历史数据序列（按日期升序），字段含 date、index_change_pct、index_close 等
            context: 可选截面上下文。例如 {"changes_by_date": {"2026-01-02": {"THS801010": 1.2, ...}}}
                     由 scoring 在当日全板块列表上预聚合，供持续性等因子做横截面排名
        
        Returns:
            FactorResult
        """
        pass
    
    def validate_data(self, sector_data: dict, history: list = None) -> bool:
        """验证数据完整性（实现类可覆盖）"""
        pass
```

### 2.4 因子注册中心

```python
class FactorRegistry:
    """因子注册中心"""
    
    _factors: dict[str, BaseFactor] = {}
    
    @classmethod
    def register(cls, factor: BaseFactor):
        """注册因子"""
        cls._factors[factor.name] = factor
    
    @classmethod
    def get(cls, name: str) -> Optional[BaseFactor]:
        """获取因子"""
        return cls._factors.get(name)
    
    @classmethod
    def get_all(cls) -> dict[str, BaseFactor]:
        """获取所有因子"""
        return cls._factors.copy()
    
    @classmethod
    def get_by_category(cls, category: FactorCategory) -> list[BaseFactor]:
        """按类别获取因子"""
        return [f for f in cls._factors.values() if f.category == category]

    @classmethod
    def calculate_all(cls, sector_data: dict, history: list = None, context: dict = None) -> list[FactorResult]:
        """依次计算已注册因子；context 原样传入各因子 calculate（实现见源码）"""
        pass  # 实现见 services/strategy/app/factors/base.py
```

### 2.5 因子合成引擎（`combiner/weighted.py`）

实现为 **两层结构**，与下文的 `StrategyWeights` / `DEFAULT_WEIGHTS` 一致：

1. **类内合成**：对同一 `FactorCategory` 下的多个 `FactorResult`，使用有效权重  
   `w_eff = factor.weight × max(confidence, 0)`。若该类别所有因子 `w_eff` 之和为 0，**整类不参与**类间合成（避免 `confidence=0` 的占位 5 分稀释信号）。
2. **类间合成**：用 `StrategyWeights` 中各类别权重对类别得分加权，并按**实际出现的类别权重之和**归一化；若没有任何可用类别，综合分回退为 **5.0**。

```python
class StrategyWeights(BaseModel):
    capital_flow: float
    momentum: float
    technical: float
    sentiment: float
    valuation: float
    rotation: float   # 三档策略均配置非零，轮动类因子参与合成

class FactorCombiner:
    def combine_weighted(
        self, results: list[FactorResult], weights: StrategyWeights | None
    ) -> tuple[float, dict]:
        """返回 (综合分, 按类别的明细 category_scores)"""
        pass  # 实现见 weighted.py

    def combine_ranking(
        self, all_sector_results: dict[str, list[FactorResult]], weights: StrategyWeights | None
    ) -> dict[str, float]:
        """全市场当日：各因子先做横截面分位得分 (0–10)，再按因子权重合成；用于 scoring 中与绝对分混合"""
        pass
```

**代码中的类别权重**以 `services/strategy/app/combiner/weighted.py` 的 `DEFAULT_WEIGHTS` 为准（会随版本迭代，文档表格仅作概念对照）。

---

## 三、因子体系设计

### 3.1 因子分类与策略类别权重

因子按 `FactorCategory` 分为：资金流、动量、技术指标、情绪、估值、轮动。每个因子另有类内 `default_weight`。

**策略档位（AGGRESSIVE / MODERATE / CONSERVATIVE）的类别间权重**由 `StrategyWeights` 定义，源码为 `combiner/weighted.py` 中的 `DEFAULT_WEIGHTS`。当前实现要点：

- **轮动（rotation）** 在三档中均占非零权重，与「轮动特征因子」语义一致。
- 类内合成使用 **置信度加权**；类间再按上述类别权重归一。

单因子与数据需求说明仍以 `docs/11-factor-algorithms.md` 为准。

### 3.2 数据流（含截面与信号）

```
InfluxDB (K线/资金流)
    │
    ▼
InfluxQuery (数据查询)  →  各板块 sector_data，可选 _history
    │
    ▼
scoring.calculate_daily_signals
    │  预聚合 context.changes_by_date（全板块历史涨跌幅按日对齐）
    ▼
FactorRegistry.calculate_all(sector_data, history, context)
    │
    ├── 各类因子.calculate(...)  → FactorResult
    │
    ▼
FactorCombiner.combine_weighted  → 绝对综合分 + category_scores
    │
    ▼（当日板块数 ≥ 3 且 cross_section_alpha > 0）
FactorCombiner.combine_ranking  → 截面排名综合分
    │
    ▼
综合分 = (1 − α) × 绝对分 + α × 截面分   （α = StrategyParams.cross_section_alpha）
    │
    ▼
三档轮动规则 → TradeSignal（含 position_ratio，可按波动倒数分配）
```

---

## 四、API 设计

（网关前缀以部署为准，以下为策略服务相对路径；与 `services/strategy/app/main.py` 一致。）

### 4.1 单板块因子分析 `POST /factors/analyze`

Request（`FactorAnalyzeRequest`）:

```json
{
  "sector_code": "SW801780",
  "date": "2026-05-01",
  "strategy_type": "MODERATE"
}
```

Response `data` 主要字段：

| 字段 | 说明 |
|------|------|
| `composite_score` | 与 `abs_composite_score` 一致（单板块接口不做全市场截面混合） |
| `abs_composite_score` | 因子引擎加权综合分 |
| `rank_composite_score` | 单板块分析时为 `null`（需全市场因子集方可定义截面排名分） |
| `engine_fallback` | 因子引擎异常走简化评分时为 `true` |
| `factors` | 各因子明细列表 |
| `category_scores` | 按类别的合成明细（与 `combine_weighted` 第二返回值一致） |
| `strategy_weights` | 当前档位的 `StrategyWeights` |

### 4.2 批量因子分析 `POST /factors/batch`

当日多板块：先逐板块 `calculate_all`（带空或截面 `context`），再 `combine_ranking` 与默认 `cross_section_alpha` 做 **绝对分与截面分的混合**。`rankings` 中每条含：

- `composite_score`：混合后最终分  
- `abs_composite_score`：仅加权绝对分  
- `rank_composite_score`：截面排名合成得分（板块数不足时可能为 `null`）  
- `rank`：按 `composite_score` 排序的名次

### 4.3 因子配置 `GET /factors/config`

返回已注册因子列表与 `DEFAULT_WEIGHTS` 各档位权重（只读；持久化策略参数见策略配置接口）。

---

## 五、数据要求

### 5.1 必需数据字段

| 数据源 | 字段 | 用途 | 最小历史 |
|--------|------|------|---------|
| InfluxDB 板块日线 | `index_close` | 技术指标计算 | 30日 |
| InfluxDB 板块日线 | `index_high` | 布林带/KDJ | 30日 |
| InfluxDB 板块日线 | `index_low` | 布林带/KDJ | 30日 |
| InfluxDB 板块日线 | `turnover` | 量比/换手率 | 30日 |
| InfluxDB 板块日线 | `main_net_inflow` | 资金流因子 | 5日 |
| InfluxDB 板块日线 | `north_net_inflow` | 北向资金因子 | 5日 |
| InfluxDB 板块日线 | `index_change_pct` | 动量因子 | 20日 |

### 5.2 数据完整性校验

每个因子在计算前必须通过 `validate_data()` 校验：
- 必需字段非空
- 数值在合理范围内
- 历史数据长度满足最小要求

校验失败或数据不足时：
- 注册中心仍可能产生 `confidence=0` 的占位结果；**类内合成时该类整体跳过**，不进入类别平均分。
- 记录警告/错误日志。

---

## 六、实现阶段（里程碑）

| 阶段 | 内容 | 状态 |
|------|------|------|
| P0–P2 | 因子基类、资金流/动量/技术/情绪因子 | 已落地 |
| P3 | 加权合成 + 截面排名合成 + 置信度参与类内权重 | 已落地 |
| P4 | 轮动特征因子（持续性含截面 TOP-K；无截面时回退） | 已落地 |
| P5 | 估值与其它增强 | 持续迭代 |

策略侧可调参数见 `models.StrategyParams`：`cross_section_alpha`、`use_relative_score_gap`、`relative_score_gap_ratio`、`use_inverse_vol_weights`、`use_zscore_normalization` 等。

### 6.2 截面 Z-Score 归一化 (`FactorRegistry.apply_zscore_normalization`)

当 `StrategyParams.use_zscore_normalization = True`（默认开启）时，在因子加权合成之前对全板块因子结果进行截面归一化：

1. 对每个因子，收集所有板块的 `raw_value`
2. 计算截面均值 μ 和标准差 σ
3. 将每个板块的评分替换为 Z-Score 映射: `score = clamp(5 + z × 2, 0, 10)`
4. 标准差为 0（全板块值相同）时保持原评分不变
5. 至少 3 个有效值才进行归一化

归一化后，因子评分反映的是板块间相对排名而非绝对阈值，减少市场整体涨跌对评分的系统性偏移。`detail` 中会附加 `zscore`、`cross_mean`、`cross_std` 字段。
