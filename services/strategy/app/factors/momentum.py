"""动量因子 - 价格动量 + 相对强弱"""
import numpy as np
from .base import BaseFactor, FactorResult, FactorCategory, FactorRegistry


class PriceMomentumFactor(BaseFactor):
    """价格动量因子

    衡量板块近期价格变动的强度和方向。
    计算: N日收益率的动量得分。
    参考: Jegadeesh & Titman (1993) - Returns to buying winners and selling losers
    """

    name = "price_momentum"
    category = FactorCategory.MOMENTUM
    default_weight = 0.15
    min_history_days = 5

    def calculate(self, sector_data: dict, history: list = None) -> FactorResult:
        # 当日涨跌幅
        change_pct = sector_data.get("index_change_pct", 0)

        # 计算历史动量 (如果有多日数据)
        momentum_5d = change_pct
        momentum_10d = change_pct
        if history and len(history) >= 5:
            closes = [h.get("index_close", 0) for h in history[-5:]]
            if closes[0] > 0:
                momentum_5d = (closes[-1] / closes[0] - 1) * 100
        if history and len(history) >= 10:
            closes = [h.get("index_close", 0) for h in history[-10:]]
            if closes[0] > 0:
                momentum_10d = (closes[-1] / closes[0] - 1) * 100

        # 综合动量: 5日权重60%, 10日权重40%
        combined_momentum = momentum_5d * 0.6 + momentum_10d * 0.4

        # 评分: 涨跌幅1% = 2分, 基准5分
        score = self.clamp(5.0 + combined_momentum * 2.0)

        # 置信度: 有多日历史数据时更可靠
        confidence = 0.8 if history and len(history) >= 10 else 0.5

        return FactorResult(
            name=self.name,
            category=self.category,
            raw_value=combined_momentum,
            score=round(score, 2),
            weight=self.default_weight,
            confidence=round(confidence, 2),
            detail={
                "change_today": round(change_pct, 2),
                "momentum_5d": round(momentum_5d, 2),
                "momentum_10d": round(momentum_10d, 2),
            },
        )

    def validate_data(self, sector_data: dict, history: list = None) -> bool:
        return "index_change_pct" in sector_data


class RelativeStrengthFactor(BaseFactor):
    """相对强弱因子

    衡量板块相对市场整体的强弱程度。
    计算: 板块涨跌幅 - 市场平均涨跌幅
    """

    name = "relative_strength"
    category = FactorCategory.MOMENTUM
    default_weight = 0.10

    def calculate(self, sector_data: dict, history: list = None) -> FactorResult:
        change_pct = sector_data.get("index_change_pct", 0)

        # 市场平均涨跌幅 (从历史数据计算)
        market_avg = 0.0
        if history and len(history) > 0:
            market_changes = [h.get("index_change_pct", 0) for h in history]
            market_avg = float(np.mean(market_changes)) if market_changes else 0.0

        # 相对强弱 = 板块涨跌幅 - 市场平均
        rs = change_pct - market_avg

        # 评分: 相对强弱1% = 2分, 基准5分
        score = self.clamp(5.0 + rs * 2.0)

        # 置信度
        confidence = 0.7 if history and len(history) >= 5 else 0.4

        return FactorResult(
            name=self.name,
            category=self.category,
            raw_value=rs,
            score=round(score, 2),
            weight=self.default_weight,
            confidence=round(confidence, 2),
            detail={
                "change_pct": round(change_pct, 2),
                "market_avg": round(market_avg, 2),
                "relative_strength": round(rs, 2),
            },
        )

    def validate_data(self, sector_data: dict, history: list = None) -> bool:
        return "index_change_pct" in sector_data


# 注册因子
FactorRegistry.register(PriceMomentumFactor())
FactorRegistry.register(RelativeStrengthFactor())
