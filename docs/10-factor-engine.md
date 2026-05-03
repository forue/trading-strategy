# 因子引擎架构设计文档

> 版本: v1.0 | 创建日期: 2026-05-01 | 内容: 多因子量化评估体系

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
│  │   输入: 各因子得分 (0-10)                                 │   │
│  │   方法: 加权合成 / 排名合成 / 分层合成                     │   │
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
│  │   │  - calculate(data) -> FactorResult           │      │   │
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
│   ├── weighted.py      # 加权合成 (线性加权)
│   ├── ranking.py       # 排名合成 (分位数排名)
│   └── config.py        # 合成配置
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
    def calculate(self, sector_data: dict, history: list = None) -> FactorResult:
        """计算因子得分
        
        Args:
            sector_data: 当日板块数据 {sector_code, main_net_inflow, index_change_pct, ...}
            history: 历史数据序列 [{date, close, volume, ...}]
        
        Returns:
            FactorResult
        """
        pass
    
    @abstractmethod
    def validate_data(self, sector_data: dict) -> bool:
        """验证数据完整性"""
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
```

### 2.5 因子合成引擎

```python
class FactorCombiner:
    """因子合成引擎"""
    
    def combine_weighted(self, results: list[FactorResult]) -> float:
        """加权合成: score = Σ(factor_score × factor_weight) / Σ(weight)"""
        if not results:
            return 0.0
        total_weight = sum(r.weight for r in results)
        if total_weight == 0:
            return 0.0
        return sum(r.score * r.weight for r in results) / total_weight
    
    def combine_ranking(self, results: list[FactorResult]) -> float:
        """排名合成: 将各因子排名归一化后加权"""
        # 每个因子转为百分位排名 (0-1)
        # 再加权合成
        pass
    
    def combine_hierarchical(self, results: list[FactorResult], 
                             category_weights: dict[str, float]) -> float:
        """分层合成: 先类别内合成，再类别间加权"""
        # 第一层: 同类别因子合成
        # 第二层: 类别间加权
        pass
```

---

## 三、因子体系设计

### 3.1 因子分类与权重

| 类别 | 因子 | 激进权重 | 稳健权重 | 保守权重 | 数据需求 |
|------|------|---------|---------|---------|---------|
| **资金流** | 主力净流入 | 35% | 25% | 15% | 当日数据 |
| | 北向净流入 | 15% | 10% | 10% | 当日数据 |
| **动量** | 价格动量(5日) | 20% | 15% | 10% | 5日K线 |
| | 相对强弱 | 15% | 10% | 5% | 5日K线 |
| **技术指标** | RSI(14) | 5% | 10% | 10% | 14日K线 |
| | MACD信号 | 5% | 10% | 10% | 26日K线 |
| | 布林带位置 | 5% | 5% | 10% | 20日K线 |
| **情绪** | 量比 | 0% | 5% | 5% | 5日成交量 |
| | 波动率 | 0% | 5% | 10% | 20日K线 |
| **估值** | PE分位 | 0% | 5% | 15% | 估值数据 |
| | PB分位 | 0% | 5% | 10% | 估值数据 |
| **轮动** | 持续性 | 0% | 0% | 5% | 10日排名 |
| | **合计** | 100% | 100% | 100% | |

### 3.2 数据流

```
InfluxDB (K线/资金流)
    │
    ▼
InfluxQuery (数据查询)
    │
    ▼
FactorRegistry (因子注册)
    │
    ├── CapitalFlowFactor.calculate()  → FactorResult
    ├── MomentumFactor.calculate()     → FactorResult
    ├── TechnicalFactor.calculate()    → FactorResult
    ├── SentimentFactor.calculate()    → FactorResult
    ├── ValuationFactor.calculate()    → FactorResult
    └── RotationFactor.calculate()     → FactorResult
    │
    ▼
FactorCombiner (合成)
    │
    ▼
ScoringModel (评分 → 信号)
```

---

## 四、API 设计

### 4.1 因子计算接口

```
POST /api/strategy/factors/calculate
Content-Type: application/json

Request:
{
  "sector_code": "SW801780",
  "date": "2026-05-01",
  "strategy_type": "MODERATE"
}

Response:
{
  "code": 200,
  "data": {
    "sector_code": "SW801780",
    "sector_name": "银行",
    "date": "2026-05-01",
    "composite_score": 7.23,
    "factors": [
      {
        "name": "capital_flow",
        "category": "capital_flow",
        "raw_value": 1.5e8,
        "score": 7.5,
        "weight": 0.35,
        "confidence": 0.9,
        "detail": {"main_flow_yi": 1.5, "north_flow_yi": 0.3}
      },
      {
        "name": "rsi_14",
        "category": "technical",
        "raw_value": 62.5,
        "score": 6.0,
        "weight": 0.10,
        "confidence": 0.8,
        "detail": {"period": 14, "level": "neutral"}
      }
    ],
    "strategy_weights": {
      "capital_flow": 0.35,
      "momentum": 0.25,
      "technical": 0.25,
      "sentiment": 0.10,
      "valuation": 0.05
    }
  }
}
```

### 4.2 批量因子计算

```
POST /api/strategy/factors/batch
Content-Type: application/json

Request:
{
  "date": "2026-05-01",
  "strategy_type": "MODERATE",
  "sector_codes": ["SW801780", "SW801150", "SW801080"]
}

Response:
{
  "code": 200,
  "data": {
    "date": "2026-05-01",
    "strategy_type": "MODERATE",
    "rankings": [
      {"sector_code": "SW801780", "sector_name": "银行", "composite_score": 7.23, "rank": 1},
      {"sector_code": "SW801080", "sector_name": "电子", "composite_score": 6.85, "rank": 2},
      {"sector_code": "SW801150", "sector_name": "医药生物", "composite_score": 5.12, "rank": 3}
    ]
  }
}
```

### 4.3 因子配置接口

```
GET /api/strategy/factors/config
PUT /api/strategy/factors/config

Request:
{
  "strategy_type": "MODERATE",
  "weights": {
    "capital_flow": 0.35,
    "momentum": 0.25,
    "technical": 0.25,
    "sentiment": 0.10,
    "valuation": 0.05
  },
  "factor_params": {
    "rsi_period": 14,
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    "bollinger_period": 20,
    "bollinger_std": 2
  }
}
```

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

校验失败时：
- 返回 `confidence=0` 的结果
- 不参与最终评分合成
- 记录警告日志

---

## 六、实现阶段

| 阶段 | 内容 | 优先级 | 工作量 |
|------|------|--------|--------|
| P0 | 因子基类 + 资金流/动量因子重构 | 高 | 1天 |
| P1 | 技术指标因子 (RSI/MACD/布林带/KDJ) | 高 | 2天 |
| P2 | 市场情绪因子 (量比/波动率/涨跌比) | 高 | 1天 |
| P3 | 因子合成引擎 (加权/排名合成) | 高 | 1天 |
| P4 | 轮动特征因子 (相关性/持续性) | 中 | 1天 |
| P5 | 估值因子增强 + 多因子模型 | 中 | 2天 |
