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

    def calculate(self, sector_data: dict, history: list = None, context: dict = None) -> FactorResult:
        # 当日涨跌幅
        change_pct = sector_data.get("index_change_pct", 0)

        # 5日/10日真实收盘价动量（history 为板块历史K线，兼容 close/index_close 字段名）
        # 历史不足或收盘价缺失时退化为当日涨跌幅
        def _close_of(h):
            return h.get("index_close") or h.get("close", 0)
        momentum_5d = change_pct
        momentum_10d = change_pct
        if history and len(history) >= 5:
            closes = [_close_of(h) for h in history[-5:]]
            if closes[0] > 0:
                momentum_5d = (closes[-1] / closes[0] - 1) * 100
        if history and len(history) >= 10:
            closes = [_close_of(h) for h in history[-10:]]
            if closes[0] > 0:
                momentum_10d = (closes[-1] / closes[0] - 1) * 100
        # 综合动量: 5日权重60% + 10日权重40%
        # （已验证：5~20d 窗口动量高度相关、对权重稳健；60d 长期追高转负，故不纳入）
        combined_momentum = momentum_5d * 0.6 + momentum_10d * 0.4

        # 评分: 涨跌幅1% = 2分, 基准5分
        score = self.clamp(5.0 + combined_momentum * 2.0)

        # 置信度: 有足够历史数据时更可靠
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
    计算: 板块涨跌幅 - 同截面所有板块平均涨跌幅

    优先使用 context["changes_by_date"] 进行真正的截面比较；
    context 不可用时回退到 sector_data["market_avg_change"] 预计算值；
    两者都不可用时使用自身历史均值（置信度降低）。
    """

    name = "relative_strength"
    category = FactorCategory.MOMENTUM
    default_weight = 0.10

    @staticmethod
    def _norm_date(d) -> str:
        if d is None:
            return ""
        return str(d)[:10]

    def calculate(self, sector_data: dict, history: list = None, context: dict = None) -> FactorResult:
        change_pct = sector_data.get("index_change_pct", 0)

        market_avg = 0.0
        mode = "fallback_self_history"

        # 优先: 截面上下文 — 真正的板块间比较
        changes_by_date = (context or {}).get("changes_by_date") or {}
        today = self._norm_date(sector_data.get("date"))
        peers_today = changes_by_date.get(today) if today else None

        if peers_today and len(peers_today) >= 3:
            peer_changes = list(peers_today.values())
            market_avg = float(np.mean(peer_changes))
            mode = "cross_section"
        elif sector_data.get("market_avg_change") is not None:
            market_avg = float(sector_data["market_avg_change"])
            mode = "precomputed"
        elif history and len(history) > 0:
            market_changes = [h.get("index_change_pct", 0) for h in history]
            market_avg = float(np.mean(market_changes)) if market_changes else 0.0
            mode = "fallback_self_history"

        rs = change_pct - market_avg
        score = self.clamp(5.0 + rs * 2.0)

        if mode == "cross_section":
            confidence = 0.85
        elif mode == "precomputed":
            confidence = 0.7
        else:
            confidence = 0.4

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
                "mode": mode,
                "peer_count": len(peers_today) if peers_today else 0,
            },
        )

    def validate_data(self, sector_data: dict, history: list = None) -> bool:
        return "index_change_pct" in sector_data


# 注册因子
FactorRegistry.register(PriceMomentumFactor())
FactorRegistry.register(RelativeStrengthFactor())
