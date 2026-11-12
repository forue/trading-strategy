"""盘感训练 - 盘后总结

对已公开的训练区间做纯历史复盘：只用「当前这根及其之前」的数据识别
K线形态、洗盘、出货与背离，给出买/卖/观察点及可读的理由。

不含未来函数，也不接入 LLM：规则固定可复现，用户能逐条对照盘面核对。
"""
from datetime import datetime


def _sma(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = []
    total = 0.0
    for i, v in enumerate(values):
        total += v
        if i >= period:
            total -= values[i - period]
        out.append(total / period if i >= period - 1 else None)
    return out


def _ema(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    k = 2 / (period + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(out[-1] + k * (v - out[-1]))
    return out


def _macd(closes: list[float]) -> tuple[list[float], list[float], list[float]]:
    dif = [a - b for a, b in zip(_ema(closes, 12), _ema(closes, 26))]
    dea = _ema(dif, 9)
    return dif, dea, [2 * (a - b) for a, b in zip(dif, dea)]


def _rsi(closes: list[float], period: int = 14) -> list[float]:
    out = [50.0] * len(closes)
    for i in range(period, len(closes)):
        gains = losses = 0.0
        for j in range(i - period + 1, i + 1):
            d = closes[j] - closes[j - 1]
            if d >= 0:
                gains += d
            else:
                losses -= d
        out[i] = 100.0 if losses == 0 else round(100 - 100 / (1 + gains / losses), 2)
    return out


def _date(s: str):
    return datetime.strptime(s[:10], "%Y-%m-%d").date()


def _pct(a: float, b: float) -> float:
    return (a / b - 1) * 100 if b else 0.0


def _reason(tag: str, text: str, score: float, title: str) -> dict:
    return {"tag": tag, "text": text, "score": score, "title": title}


# ─────────────────────── 规则方向校准 ───────────────────────
# 教科书给的方向并不等于真实后续走势。离线评估：24 只 A 股 × 3 个一年窗口、69 段区间共
# 5203 次形态命中，按「形态出现的下一交易日开盘介入、第 5 日收盘退出」计算收益。
# 标的等分两组：方向表 bias/weight 只由第一组（half0）决定（样本≥8 且均值绝对值≥0.3%），
# 第二组 half1 完全不参与定向，仅用于事后检验稳健性；h1 仅供前端展示，不作为规则依据。
# side=教科书方向，r5/pos5 为两组合并描述（不参与定向）。
RULE_EDGE: dict[str, dict] = {
    "看涨吞没":            {"side": 1, "bias": 1, "weight": 0.51, "n": 901, "r5": 0.28, "pos5": 47.5, "h0": 0.61, "h1": -0.05},
    "看跌吞没":            {"side": -1, "bias": 1, "weight": 0.63, "n": 781, "r5": 0.14, "pos5": 47.5, "h0": 0.86, "h1": -0.56},
    "MACD 底背离":         {"side": 1, "bias": -1, "weight": 0.72, "n": 764, "r5": -0.51, "pos5": 42.9, "h0": -1.04, "h1": -0.14},
    "冲高回落长上影":       {"side": -1, "bias": 1, "weight": 0.73, "n": 384, "r5": 0.99, "pos5": 47.4, "h0": 1.05, "h1": 0.91},
    "RSI 顶背离":          {"side": -1, "bias": -1, "weight": 0.81, "n": 353, "r5": -0.70, "pos5": 44.5, "h0": -1.21, "h1": 0.04},
    "缩量回踩不破 MA20":    {"side": 1, "bias": 1, "weight": 1.00, "n": 286, "r5": 0.47, "pos5": 48.3, "h0": 1.63, "h1": -0.58},
    "放量突破平台":         {"side": 1, "bias": -1, "weight": 0.93, "n": 264, "r5": -2.10, "pos5": 33.3, "h0": -1.45, "h1": -2.75},
    "MACD 顶背离":         {"side": -1, "bias": -1, "weight": 0.49, "n": 261, "r5": -0.08, "pos5": 43.7, "h0": -0.57, "h1": 0.45},
    "早晨之星":            {"side": 1, "bias": 0, "weight": 0.00, "n": 249, "r5": 0.40, "pos5": 50.6, "h0": -0.18, "h1": 0.91},
    "盘中假跌破 MA20":      {"side": 1, "bias": -1, "weight": 0.46, "n": 242, "r5": -1.03, "pos5": 43.0, "h0": -0.52, "h1": -1.80},
    "黄昏之星":            {"side": -1, "bias": 1, "weight": 0.90, "n": 214, "r5": 0.77, "pos5": 49.1, "h0": 1.40, "h1": 0.33},
    "放量跌破 MA20":        {"side": -1, "bias": 1, "weight": 0.51, "n": 157, "r5": 0.80, "pos5": 49.7, "h0": 0.62, "h1": 0.98},
    "价升量缩背离":         {"side": -1, "bias": 0, "weight": 0.00, "n": 139, "r5": 0.20, "pos5": 43.9, "h0": -0.09, "h1": 0.63},
    "锤子线探底回升":       {"side": 1, "bias": 1, "weight": 0.97, "n": 104, "r5": 0.24, "pos5": 45.2, "h0": 1.54, "h1": -0.96},
    "大阴线次日缩量反包":   {"side": 1, "bias": 1, "weight": 0.38, "n": 52, "r5": -0.69, "pos5": 53.8, "h0": 0.36, "h1": -1.75},
    "高位巨量长上影":       {"side": -1, "bias": 0, "weight": 0.00, "n": 26, "r5": -1.19, "pos5": 34.6, "h0": -0.00, "h1": -2.81},
    "横盘缩量蓄势":         {"side": 1, "bias": 0, "weight": 0.00, "n": 11, "r5": 0.28, "pos5": 54.5, "h0": 0.27, "h1": 0.28},
    "高位巨量十字星":       {"side": -1, "bias": 0, "weight": 0.00, "n": 8, "r5": -3.53, "pos5": 12.5, "h0": -2.29, "h1": -7.25},
    "高位放量滞涨":         {"side": -1, "bias": 0, "weight": 0.00, "n": 7, "r5": 1.84, "pos5": 85.7, "h0": 5.78, "h1": 0.26},
}

# 理由 → 标准形态示意图的 key（背离类没有确定的K线外形，不给示意）
REASON_PATTERN: dict[str, str] = {
    "锤子线探底回升": "hammer",
    "看涨吞没": "bull_engulf",
    "看跌吞没": "bear_engulf",
    "早晨之星": "morning_star",
    "黄昏之星": "evening_star",
    "冲高回落长上影": "shooting_star",
    "高位巨量长上影": "shooting_star",
    "放量突破平台": "breakout",
    "高位巨量十字星": "high_cross",
    "高位放量滞涨": "high_stall",
    "缩量回踩不破 MA20": "pullback_no_break",
    "盘中假跌破 MA20": "pullback_ma20",
    "横盘缩量蓄势": "sideways",
    "大阴线次日缩量反包": "yin_rebound",
    "放量跌破 MA20": "breakdown_ma20",
}

# 标准形态示意图：[open, high, low, close] 归一化到 0~100，focus 恒为最后一根（触发根）。
# 每根示意都按本系统的识别规则校验过，rule 是规则里画不出来的量能/均线条件，
# 前端一并展示，避免把示意图误当成完整判定条件。
PATTERN_SHAPES: dict[str, dict] = {
    "hammer": {"name": "锤子线", "focus": 2,
               "bars": [[58, 59, 47, 48], [48, 49, 38, 39], [39, 41, 20, 40]],
               "rule": "前 5 日跌超 3%；下影 ≥ 2 倍实体、上影 ≤ 实体；收阳且振幅 > 前收 2%",
               "note": "下跌末端小实体、长下影，盘中探底被拉回；常见于止跌，但需次日确认。"},
    "bull_engulf": {"name": "看涨吞没", "focus": 1,
                    "bars": [[58, 59, 45, 46], [45, 62, 44, 61]],
                    "rule": "前一日收阴；当日收阳、实体 > 前日 1.2 倍，开盘 ≤ 前收且收盘 > 前开（实体完全反包）",
                    "note": "先阴后阳，阳线实体完全包住前一根阴线，代表多头反包。"},
    "bear_engulf": {"name": "看跌吞没", "focus": 1,
                    "bars": [[40, 56, 39, 55], [56, 57, 36, 37]],
                    "rule": "前一日收阳；当日收阴、实体 > 前日 1.2 倍，开盘 ≥ 前收且收盘 < 前开",
                    "note": "先阳后阴，阴线实体完全包住前一根阳线，代表冲高被空方接管。"},
    "morning_star": {"name": "早晨之星", "focus": 2,
                     "bars": [[60, 61, 43, 44], [43, 46, 41, 42], [43, 60, 42, 59]],
                     "rule": "首根收阴；中间根实体占其振幅 < 30% 且收盘低于首根收盘；第三根收阳并收复首根实体一半以上",
                     "note": "大阴线 → 跳空小实体 → 大阳线。规则未限定首尾实体大小，真实命中常是缩小版，不必与示意等比例。"},
    "evening_star": {"name": "黄昏之星", "focus": 2,
                     "bars": [[40, 58, 39, 57], [57, 60, 55, 58], [57, 58, 37, 38]],
                     "rule": "首根收阳；中间根实体占其振幅 < 30% 且收盘高于首根收盘；第三根收阴并跌回首根实体一半以下",
                     "note": "大阳线 → 跳空小实体 → 大阴线。规则未限定首尾实体大小，真实命中常是缩小版。"},
    "shooting_star": {"name": "射击之星 / 长上影", "focus": 1,
                      "bars": [[42, 44, 40, 43], [43, 66, 42, 45]],
                      "rule": "上影 ≥ 2 倍实体；「冲高回落」另需前 5 日涨超 5%、振幅 > 前收 3%，"
                              "「高位巨量长上影」另需 60 日分位 > 75% 且量比 > 1.8",
                      "note": "上涨后冲高回落，上影线 ≥ 2 倍实体，显示上方抛压。"},
    "breakout": {"name": "放量突破平台", "focus": 3,
                 "bars": [[48, 50, 47, 49], [49, 51, 48, 50], [50, 52, 49, 51], [51, 64, 50, 63]],
                 "rule": "收盘突破前 20 日最高价，当日涨幅 > 3%，量能 > 5 日均量 1.5 倍",
                 "note": "横盘后放量长阳突破前 20 日高点。示意只画 3 根平台，真实平台是 20 日；教科书视为买点，"
                         "但本系统样本中后续 5 日多为回落。"},
    "high_cross": {"name": "高位巨量十字星", "focus": 2,
                   "bars": [[44, 52, 43, 51], [51, 54, 50, 53], [53, 66, 44, 54]],
                   "rule": "实体占振幅 < 15%，20 日累涨 > 15%，量能 > 5 日均量 1.8 倍",
                   "note": "高位放巨量却收出极小实体，多空分歧极大；量能条件在K线图中看不出来。"},
    "high_stall": {"name": "高位放量滞涨", "focus": 3,
                   "bars": [[46, 50, 45, 49], [49, 54, 48, 53], [53, 58, 52, 57], [57, 60, 55, 57.5]],
                   "rule": "20 日累涨 > 15%、处近 60 日 80% 分位以上，量能 > 2 倍但当日涨幅 < 1.5%",
                   "note": "连续上涨后放出大量，末根几乎收平，买盘承接转弱；示意末根涨幅刻意小于 1.5%。"},
    "pullback_no_break": {"name": "缩量回踩不破 MA20", "focus": 2,
                          "bars": [[48, 50, 47, 49], [49, 55, 48, 54], [54, 55, 50, 51]],
                          "rule": "MA5 > MA20 且 20 日上涨；当日跌 1.5%~8%、收盘仍在 MA20 上方，量能 < 5 日均量 75%",
                          "note": "上升趋势里一根缩量中阴，收盘没有跌破均线、也没有长下影；"
                                  "与「盘中假跌破」的区别是根本没有破线。"},
    "pullback_ma20": {"name": "盘中假跌破 MA20", "focus": 2,
                      "bars": [[52, 55, 51, 54], [54, 55, 50, 51], [51, 53, 43, 52]],
                      "rule": "MA5 > MA20 且 20 日上涨；盘中最低跌破 MA20、收盘收回，下影长于实体",
                      "note": "盘中破线后收回，下影长于实体，是典型的假跌破洗盘；"
                              "MA20 与量能条件在K线图中未画出。本系统样本中该形态后续偏弱。"},
    "sideways": {"name": "横盘缩量蓄势", "focus": 5,
                 "bars": [[50, 51, 49, 50.5], [50.5, 51.5, 50, 51], [51, 52, 50.5, 50.8],
                          [50.8, 51.8, 50.3, 51.2], [51.2, 52, 50.8, 51], [51, 51.8, 50.6, 51.3]],
                 "rule": "均线多头排列；近 10 日振幅 < 8%，5 日均量 < 10 日均量 85%（每 10 根检查一次）",
                 "note": "窄幅横盘、波动收敛，量能持续萎缩；这是量价状态而非某根K线的形状，示意只画横盘外形。"},
    "yin_rebound": {"name": "大阴线次日缩量反包", "focus": 2,
                    "bars": [[56, 57, 55, 56], [56, 57, 46, 47], [48, 58, 47, 57]],
                    "rule": "前一日跌超 4%；当日收阳、收盘越过前日开盘价，成交量 < 前日 90%（不要求实体吞没）",
                    "note": "大阴线后缩量收阳、收盘越过前日开盘，但开盘价高于前日收盘，"
                            "因此不是「看涨吞没」那种实体完全反包。"},
    "breakdown_ma20": {"name": "放量跌破 MA20", "focus": 2,
                       "bars": [[56, 58, 55, 57], [57, 58, 53, 54], [54, 55, 41, 42]],
                       "rule": "前一日收盘仍在 MA20 上方；当日跌超 2%、收盘跌破 MA20，量能 > 5 日均量 1.2 倍",
                       "note": "放量长阴跌破 MA20，趋势转弱；本系统样本中 10 日后常出现反弹。"},
}

METHOD_NOTE = (
    "参考点按当日收盘后可见的信息逐根扫描生成，没有事后挑选「最像转折点」的位置；"
    "方向取自离线校准（24 只 A 股 × 3 个一年窗口、69 段区间 5203 次形态命中，"
    "按下一交易日开盘介入、第 5 日收盘退出统计）；标的等分两组，方向只由第一组确定，"
    "第二组不参与定向、仅用于检验稳健性，样本不足或方向不显著的规则一律标中性。"
    "统计是历史描述，不是预测；形态后短期走势在两组样本间差异很大，请把它当作对照材料而非买卖指令。"
)


def _kline_patterns(bars: list[dict], i: int, ctx: dict) -> list[dict]:
    """单根 / 双根 / 三根K线形态"""
    b, p = bars[i], bars[i - 1]
    body = ctx["body"]
    rng = ctx["rng"]
    out: list[dict] = []
    if body <= 0 or rng <= 0:
        return out

    upper, lower = ctx["upper"], ctx["lower"]
    p_body = abs(p["close"] - p["open"])
    chg = ctx["chg"]
    run5 = ctx["run5"]
    run20 = ctx["run20"]

    # 锤子线：下跌末端长下影收回
    if lower >= 2 * body and upper <= body and b["close"] > b["open"] and run5 < -3 and rng / p["close"] > 0.02:
        out.append(_reason("形态", f"下影线是实体的 {lower / body:.1f} 倍，盘中探至 {b['low']:.2f} 后被拉回，"
                                  f"此前 5 日已跌 {abs(run5):.1f}%，属下跌末端的探底回升（锤子线）", 1.5, "锤子线探底回升"))

    # 吞没
    if p["close"] < p["open"] and chg > 0 and b["close"] > p["open"] and b["open"] <= p["close"] and body > p_body * 1.2:
        out.append(_reason("形态", f"阳线实体 {body:.2f} 完全包住前一日阴线（{p_body:.2f}），收盘 {b['close']:.2f} 高于前日开盘，"
                                  "多头反包（看涨吞没）", 2.0, "看涨吞没"))
    if p["close"] > p["open"] and chg < 0 and b["close"] < p["open"] and b["open"] >= p["close"] and body > p_body * 1.2:
        out.append(_reason("形态", f"阴线实体 {body:.2f} 完全包住前一日阳线，收盘 {b['close']:.2f} 低于前日开盘，"
                                  "冲高被空方接管（看跌吞没）", -2.0, "看跌吞没"))

    # 星线（早晨 / 黄昏）
    if i >= 2:
        pp = bars[i - 2]
        mid = (pp["open"] + pp["close"]) / 2
        small = abs(p["close"] - p["open"]) / (p["high"] - p["low"]) if p["high"] > p["low"] else 1
        if (pp["close"] < pp["open"] and small < 0.3 and p["close"] < pp["close"]
                and b["close"] > b["open"] and b["close"] > mid):
            out.append(_reason("形态", "大阴线后接十字小实体，第三根阳线收复首根阴线一半以上，构成早晨之星", 2.5, "早晨之星"))
        if (pp["close"] > pp["open"] and small < 0.3 and p["close"] > pp["close"]
                and b["close"] < b["open"] and b["close"] < mid):
            out.append(_reason("形态", "大阳线后接十字小实体，第三根阴线跌回首根阳线一半以下，构成黄昏之星", -2.5, "黄昏之星"))

    # 射击之星 / 长上影
    if upper >= 2 * body and rng / p["close"] > 0.03 and run5 > 5 and b["close"] < b["high"] * 0.99:
        out.append(_reason("形态", f"上影线是实体的 {upper / body:.1f} 倍，此前 5 日涨 {run5:.1f}% 后冲高 {b['high']:.2f} 回落，"
                                  "上方抛压明显（射击之星）", -1.5, "冲高回落长上影"))

    # 放量长阳突破平台
    prev20_high = max(x["high"] for x in bars[i - 20:i]) if i >= 20 else None
    if prev20_high and b["close"] > prev20_high and ctx["vol_ratio"] > 1.5 and chg > 3:
        out.append(_reason("形态", f"收盘 {b['close']:.2f} 突破前 20 日高点 {prev20_high:.2f}，"
                                  f"当日涨 {chg:.1f}% 且量能为 5 日均量的 {ctx['vol_ratio']:.1f} 倍（放量突破）",
                           2.0, "放量突破平台"))

    # 高位巨量十字星
    if body / rng < 0.15 and ctx["vol_ratio"] > 1.8 and run20 > 15:
        out.append(_reason("形态", f"20 日已涨 {run20:.1f}%，当日实体仅占振幅 {body / rng * 100:.0f}% 却放出 "
                                  f"{ctx['vol_ratio']:.1f} 倍量，多空分歧极大（高位巨量十字星）", -2.0, "高位巨量十字星"))
    return out


def _washout(bars: list[dict], i: int, ctx: dict) -> list[dict]:
    """洗盘：上升趋势里制造恐慌但筹码不松动的动作"""
    b, p = bars[i], bars[i - 1]
    ma5, ma20 = ctx["ma5"], ctx["ma20"]
    out: list[dict] = []
    if ma5 is None or ma20 is None or not ma20:
        return out
    uptrend = ma5 > ma20 and ctx["run20"] > 0
    chg, vr = ctx["chg"], ctx["vol_ratio"]

    if uptrend and -8 <= chg < -1.5 and b["close"] >= ma20 * 0.99 and vr < 0.75:
        out.append(_reason("洗盘", f"均线仍多头排列（MA5 {ma5:.2f} > MA20 {ma20:.2f}），当日跌 {abs(chg):.1f}% "
                                  f"但收盘 {b['close']:.2f} 未破 MA20，量能只有 5 日均量的 {vr:.2f} 倍，"
                                  "属缩量回踩而非放量出逃", 1.5, "缩量回踩不破 MA20"))

    if uptrend and b["low"] < ma20 <= b["close"] and ctx["lower"] > ctx["body"]:
        out.append(_reason("洗盘", f"盘中最低 {b['low']:.2f} 跌破 MA20 {ma20:.2f}，收盘 {b['close']:.2f} 又收回，"
                                  "下影线长于实体，是典型的假跌破洗盘", 2.0, "盘中假跌破 MA20"))

    prev_chg = _pct(p["close"], bars[i - 2]["close"]) if i >= 2 else 0
    if prev_chg <= -4 and chg > 0 and b["close"] > p["open"] and p["volume"] and b["volume"] < p["volume"] * 0.9:
        out.append(_reason("洗盘", f"前一日大阴线跌 {abs(prev_chg):.1f}%，今日以更小成交量收复其开盘价 {p['open']:.2f}，"
                                  "恐慌盘被快速消化（阴线反包）", 2.0, "大阴线次日缩量反包"))

    if i >= 12 and uptrend and i % 10 == 0:
        win = bars[i - 10:i]
        swing = (max(x["high"] for x in win) - min(x["low"] for x in win)) / min(x["low"] for x in win) * 100
        if swing < 8 and ctx["vol_ma5"] < ctx["vol_ma10"] * 0.85:
            out.append(_reason("洗盘", f"近 10 日振幅仅 {swing:.1f}%，5 日均量已降到 10 日均量的 "
                                      f"{ctx['vol_ma5'] / ctx['vol_ma10']:.2f} 倍，均线仍向上，属横盘缩量蓄势",
                               1.0, "横盘缩量蓄势"))
    return out


def _distribution(bars: list[dict], i: int, ctx: dict) -> list[dict]:
    """出货：高位放量滞涨、破位与涨幅衰竭"""
    b = bars[i]
    ma20 = ctx["ma20"]
    out: list[dict] = []
    chg, vr = ctx["chg"], ctx["vol_ratio"]
    run20, pos60 = ctx["run20"], ctx["pos60"]

    if run20 > 15 and pos60 > 0.8 and vr > 2 and chg < 1.5:
        out.append(_reason("出货", f"20 日累涨 {run20:.1f}%、价格处于近 60 日 {pos60 * 100:.0f}% 分位，"
                                  f"当日放出 {vr:.1f} 倍量却只涨 {chg:.1f}%，放量滞涨是高位派发的典型特征",
                           -2.5, "高位放量滞涨"))

    if pos60 > 0.75 and vr > 1.8 and ctx["upper"] >= 2 * ctx["body"]:
        out.append(_reason("出货", f"高位 {vr:.1f} 倍量冲高 {b['high']:.2f} 后收在 {b['close']:.2f}，"
                                  f"上影线是实体 {ctx['upper'] / max(ctx['body'], 1e-6):.1f} 倍，拉高兑现迹象明显",
                           -2.0, "高位巨量长上影"))

    if i >= 1 and ma20 and bars[i - 1]["close"] >= ma20 and b["close"] < ma20 and chg < -2 and vr > 1.2:
        out.append(_reason("出货", f"放量跌破 MA20 {ma20:.2f}（当日 {chg:.1f}%、{vr:.1f} 倍量），"
                                  "趋势由多头转弱，反抽不站回应减仓", -2.0, "放量跌破 MA20"))

    if i >= 3 and run20 > 12:
        last3 = bars[i - 2:i + 1]
        if all(x["volume"] > 1.5 * ctx["vol_ma5"] for x in last3) and _pct(b["close"], bars[i - 3]["close"]) < 2:
            out.append(_reason("出货", f"连续 3 日放量（均超 {ctx['vol_ma5']:.0f} 手）但累计涨幅不足 2%，"
                                      "买盘承接转弱、上攻衰竭", -1.5, "连续放量涨幅收窄"))
    return out


def _divergence(bars: list[dict], i: int, ctx: dict, closes: list[float],
                dif: list[float], rsi: list[float], vol_ma5: list[float | None]) -> list[dict]:
    """背离：价与 MACD / 量能 / RSI 不同步"""
    b = bars[i]
    out: list[dict] = []
    if i < 21:
        return out
    win_close = closes[i - 20:i]
    win_dif = dif[i - 20:i]
    win_rsi = rsi[i - 20:i]

    if b["close"] > max(win_close) and dif[i] > 0 and dif[i] < max(win_dif):
        out.append(_reason("背离", f"收盘 {b['close']:.2f} 创 20 日新高，但 DIF {dif[i]:.3f} 低于前高 "
                                  f"{max(win_dif):.3f}，MACD 顶背离，上攻动能减弱", -2.5, "MACD 顶背离"))
    if b["close"] < min(win_close) and dif[i] < 0 and dif[i] > min(win_dif):
        out.append(_reason("背离", f"收盘 {b['close']:.2f} 创 20 日新低，但 DIF {dif[i]:.3f} 高于前低 "
                                  f"{min(win_dif):.3f}，MACD 底背离，杀跌动能衰减", 2.5, "MACD 底背离"))
    if (b["close"] > max(win_close) and ctx["run20"] > 8 and vol_ma5[i] and vol_ma5[i - 10]
            and vol_ma5[i] < vol_ma5[i - 10] * 0.8):
        out.append(_reason("背离", f"价格创 20 日新高，5 日均量却从 {vol_ma5[i - 10]:.0f} 手降到 "
                                  f"{vol_ma5[i]:.0f} 手，量价背离、追涨资金不足", -1.5, "价升量缩背离"))
    if b["close"] > max(win_close) and rsi[i] > 70 and rsi[i] < max(win_rsi):
        out.append(_reason("背离", f"价格新高而 RSI14 {rsi[i]:.1f} 低于前高 {max(win_rsi):.1f}，"
                                  "超买区动能背离", -1.5, "RSI 顶背离"))
    return out


def _decorate_reasons(found: list[dict]) -> list[dict]:
    """把识别出的形态补上离线校准方向、历史统计与标准图形 key"""
    out = []
    for r in found:
        edge = RULE_EDGE.get(r["title"], {})
        side = edge.get("side", 1 if r["score"] > 0 else -1)
        bias = edge.get("bias", 0)
        out.append({
            "tag": r["tag"],
            "text": r["text"],
            "title": r["title"],
            "bias": bias,
            "weight": edge.get("weight", 0.0),
            "contrarian": bias != 0 and bias != side,
            "pattern": REASON_PATTERN.get(r["title"]),
            "stat": {
                "n": edge.get("n", 0),
                "r5": edge.get("r5", 0.0),
                "pos5": edge.get("pos5", 0.0),
                "h0": edge.get("h0", 0.0),
                "h1": edge.get("h1", 0.0),
                "side": side,
            },
        })
    return out


def build_review(bars: list[dict], start_date: str, end_date: str) -> dict:
    """生成盘后总结

    Args:
        bars: 含指标预热段的日线（升序），可长于训练区间
        start_date / end_date: 训练区间首尾（含）

    逐根按「当根及其之前」的信息识别形态，方向只用离线校准过的规则；
    不按分数全局挑点、不为凑四类硬选，输出顺序即时间顺序。
    """
    train = [b for b in bars if start_date <= b["date"] <= end_date]
    base = {"range": {"start": start_date, "end": end_date, "bars": len(train)},
            "summary": "", "method": METHOD_NOTE, "patterns": PATTERN_SHAPES,
            "signals": [], "counts": {}}
    if len(train) < 25:
        base["summary"] = "训练区间数据不足，无法生成盘后总结"
        return base

    closes = [b["close"] for b in bars]
    vols = [float(b["volume"] or 0) for b in bars]
    ma5, ma10, ma20, ma60 = (_sma(closes, p) for p in (5, 10, 20, 60))
    vol_ma5, vol_ma10 = _sma(vols, 5), _sma(vols, 10)
    dif, dea, _hist = _macd(closes)
    rsi = _rsi(closes)
    offset = next(i for i, b in enumerate(bars) if b["date"] >= start_date)

    signals: list[dict] = []
    for i in range(offset, offset + len(train)):
        b, p = bars[i], bars[i - 1]
        if not p["close"] or ma20[i] is None or i < 21:
            continue
        body = abs(b["close"] - b["open"])
        rng = b["high"] - b["low"]
        if rng <= 0:
            continue
        highs = [x["high"] for x in bars[i - 59:i + 1]]
        lows = [x["low"] for x in bars[i - 59:i + 1]]
        span = max(highs) - min(lows)
        ctx = {
            "body": body, "rng": rng,
            "upper": b["high"] - max(b["open"], b["close"]),
            "lower": min(b["open"], b["close"]) - b["low"],
            "chg": _pct(b["close"], p["close"]),
            "run5": _pct(b["close"], bars[i - 5]["close"]) if i >= 5 else 0.0,
            "run20": _pct(b["close"], bars[i - 20]["close"]),
            "vol_ratio": vols[i] / vol_ma5[i] if vol_ma5[i] else 0.0,
            "vol_ma5": vol_ma5[i] or 0.0, "vol_ma10": vol_ma10[i] or 0.0,
            "ma5": ma5[i], "ma20": ma20[i],
            "pos60": (b["close"] - min(lows)) / span if span else 0.5,
        }
        found = (_kline_patterns(bars, i, ctx) + _washout(bars, i, ctx)
                 + _distribution(bars, i, ctx)
                 + _divergence(bars, i, ctx, closes, dif, rsi, vol_ma5))
        if not found:
            continue
        reasons = _decorate_reasons(found)
        # 只保留「有校准方向」或「多个形态共振」的点，纯中性单点不刷屏
        directional = [r for r in reasons if r["bias"]]
        if not directional and len(reasons) < 2:
            continue
        net = sum(r["bias"] * r["weight"] for r in reasons)
        total_w = sum(r["weight"] for r in directional) or 1.0
        agree = sum(r["weight"] for r in directional
                    if r["bias"] == (1 if net > 0 else -1)) / total_w
        # 多规则同向才给方向；提高门槛会让信号变少但在样本外反而更不稳定（实测），
        # 故保持较低门槛，由面板滚动展示，并明确标注这些不是买卖指令
        if abs(net) >= 0.6 and agree >= 0.8:
            action = "buy" if net > 0 else "sell"
            confidence = "高" if abs(net) >= 1.0 else "中"
        else:
            action, confidence = "watch", "—"

        # 失效位只取触发根及其之前的价格，窗口也只到触发根，避免任何未来信息
        window = bars[max(0, i - 8):i + 1]
        invalidate = (min(x["low"] for x in window[-3:]) if action != "sell"
                      else max(x["high"] for x in window[-3:]))
        signal = {
            "no": i - offset + 1,
            "date": b["date"],
            "price": round(b["close"], 3),
            "score": round(net, 2),          # 兼容旧前端字段
            "net": round(net, 2),
            "action": action,
            "confidence": confidence,
            "title": max(reasons, key=lambda r: (r["weight"], bool(r["pattern"])))["title"],
            "execute": "下一交易日开盘",
            "horizon": 5,
            "invalidate": round(invalidate, 3),
            "focus": len(window) - 1,
            "window": [{"d": x["date"], "o": round(x["open"], 3), "h": round(x["high"], 3),
                        "l": round(x["low"], 3), "c": round(x["close"], 3),
                        "v": x.get("volume") or 0} for x in window],
            "reasons": reasons[:5],
        }
        # 同向冷却：逐根滚动，不按分数重排、不补足固定条数；中性观察点间隔放宽
        gap = 12 if action == "watch" else 8
        if any(abs(signal["no"] - k["no"]) < gap and signal["action"] == k["action"] for k in signals):
            continue
        signals.append(signal)

    change = _pct(train[-1]["close"], train[0]["close"])
    peak = train[0]["close"]
    max_dd = 0.0
    for b in train:
        peak = max(peak, b["close"])
        max_dd = min(max_dd, _pct(b["close"], peak))
    counts: dict[str, int] = {}
    for s in signals:
        for r in s["reasons"]:
            counts[r["tag"]] = counts.get(r["tag"], 0) + 1
    buys = sum(1 for s in signals if s["action"] == "buy")
    sells = sum(1 for s in signals if s["action"] == "sell")
    base["summary"] = (
        f"训练区间共 {len(train)} 个交易日，收盘累计 {change:+.1f}%，最大回撤 {max_dd:.1f}%。"
        f"逐根扫描得到 {len(signals)} 个观察点（统计倾向偏多 {buys}、偏空 {sells}、"
        f"中性 {len(signals) - buys - sells}）；这些点不是事后挑选的最佳买卖点，"
        f"方向只是历史统计倾向，请结合失效位与自己的判断核对。"
    )
    base["range"] = {"start": start_date, "end": end_date, "bars": len(train),
                     "change_pct": round(change, 2), "max_drawdown": round(max_dd, 2)}
    base["signals"] = signals
    base["counts"] = counts
    return base
