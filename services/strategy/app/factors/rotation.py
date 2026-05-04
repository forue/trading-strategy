"""轮动特征因子 - 持续性 / 轮动速度"""
from .base import BaseFactor, FactorResult, FactorCategory, FactorRegistry


def _norm_date(d) -> str:
    if d is None:
        return ""
    s = str(d)[:10]
    return s


class PersistenceFactor(BaseFactor):
    """板块持续性因子

    近 N 个交易日中，截面涨幅排名进入前 K 的天数占比（需 context.changes_by_date）。
    无截面数据时回退为时间序列上的正收益日占比，置信度降低。
    """

    name = "persistence"
    category = FactorCategory.ROTATION
    default_weight = 0.05
    min_history_days = 10

    def __init__(self, top_k: int = 10, period: int = 10):
        self.top_k = top_k
        self.period = period

    def calculate(self, sector_data: dict, history: list = None, context: dict = None) -> FactorResult:
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

        code = str(sector_data.get("sector_code", "") or "")
        changes_by_date = (context or {}).get("changes_by_date") or {}

        days_in_top_k = 0
        days_cross_valid = 0
        slice_hist = history[-self.period :]

        for h in slice_hist:
            d = _norm_date(h.get("date"))
            peers = changes_by_date.get(d) if d else None
            if peers and len(peers) >= 3 and code in peers:
                days_cross_valid += 1
                sorted_codes = sorted(peers.keys(), key=lambda c: peers[c], reverse=True)
                try:
                    rank = sorted_codes.index(code) + 1
                except ValueError:
                    rank = 999
                if rank <= self.top_k:
                    days_in_top_k += 1

        if days_cross_valid > 0:
            persistence = days_in_top_k / days_cross_valid
            confidence = min(1.0, 0.35 + 0.5 * (days_cross_valid / self.period))
            mode = "cross_section_topk"
        else:
            rank_history = [h.get("index_change_pct", 0) for h in slice_hist]
            positive_days = sum(1 for r in rank_history if r > 0)
            persistence = positive_days / len(rank_history) if rank_history else 0
            confidence = 0.25
            mode = "time_series_positive_fallback"

        score = persistence * 10.0

        return FactorResult(
            name=self.name,
            category=self.category,
            raw_value=persistence,
            score=round(self.clamp(score), 2),
            weight=self.default_weight,
            confidence=round(confidence, 2),
            detail={
                "persistence": round(persistence, 4),
                "mode": mode,
                "days_in_top_k": days_in_top_k,
                "days_cross_valid": days_cross_valid,
                "period": self.period,
                "top_k": self.top_k,
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

    def calculate(self, sector_data: dict, history: list = None, context: dict = None) -> FactorResult:
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
