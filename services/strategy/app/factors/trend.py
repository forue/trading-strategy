"""趋势因子 - 均线交叉 / 趋势强度"""
import numpy as np
from .base import BaseFactor, FactorResult, FactorCategory, FactorRegistry


class MATrendFactor(BaseFactor):
    """均线趋势因子

    通过 MA5/MA20 和 MA10/MA60 双交叉判断趋势方向和强度。
    - 金叉（短均线 > 长均线）= 上升趋势，高分
    - 死叉（短均线 < 长均线）= 下降趋势，低分
    - 均线斜率 = 趋势加速度

    参考: Murphy, J. (1999) Technical Analysis of the Financial Markets
    """

    name = "ma_trend"
    category = FactorCategory.TECHNICAL
    default_weight = 0.10
    min_history_days = 20

    def calculate(self, sector_data: dict, history: list = None, context: dict = None) -> FactorResult:
        if not history or len(history) < 20:
            return FactorResult(
                name=self.name, category=self.category, raw_value=0.0,
                score=5.0, weight=self.default_weight, confidence=0.0,
                detail={"error": "历史数据不足20天"},
            )

        closes = [h.get("index_close", 0) for h in history]

        arr = np.array(closes, dtype=float)

        # 计算均线
        ma5 = float(np.mean(arr[-5:]))
        ma10 = float(np.mean(arr[-10:]))
        ma20 = float(np.mean(arr[-20:]))
        ma60 = float(np.mean(arr[-60:])) if len(arr) >= 60 else ma20
        current = arr[-1]

        # 1. MA5/MA20 交叉信号 (权重 60%)
        short_above_long_1 = ma5 > ma20
        # 2. MA10/MA60 交叉信号 (权重 40%)
        short_above_long_2 = ma10 > ma60

        # 历史交叉检测（前一日）
        if len(arr) >= 21:
            prev_ma5 = float(np.mean(arr[-6:-1]))
            prev_ma20 = float(np.mean(arr[-21:-1]))
            golden_cross_1 = prev_ma5 <= prev_ma20 and ma5 > ma20
            death_cross_1 = prev_ma5 >= prev_ma20 and ma5 < ma20
        else:
            golden_cross_1 = False
            death_cross_1 = False

        # 评分
        score = 5.0

        # MA5/MA20 贡献 (60%)
        if short_above_long_1:
            score += 1.5  # 短期趋势向上
        else:
            score -= 1.5  # 短期趋势向下

        # MA10/MA60 贡献 (40%)
        if short_above_long_2:
            score += 1.0  # 中期趋势向上
        else:
            score -= 1.0  # 中期趋势向下

        # 金叉/死叉加分
        if golden_cross_1:
            score += 1.0
        elif death_cross_1:
            score -= 1.0

        # 价格相对均线位置
        if current > ma20:
            score += 0.5  # 价格在20日线上方
        else:
            score -= 0.5

        # 均线斜率 (MA20 的 5日变化)
        if len(arr) >= 25:
            ma20_prev = float(np.mean(arr[-25:-5]))
            ma_slope = (ma20 - ma20_prev) / ma20_prev * 100 if ma20_prev > 0 else 0
            score += np.clip(ma_slope * 5, -1.0, 1.0)  # 斜率贡献 ±1 分
        else:
            ma_slope = 0

        # 信号判定
        if short_above_long_1 and short_above_long_2:
            signal = "strong_uptrend"
        elif short_above_long_1 and not short_above_long_2:
            signal = "weak_uptrend"
        elif not short_above_long_1 and short_above_long_2:
            signal = "weak_downtrend"
        else:
            signal = "strong_downtrend"

        return FactorResult(
            name=self.name,
            category=self.category,
            raw_value=ma5 - ma20,  # 正值=多头排列
            score=round(self.clamp(score), 2),
            weight=self.default_weight,
            confidence=0.8 if len(arr) >= 60 else 0.6,
            detail={
                "ma5": round(ma5, 2),
                "ma10": round(ma10, 2),
                "ma20": round(ma20, 2),
                "ma60": round(ma60, 2),
                "golden_cross": golden_cross_1,
                "death_cross": death_cross_1,
                "signal": signal,
            },
        )

    def validate_data(self, sector_data: dict, history: list = None) -> bool:
        return "index_close" in sector_data


class SectorDispersionFactor(BaseFactor):
    """板块离散度因子

    衡量全市场板块涨跌幅的分散程度。
    - 高离散度：板块分化明显，轮动策略有效
    - 低离散度：板块同涨同跌，轮动效果差

    通过 context["changes_by_date"] 获取截面数据计算。
    """

    name = "sector_dispersion"
    category = FactorCategory.ROTATION
    default_weight = 0.08
    min_history_days = 0

    def calculate(self, sector_data: dict, history: list = None, context: dict = None) -> FactorResult:
        if not context or "changes_by_date" not in context:
            return FactorResult(
                name=self.name, category=self.category, raw_value=0.0,
                score=5.0, weight=self.default_weight, confidence=0.0,
                detail={"error": "无截面数据"},
            )

        changes_by_date = context["changes_by_date"]
        dates = sorted(changes_by_date.keys())

        if len(dates) < 3:
            return FactorResult(
                name=self.name, category=self.category, raw_value=0.0,
                score=5.0, weight=self.default_weight, confidence=0.0,
                detail={"error": "截面数据不足"},
            )

        # 计算近5日的截面离散度（标准差）
        recent_dates = dates[-5:]
        dispersions = []
        for d in recent_dates:
            changes = list(changes_by_date[d].values())
            if len(changes) >= 3:
                dispersions.append(float(np.std(changes)))

        if not dispersions:
            return FactorResult(
                name=self.name, category=self.category, raw_value=0.0,
                score=5.0, weight=self.default_weight, confidence=0.0,
                detail={"error": "有效离散度数据不足"},
            )

        avg_dispersion = float(np.mean(dispersions))
        latest_dispersion = dispersions[-1]

        # 评分: 高离散度 = 轮动机会多 = 高分
        # A股板块日涨跌标准差通常在 0.5%~3% 之间
        if avg_dispersion > 2.5:
            score = 8.0 + min((avg_dispersion - 2.5) * 2, 2.0)
        elif avg_dispersion > 1.5:
            score = 6.0 + (avg_dispersion - 1.5) * 2.0
        elif avg_dispersion > 0.8:
            score = 4.0 + (avg_dispersion - 0.8) * 2.86
        else:
            score = max(0, 2.0 + avg_dispersion * 2.5)

        # 离散度上升趋势加分（轮动机会在增加）
        if len(dispersions) >= 3:
            trend = dispersions[-1] - dispersions[0]
            if trend > 0.3:
                score += 0.5  # 离散度扩大
            elif trend < -0.3:
                score -= 0.5  # 离散度收窄

        return FactorResult(
            name=self.name,
            category=self.category,
            raw_value=round(avg_dispersion, 4),
            score=round(self.clamp(score), 2),
            weight=self.default_weight,
            confidence=0.7 if len(dispersions) >= 3 else 0.4,
            detail={
                "avg_dispersion": round(avg_dispersion, 4),
                "latest_dispersion": round(latest_dispersion, 4),
                "sector_count": len(changes_by_date.get(dates[-1], {})),
            },
        )

    def validate_data(self, sector_data: dict, history: list = None) -> bool:
        return True  # 依赖 context 而非 history


# 注册因子
FactorRegistry.register(MATrendFactor())
FactorRegistry.register(SectorDispersionFactor())
