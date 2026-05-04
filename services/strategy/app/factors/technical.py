"""技术指标因子 - RSI / MACD / 布林带 / KDJ"""
import numpy as np
from .base import BaseFactor, FactorResult, FactorCategory, FactorRegistry


class RSIFactor(BaseFactor):
    """RSI 相对强弱指标

    衡量价格变动的速度和幅度，判断超买超卖状态。
    公式: RSI = 100 - 100 / (1 + RS), RS = 平均上涨幅度 / 平均下跌幅度
    参考: Wilder, J.W. (1978) New Concepts in Technical Trading Systems
    """

    name = "rsi_14"
    category = FactorCategory.TECHNICAL
    default_weight = 0.10
    min_history_days = 15

    def __init__(self, period: int = 14):
        self.period = period

    def calculate(self, sector_data: dict, history: list = None, context: dict = None) -> FactorResult:
        closes = [h.get("index_close", 0) for h in history]
        rsi = self._calc_rsi(closes, self.period)

        # 评分映射: RSI < 30 超卖(8-10), RSI > 70 超买(0-2)
        if rsi < 30:
            score = 8.0 + (30 - rsi) / 30 * 2.0
        elif rsi < 50:
            score = 5.0 + (50 - rsi) / 20 * 3.0
        elif rsi < 70:
            score = 2.0 + (70 - rsi) / 20 * 3.0
        else:
            score = max(0, 2.0 - (rsi - 70) / 30 * 2.0)

        # 判断RSI状态
        if rsi < 30:
            level = "oversold"
        elif rsi > 70:
            level = "overbought"
        elif rsi < 50:
            level = "weak"
        else:
            level = "strong"

        return FactorResult(
            name=self.name,
            category=self.category,
            raw_value=rsi,
            score=round(self.clamp(score), 2),
            weight=self.default_weight,
            confidence=0.8,
            detail={"period": self.period, "level": level},
        )

    def validate_data(self, sector_data: dict, history: list = None) -> bool:
        if not history or len(history) < self.min_history_days:
            return False
        return all("index_close" in h for h in history[-self.min_history_days:])

    @staticmethod
    def _calc_rsi(closes: list, period: int = 14) -> float:
        """计算RSI值"""
        if len(closes) < period + 1:
            return 50.0

        changes = np.diff(closes[-period - 1:])
        gains = np.where(changes > 0, changes, 0)
        losses = np.where(changes < 0, -changes, 0)

        avg_gain = np.mean(gains) if len(gains) > 0 else 0
        avg_loss = np.mean(losses) if len(losses) > 0 else 0

        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - 100.0 / (1.0 + rs)


class MACDFactor(BaseFactor):
    """MACD 指数平滑异同移动平均线

    通过快慢均线的差值判断趋势方向和强度。
    参考: Gerald Appel (1979) Technical Analysis
    """

    name = "macd"
    category = FactorCategory.TECHNICAL
    default_weight = 0.10
    min_history_days = 35

    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9):
        self.fast = fast
        self.slow = slow
        self.signal = signal

    def calculate(self, sector_data: dict, history: list = None, context: dict = None) -> FactorResult:
        closes = [h.get("index_close", 0) for h in history]
        dif, dea, macd_bar = self._calc_macd(closes, self.fast, self.slow, self.signal)

        # 评分逻辑
        score = 5.0
        if dif > dea and macd_bar > 0:
            score = 7.0 + min(macd_bar / 0.5, 3.0)  # 多头
        elif dif > dea:
            score = 5.0 + (dif - dea) * 10  # 多头减弱
        elif dif < dea and macd_bar < 0:
            score = 3.0 + min(abs(macd_bar) / 0.5, -3.0)  # 空头
        elif dif < dea:
            score = 5.0 - (dea - dif) * 10  # 空头减弱

        # 金叉/死叉信号
        signal = "hold"
        if len(closes) >= 2:
            prev_dif, prev_dea, _ = self._calc_macd(closes[:-1], self.fast, self.slow, self.signal)
            if prev_dif <= prev_dea and dif > dea:
                signal = "golden_cross"
                score += 1.5
            elif prev_dif >= prev_dea and dif < dea:
                signal = "death_cross"
                score -= 1.5

        return FactorResult(
            name=self.name,
            category=self.category,
            raw_value=dif,
            score=round(self.clamp(score), 2),
            weight=self.default_weight,
            confidence=0.8,
            detail={
                "dif": round(dif, 4),
                "dea": round(dea, 4),
                "macd_bar": round(macd_bar, 4),
                "signal": signal,
            },
        )

    def validate_data(self, sector_data: dict, history: list = None) -> bool:
        if not history or len(history) < self.min_history_days:
            return False
        return all("index_close" in h for h in history[-self.min_history_days:])

    @staticmethod
    def _calc_ema(data: list, period: int) -> list:
        """计算EMA"""
        if not data:
            return []
        k = 2.0 / (period + 1)
        ema = [data[0]]
        for i in range(1, len(data)):
            ema.append(data[i] * k + ema[-1] * (1 - k))
        return ema

    def _calc_macd(self, closes: list, fast: int, slow: int, signal: int) -> tuple:
        """计算MACD DIF/DEA/BAR"""
        if len(closes) < slow:
            return 0.0, 0.0, 0.0
        ema_fast = self._calc_ema(closes, fast)
        ema_slow = self._calc_ema(closes, slow)
        dif_list = [f - s for f, s in zip(ema_fast, ema_slow)]
        dea_list = self._calc_ema(dif_list, signal)
        dif = dif_list[-1]
        dea = dea_list[-1]
        macd_bar = 2 * (dif - dea)
        return dif, dea, macd_bar


