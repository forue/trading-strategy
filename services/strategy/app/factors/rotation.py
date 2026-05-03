"""轮动特征因子 - 持续性 / 轮动速度"""
import numpy as np
from .base import BaseFactor, FactorResult, FactorCategory, FactorRegistry


class PersistenceFactor(BaseFactor):
    """板块持续性因子

    衡量板块在排名中的稳定性。
    计算: 近N日中在TOP K排名内的比例。
    """

    name = "persistence"
    category = FactorCategory.ROTATION
    default_weight = 0.05
    min_history_days = 10

    def __init__(self, top_k: int = 10, period: int = 10):
        self.top_k = top_k
        self.period = period

    def calculate(self, sector_data: dict, history: list = None) -> FactorResult:
        if not history or len(history) < self.period:
            return FactorResult(
                name=self.name,
                category=self.category,
                raw_value=0,
                score=5.0,
                weight=self.default_weight,
                confidence=0.0,
                detail={"error": "历史数据不足"},
            )

        # 计算每日排名 (按涨跌幅)
        rank_history = []
        for h in history[-self.period:]:
            # 简化: 使用涨跌幅作为排名依据
            # 实际应使用全市场排名
            change = h.get("index_change_pct", 0)
            rank_history.append(change)

        # 持续性: 近N日中正收益的天数比例
        positive_days = sum(1 for r in rank_history if r > 0)
        persistence = positive_days / len(rank_history) if rank_history else 0

        # 评分: 持续性越高越好
        score = persistence * 10.0

        confidence = 0.6

        return FactorResult(
            name=self.name,
            category=self.category,
            raw_value=persistence,
            score=round(self.clamp(score), 2),
            weight=self.default_weight,
            confidence=round(confidence, 2),
            detail={
                "persistence": round(persistence, 4),
                "positive_days": positive_days,
                "total_days": len(rank_history),
            },
        )

    def validate_data(self, sector_data: dict, history: list = None) -> bool:
        return history is not None and len(history) >= self.min_history_days


class TrendConsistencyFactor(BaseFactor):
    """趋势一致性因子

    衡量板块趋势的方向一致性。
    计算: 近N日中同方向天数的比例。
    """

    name = "trend_consistency"
    category = FactorCategory.ROTATION
    default_weight = 0.05
    min_history_days = 10

    def __init__(self, period: int = 10):
        self.period = period

    def calculate(self, sector_data: dict, history: list = None) -> FactorResult:
        if not history or len(history) < self.period:
            return FactorResult(
                name=self.name,
                category=self.category,
                raw_value=0,
                score=5.0,
                weight=self.default_weight,
                confidence=0.0,
                detail={"error": "历史数据不足"},
            )

        # 计算涨跌方向
        directions = []
        for h in history[-self.period:]:
            change = h.get("index_change_pct", 0)
            directions.append(1 if change > 0 else -1 if change < 0 else 0)

        # 当日方向
        today_change = history[-1].get("index_change_pct", 0) if history else 0
        today_direction = 1 if today_change > 0 else -1 if today_change < 0 else 0

        # 一致性: 与当日同方向的天数比例
        same_direction = sum(1 for d in directions if d == today_direction)
        consistency = same_direction / len(directions) if directions else 0

        # 评分: 一致性越高，趋势越明确
        score = consistency * 10.0

        confidence = 0.6

        return FactorResult(
            name=self.name,
            category=self.category,
            raw_value=consistency,
            score=round(self.clamp(score), 2),
            weight=self.default_weight,
            confidence=round(confidence, 2),
            detail={
                "consistency": round(consistency, 4),
                "today_direction": today_direction,
                "same_direction_days": same_direction,
            },
        )

    def validate_data(self, sector_data: dict, history: list = None) -> bool:
        return history is not None and len(history) >= self.min_history_days


# 注册因子
FactorRegistry.register(PersistenceFactor())
FactorRegistry.register(TrendConsistencyFactor())
