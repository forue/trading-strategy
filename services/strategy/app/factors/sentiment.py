"""市场情绪因子 - 量比 / 波动率 / 换手率"""
import numpy as np
from .base import BaseFactor, FactorResult, FactorCategory, FactorRegistry


class VolumeRatioFactor(BaseFactor):
    """量比因子

    当日成交量与近期平均成交量的比值，衡量资金活跃度。
    公式: 量比 = 当日成交量 / 近N日平均成交量
    """

    name = "volume_ratio"
    category = FactorCategory.SENTIMENT
    default_weight = 0.05
    min_history_days = 6

    def __init__(self, period: int = 5):
        self.period = period

    def calculate(self, sector_data: dict, history: list = None, context: dict = None) -> FactorResult:
        turnover = sector_data.get("turnover", 0)

        # 计算近N日平均成交量
        if history and len(history) >= self.period:
            recent_turnover = [h.get("turnover", 0) for h in history[-self.period:]]
            avg_turnover = np.mean(recent_turnover) if recent_turnover else 1
        else:
            avg_turnover = turnover  # 无历史时使用当日值

        # 量比
        volume_ratio = turnover / avg_turnover if avg_turnover > 0 else 1.0

        # 评分: 量比 > 2 放量(7-10), 量比 < 0.8 缩量(2-4)
        if volume_ratio > 2.0:
            score = 7.0 + min((volume_ratio - 2.0) * 2, 3.0)
        elif volume_ratio > 1.2:
            score = 5.0 + (volume_ratio - 1.2) * 2.5
        elif volume_ratio > 0.8:
            score = 4.0 + (volume_ratio - 0.8) * 2.5
        else:
            score = max(0, 2.0 + volume_ratio * 2.5)

        # 结合价格方向调整
        change_pct = sector_data.get("index_change_pct", 0)
        if change_pct > 0 and volume_ratio > 1.2:
            score += 1.0  # 放量上涨
        elif change_pct < 0 and volume_ratio > 1.2:
            score -= 1.0  # 放量下跌

        confidence = 0.7 if history and len(history) >= self.period else 0.4

        return FactorResult(
            name=self.name,
            category=self.category,
            raw_value=volume_ratio,
            score=round(self.clamp(score), 2),
            weight=self.default_weight,
            confidence=round(confidence, 2),
            detail={
                "volume_ratio": round(volume_ratio, 2),
                "turnover_yi": round(turnover / 1e8, 2) if turnover > 0 else 0,
                "avg_turnover_yi": round(avg_turnover / 1e8, 2) if avg_turnover > 0 else 0,
            },
        )

    def validate_data(self, sector_data: dict, history: list = None) -> bool:
        return "turnover" in sector_data


class VolatilityFactor(BaseFactor):
    """历史波动率因子

    衡量价格变动的不确定性，用于风险评估。
    公式: HV = std(日收益率) × sqrt(252)
    """

    name = "volatility"
    category = FactorCategory.SENTIMENT
    default_weight = 0.05
    min_history_days = 21

    def __init__(self, period: int = 20):
        self.period = period

    def calculate(self, sector_data: dict, history: list = None, context: dict = None) -> FactorResult:
        closes = [h.get("index_close", 0) for h in history[-self.period - 1:]]

        # 日收益率
        returns = []
        for i in range(1, len(closes)):
            if closes[i - 1] > 0:
                returns.append(np.log(closes[i] / closes[i - 1]))

        # 年化波动率
        hv = float(np.std(returns)) * np.sqrt(252) if returns else 0.0
        hv_pct = hv * 100

        # 评分: 低波动偏好(保守), 高波动容忍(激进)
        # 通用评分: 波动率越低越好
        if hv_pct < 15:
            score = 8.0 + (15 - hv_pct) / 15 * 2.0
        elif hv_pct < 25:
            score = 5.0 + (25 - hv_pct) / 10 * 3.0
        elif hv_pct < 40:
            score = 2.0 + (40 - hv_pct) / 15 * 3.0
        else:
            score = max(0, 2.0 - (hv_pct - 40) / 20 * 2.0)

        confidence = 0.8 if len(returns) >= 15 else 0.5

        return FactorResult(
            name=self.name,
            category=self.category,
            raw_value=hv,
            score=round(self.clamp(score), 2),
            weight=self.default_weight,
            confidence=round(confidence, 2),
            detail={
                "hv_pct": round(hv_pct, 2),
                "period": self.period,
                "data_points": len(returns),
            },
        )

    def validate_data(self, sector_data: dict, history: list = None) -> bool:
        if not history or len(history) < self.min_history_days:
            return False
        return all("index_close" in h for h in history[-self.min_history_days:])


class MarketBreadthFactor(BaseFactor):
    """市场广度因子

    衡量市场整体强弱的广度指标。
    公式: 涨跌比 = 上涨板块数 / 总板块数
    注: 此因子需要全市场数据，单独板块无法计算。
    作为板块中性因子使用，通过sector_data传入预计算值。
    """

    name = "market_breadth"
    category = FactorCategory.SENTIMENT
    default_weight = 0.05

    def calculate(self, sector_data: dict, history: list = None, context: dict = None) -> FactorResult:
        # 从sector_data获取预计算的市场广度
        breadth = sector_data.get("market_breadth", 0.5)

        # 评分: 涨跌比 > 0.7 强势(8-10), < 0.3 弱势(0-2)
        if breadth > 0.7:
            score = 8.0 + (breadth - 0.7) / 0.3 * 2.0
        elif breadth > 0.5:
            score = 5.0 + (breadth - 0.5) / 0.2 * 3.0
        elif breadth > 0.3:
            score = 2.0 + (breadth - 0.3) / 0.2 * 3.0
        else:
            score = max(0, breadth / 0.3 * 2.0)

        confidence = 0.6  # 市场广度数据可能不完全

        return FactorResult(
            name=self.name,
            category=self.category,
            raw_value=breadth,
            score=round(self.clamp(score), 2),
            weight=self.default_weight,
            confidence=round(confidence, 2),
            detail={"breadth": round(breadth, 4)},
        )

    def validate_data(self, sector_data: dict, history: list = None) -> bool:
        # 市场广度可以缺失，使用默认值
        return True


# 注册因子
FactorRegistry.register(VolumeRatioFactor())
FactorRegistry.register(VolatilityFactor())
FactorRegistry.register(MarketBreadthFactor())