class BollingerFactor(BaseFactor):
    """布林带因子

    基于统计学的价格通道，衡量波动率和价格位置。
    参考: John Bollinger (2001) Bollinger on Bollinger Bands
    """

    name = "bollinger"
    category = FactorCategory.TECHNICAL
    default_weight = 0.08
    min_history_days = 21

    def __init__(self, period: int = 20, multiplier: float = 2.0):
        self.period = period
        self.multiplier = multiplier

    def calculate(self, sector_data: dict, history: list = None, context: dict = None) -> FactorResult:
        closes = [h.get("index_close", 0) for h in history[-self.period:]]
        close = closes[-1] if closes else 0

        middle = np.mean(closes)
        std = np.std(closes)
        upper = middle + self.multiplier * std
        lower = middle - self.multiplier * std

        # %B = (close - lower) / (upper - lower)
        pct_b = (close - lower) / (upper - lower) if upper != lower else 0.5

        # 带宽
        bandwidth = (upper - lower) / middle if middle > 0 else 0

        # 评分: %B < 0 超卖(8-10), %B > 1 超买(0-2)
        if pct_b < 0:
            score = 8.0 + min(abs(pct_b) * 5, 2.0)
        elif pct_b < 0.2:
            score = 6.0 + (0.2 - pct_b) * 10
        elif pct_b < 0.8:
            score = 4.0 + (0.5 - pct_b) * 3.3
        elif pct_b <= 1.0:
            score = 2.0 + (1.0 - pct_b) * 10
        else:
            score = max(0, 2.0 - (pct_b - 1.0) * 5)

        # 波动率影响置信度
        confidence = 0.8 if 0.01 < bandwidth < 0.1 else 0.5

        return FactorResult(
            name=self.name,
            category=self.category,
            raw_value=pct_b,
            score=round(self.clamp(score), 2),
            weight=self.default_weight,
            confidence=round(confidence, 2),
            detail={
                "pct_b": round(pct_b, 4),
                "upper": round(upper, 2),
                "middle": round(middle, 2),
                "lower": round(lower, 2),
                "bandwidth": round(bandwidth, 4),
            },
        )

    def validate_data(self, sector_data: dict, history: list = None) -> bool:
        if not history or len(history) < self.min_history_days:
            return False
        return all("index_close" in h for h in history[-self.min_history_days:])


class KDJFactor(BaseFactor):
    """KDJ 随机指标

    衡量收盘价在一定周期内价格范围中的位置。
    参考: George Lane (1984) Lane's Stochastics
    """

    name = "kdj"
    category = FactorCategory.TECHNICAL
    default_weight = 0.07
    min_history_days = 10

    def __init__(self, period: int = 9):
        self.period = period

    def calculate(self, sector_data: dict, history: list = None, context: dict = None) -> FactorResult:
        k, d, j = self._calc_kdj(history, self.period)

        # 评分逻辑
        score = 5.0
        if k < 20 and d < 20:
            score = 8.0 + (20 - min(k, d)) / 20 * 2.0  # 超卖
        elif k > 80 and d > 80:
            score = 2.0 - (max(k, d) - 80) / 20 * 2.0  # 超买
        elif k > d:
            score = 6.0 + (k - d) / 20 * 2.0  # 多头
        else:
            score = 4.0 - (d - k) / 20 * 2.0  # 空头

        # 金叉/死叉
        signal = "hold"
        if len(history) >= 2:
            prev_k, prev_d, _ = self._calc_kdj(history[:-1], self.period)
            if prev_k <= prev_d and k > d:
                signal = "golden_cross"
                score += 1.5
            elif prev_k >= prev_d and k < d:
                signal = "death_cross"
                score -= 1.5

        return FactorResult(
            name=self.name,
            category=self.category,
            raw_value=k,
            score=round(self.clamp(score), 2),
            weight=self.default_weight,
            confidence=0.7,
            detail={"k": round(k, 2), "d": round(d, 2), "j": round(j, 2), "signal": signal},
        )

    def validate_data(self, sector_data: dict, history: list = None) -> bool:
        if not history or len(history) < self.min_history_days:
            return False
        required = ["index_close", "index_high", "index_low"]
        return all(all(k in h for k in required) for h in history[-self.min_history_days:])

    @staticmethod
    def _calc_kdj(history: list, period: int = 9) -> tuple:
        """计算KDJ"""
        if not history or len(history) < period:
            return 50.0, 50.0, 50.0

        recent = history[-period:]
        highest = max(h.get("index_high", 0) for h in recent)
        lowest = min(h.get("index_low", 0) for h in recent)
        close = recent[-1].get("index_close", 0)

        if highest == lowest:
            rsv = 50.0
        else:
            rsv = (close - lowest) / (highest - lowest) * 100

        # SMA平滑
        k = 2 / 3 * 50 + 1 / 3 * rsv
        d = 2 / 3 * 50 + 1 / 3 * k
        j = 3 * k - 2 * d

        return k, d, j


# 注册因子
FactorRegistry.register(RSIFactor())
FactorRegistry.register(MACDFactor())
FactorRegistry.register(BollingerFactor())
FactorRegistry.register(KDJFactor())
