"""盘感训练 - 个股K线盲盒回放

训练流程：
1. 从 data-collector 的股票池随机抽一只标的，取库中（缺失则按需采集）近 5 年日线；
2. 随机截取其中一段连续一年作为训练区间，另取区间前 90 根作为指标预热（不展示）；
3. 初始只暴露前两个月的K线，用户按天/周推进，随时可全仓买入、卖出；
4. 回放结束（推进到区间末尾或主动结束）时强制平仓，公开标的与区间并落库统计。

防作弊：完整K线只存在于服务端 Redis 会话中，接口按 cursor 切片返回，
前端任何时刻都拿不到未来数据。
"""
import asyncio
import calendar
import json
import random
import uuid
from datetime import date, datetime, timedelta

import httpx
from fastapi import APIRouter, HTTPException
from loguru import logger

from .config import settings
from .influx_query import influx_query
from shared import RedisManager, success_response

router = APIRouter(prefix="/stock-sense", tags=["盘感训练"])
redis_mgr = RedisManager()

# ─── 交易规则（与实盘默认参数保持一致） ───
INITIAL_CAPITAL = 100000.0
COMMISSION_RATE = 0.0003
MIN_COMMISSION = 5.0
STAMP_TAX_RATE = 0.001      # 仅卖出
SLIPPAGE_RATE = 0.001

# ─── 训练区间参数 ───
WARMUP_BARS = 90            # 指标预热K线（不展示，保证 MA60/MACD 在首根可见K线上已收敛）
WINDOW_DAYS = 365           # 训练区间长度（自然日）
MIN_WINDOW_BARS = 230       # 一年内至少需要的交易日数（A股约 243）
MAX_GAP_DAYS = 30           # 区间内允许的最大单次缺口（更长视为长期停牌）
INITIAL_VIEW_MONTHS = 2     # 初始只展示前两个月的K线
MAX_PICK_ATTEMPTS = 8       # 随机抽题最多尝试次数（采集失败/数据不足时换标的）

SESSION_TTL = 4 * 3600      # 会话过期（秒）
RECORD_KEY_PREFIX = "stock_sense:records:"
SESSION_KEY_PREFIX = "stock_sense:session:"
READY_CODES_KEY = "stock_sense:ready_codes"
RECENT_CODES_PREFIX = "stock_sense:recent:"
EXCLUDE_RECENT = 10         # 抽题时排除该用户最近 N 轮训练过的标的，避免连续重复
WARM_BATCH = 12             # 每轮训练后台预热的标的本数
WARM_LOCK = "stock_sense:warm_lock"   # 预热互斥（避免并发采集同一批标的）
READY_TARGET = 120          # 已落库样本池达到该规模就不再预热
MAX_RECORDS = 200
MAX_LINES = 40               # 单轮训练最多保留的划线条数


# ─────────────────────────── 基础工具 ───────────────────────────

def _add_months(d: date, months: int) -> date:
    """自然月加减，日期溢出时取当月最后一天"""
    year = d.year + (d.month - 1 + months) // 12
    month = (d.month - 1 + months) % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _parse_date(s: str) -> date:
    return datetime.strptime(s[:10], "%Y-%m-%d").date()


def _ema(values: list[float], period: int) -> list[float]:
    """指数移动平均（首值用第一个价格初始化，与常见行情软件一致）"""
    if not values:
        return []
    k = 2 / (period + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(out[-1] + k * (v - out[-1]))
    return out


def _ma(values: list[float], period: int) -> list[float | None]:
    """简单移动平均，不足周期返回 None"""
    out: list[float | None] = []
    total = 0.0
    for i, v in enumerate(values):
        total += v
        if i >= period:
            total -= values[i - period]
        out.append(round(total / period, 3) if i >= period - 1 else None)
    return out


def _macd(closes: list[float]) -> dict:
    """MACD(12,26,9)：DIF、DEA、柱状值 MACD = 2*(DIF-DEA)"""
    if not closes:
        return {"dif": [], "dea": [], "macd": []}
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    dif = [a - b for a, b in zip(ema12, ema26)]
    dea = _ema(dif, 9)
    bar = [2 * (a - b) for a, b in zip(dif, dea)]
    r = lambda xs: [round(x, 3) for x in xs]  # noqa: E731
    return {"dif": r(dif), "dea": r(dea), "macd": r(bar)}


def _aggregate(bars: list[dict], view: str) -> list[dict]:
    """按周/月聚合日线；view=day 原样返回

    周按 ISO 自然周分组，月按自然月分组，日期取该分组最后一根K线的日期。
    """
    if view == "day" or len(bars) <= 1:
        return bars
    groups: dict[str, list[dict]] = {}
    order: list[str] = []
    for b in bars:
        d = _parse_date(b["date"])
        if view == "week":
            iso = d.isocalendar()
            key = f"{iso[0]}-W{iso[1]:02d}"
        else:
            key = f"{d.year}-{d.month:02d}"
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(b)

    out = []
    for key in order:
        g = groups[key]
        out.append({
            "date": g[-1]["date"],
            "open": g[0]["open"],
            "close": g[-1]["close"],
            "high": max(x["high"] for x in g),
            "low": min(x["low"] for x in g),
            "volume": sum(x["volume"] for x in g),
            "amount": sum(x["amount"] for x in g),
            "change_pct": round((g[-1]["close"] / g[0]["open"] - 1) * 100, 2) if g[0]["open"] else 0.0,
            "turnover": round(sum(x["turnover"] for x in g), 2),
        })
    return out


def _build_chart(seg: list[dict], train_start: int, view: str) -> dict:
    """可见K线 → 视图聚合 + 指标

    seg 含指标预热段，训练区间从 train_start 开始：
    - 指标在「含预热」的聚合序列上计算，保证首根可见K线的 MA/MACD 已收敛；
    - 返回的K线只从训练区间起点开始聚合，避免混入训练前数据。
    """
    agg_full = _aggregate(seg, view)
    agg_train = _aggregate(seg[train_start:], view)
    if not agg_full or not agg_train:
        return {"bars": [], "ma": {}, "macd": {}, "vol_ma": {}}

    closes = [b["close"] for b in agg_full]
    ma_periods = (5, 10, 20, 60) if view == "day" else (5, 10)
    ma = {f"ma{p}": _ma(closes, p) for p in ma_periods}
    macd = _macd(closes)
    vol_ma = {
        "vol_ma5": _ma([b["volume"] for b in agg_full], 5),
        "vol_ma10": _ma([b["volume"] for b in agg_full], 10),
    }

    # 按日期对齐到训练区间首根（同组收盘价一致，指标无需重算）
    start_date = agg_train[0]["date"]
    k = 0
    while k < len(agg_full) and agg_full[k]["date"] < start_date:
        k += 1
    n = len(agg_train)

    return {
        "bars": agg_train,
        "ma": {name: vals[k: k + n] for name, vals in ma.items()},
        "macd": {name: vals[k: k + n] for name, vals in macd.items()},
        "vol_ma": {name: vals[k: k + n] for name, vals in vol_ma.items()},
    }


# ─────────────────────────── 数据准备 ───────────────────────────

def _fetch_stock_pool() -> list[dict]:
    """从 data-collector 获取股票池（采集口径统一在该服务）"""
    with httpx.Client(timeout=30) as client:
        resp = client.get(f"{settings.data_collector_url}/stocks/pool")
        resp.raise_for_status()
        pool = (resp.json() or {}).get("data") or []
    return [s for s in pool if s.get("code")]


def _query_bars(code: str, years: int = 5) -> list[dict]:
    end = date.today()
    start = end - timedelta(days=365 * years)
    return influx_query.query_stock_kline(code, start.isoformat(), end.isoformat())


def _ensure_bars(code: str) -> list[dict]:
    """库中个股日线不足时，按需触发 data-collector 采集后回读"""
    bars = _query_bars(code)
    if len(bars) >= MIN_WINDOW_BARS + WARMUP_BARS:
        return bars

    end = date.today()
    start = end - timedelta(days=365 * 5)
    try:
        with httpx.Client(timeout=120) as client:
            client.post(
                f"{settings.data_collector_url}/collect/stock-kline",
                params={"code": code,
                        "start_date": start.strftime("%Y%m%d"),
                        "end_date": end.strftime("%Y%m%d")},
            )
    except Exception as e:
        logger.warning(f"个股 {code} 采集请求失败: {e}")
        return bars
    return _query_bars(code)


def _pick_window(bars: list[dict]) -> tuple[int, int] | None:
    """在日线序列中随机截取一段连续一年

    Returns:
        (start_idx, end_idx)：训练区间首根与末根在 bars 中的下标；无合规区间返回 None
    """
    n = len(bars)
    if n < MIN_WINDOW_BARS:
        return None
    dates = [_parse_date(b["date"]) for b in bars]

    candidates: list[tuple[int, int]] = []
    j = 0
    # 训练区间之前必须留够预热K线，否则首根可见K线的 MA60/MACD 仍未收敛
    for i in range(WARMUP_BARS, n):
        limit = dates[i] + timedelta(days=WINDOW_DAYS)
        while j + 1 < n and dates[j + 1] <= limit:
            j += 1
        if j <= i or j - i + 1 < MIN_WINDOW_BARS:
            continue
        # 区间内不得出现长期停牌（单次缺口超过 MAX_GAP_DAYS 视为不合格）
        if any((dates[k + 1] - dates[k]).days > MAX_GAP_DAYS for k in range(i, j)):
            continue
        candidates.append((i, j))

    return random.choice(candidates) if candidates else None


def _ready_codes() -> list[str]:
    """已落库过日线的股票代码（避免每轮都等待首次采集）"""
    try:
        return list(redis_mgr.client.smembers(READY_CODES_KEY) or [])
    except Exception:
        return []


def _mark_ready(code: str) -> None:
    try:
        redis_mgr.client.sadd(READY_CODES_KEY, code)
    except Exception:
        pass


def _recent_codes(user: str) -> list[str]:
    """该用户最近几轮抽到的标的（最近的在前，抽题时优先避开）"""
    try:
        return list(redis_mgr.client.lrange(RECENT_CODES_PREFIX + (user or "default"),
                                            0, EXCLUDE_RECENT - 1) or [])
    except Exception:
        return []


def _mark_recent(user: str, code: str) -> None:
    """记录本轮抽到的标的，供下一轮排除"""
    key = RECENT_CODES_PREFIX + (user or "default")
    try:
        redis_mgr.client.lpush(key, code)
        redis_mgr.client.ltrim(key, 0, EXCLUDE_RECENT - 1)
    except Exception:
        pass


def _pick_candidates(pool: list[dict], recent: list[str]) -> list[dict]:
    """抽样候选标的，按优先级排好序，调用方按顺序尝试

    顺序：近 N 轮没做过的已落库标的 → 做过的已落库标的（越久远越靠前）
    → 全池未落库标的（首次抽到要采集，放最后兜底）。

    已落库（InfluxDB 有日线）的代码抽到即可用，不必等 AkShare 采集。
    早期版本在已落库池很小时直接从池内重复抽（把刚做过的又塞回首位），
    导致样本池只有一两只时同一只标的连着出现好几轮，这里按冷热排序修正。
    """
    by_code = {s["code"]: s for s in pool}
    avoid = set(recent)
    ready = [c for c in _ready_codes() if c in by_code]
    fresh = [c for c in ready if c not in avoid]
    picks = [by_code[c] for c in random.sample(fresh, min(len(fresh), MAX_PICK_ATTEMPTS))]

    # 已落库且没做过的还不够：优先补全池没落库的（首次要采集，慢一点但不会重复），
    # 已落库池很小时正是这一步保证不会连着几轮抽到同一只
    if len(picks) < MAX_PICK_ATTEMPTS:
        used = {p["code"] for p in picks}
        rest = [s for s in pool if s["code"] not in used and s["code"] not in avoid]
        picks += random.sample(rest, min(len(rest), MAX_PICK_ATTEMPTS - len(picks)))

    # 全池也用尽（几乎不会发生）才回到最近做过的，越久远越靠前
    used = {p["code"] for p in picks}
    stale = [c for c in reversed(recent) if c in by_code and c not in used]
    picks += [by_code[c] for c in stale[: MAX_PICK_ATTEMPTS - len(picks)]]

    return picks or random.sample(pool, min(len(pool), MAX_PICK_ATTEMPTS))


def _build_session(user: str) -> dict:
    """随机抽题并构造会话（含指标预热段）"""
    pool = _fetch_stock_pool()
    if not pool:
        raise HTTPException(status_code=503, detail="股票池不可用，请检查 data-collector 服务")

    recent = _recent_codes(user)
    for pick in _pick_candidates(pool, recent):
        bars = _ensure_bars(pick["code"])
        window = _pick_window(bars)
        if not window:
            logger.info(f"个股 {pick['code']} 无合规一年区间，重新抽题")
            continue
        _mark_ready(pick["code"])
        _mark_recent(user, pick["code"])

        start_idx, end_idx = window
        warmup_start = max(0, start_idx - WARMUP_BARS)
        seg = bars[warmup_start:end_idx + 1]
        train_start = start_idx - warmup_start

        # 初始可见：训练区间起点起的前两个自然月
        limit = _add_months(_parse_date(seg[train_start]["date"]), INITIAL_VIEW_MONTHS)
        cursor = train_start
        for i in range(train_start, len(seg)):
            if _parse_date(seg[i]["date"]) <= limit:
                cursor = i
            else:
                break
        # 至少留一根未展示，避免开局即结束
        cursor = min(cursor, len(seg) - 2)
        cursor = max(cursor, train_start)

        return {
            "session_id": uuid.uuid4().hex,
            "user": user or "default",
            "code": pick["code"],
            "name": seg[train_start].get("stock_name") or pick.get("name") or pick["code"],
            "bars": seg,
            "train_start": train_start,
            "cursor": cursor,
            "cash": INITIAL_CAPITAL,
            "position": None,
            "lots": [],                  # 买入批次，卖出时按 FIFO 配对成本
            "trades": [],
            "lines": [],                 # 训练中用到的划线（锚点为 训练区间序号 + 价格）
            "ended": False,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }

    raise HTTPException(status_code=503, detail="暂时无法准备训练数据（数据源不可用），请稍后重试")


# 后台任务引用（asyncio 可能回收未被引用的任务）
_bg_tasks: set = set()


def _spawn(coro) -> None:
    """调度后台任务并持有引用，异常不影响主流程"""
    task = asyncio.create_task(coro)
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)


async def _warm_ready(user: str) -> None:
    """后台预热已落库样本

    抽题只在已落库标的中选才不会等 AkShare 采集，但初始样本很少（抽来抽去就那几只），
    所以每轮训练后在后台补采几只，逐步扩大抽题的随机范围。
    """
    try:
        ready = set(_ready_codes())
        if len(ready) >= READY_TARGET:
            logger.info(f"盘感训练样本池已达 {len(ready)} 只，跳过预热")
            return
        # 串行预热，避免用户连续点开始时并发重复采集（批量大，锁给足时间）
        if not redis_mgr.client.set(WARM_LOCK, "1", nx=True, ex=300):
            return
        pool = await asyncio.to_thread(_fetch_stock_pool)
        exclude = set(_recent_codes(user))
        codes = [s["code"] for s in pool if s["code"] not in ready and s["code"] not in exclude]
        if not codes:
            return
        for code in random.sample(codes, min(len(codes), WARM_BATCH)):
            try:
                bars = await asyncio.to_thread(_ensure_bars, code)
            except Exception as e:
                logger.warning(f"盘感训练样本预热失败 {code}: {e}")
                continue
            if len(bars) < WARMUP_BARS + MIN_WINDOW_BARS:
                # 历史太短的次新股放进来只会浪费抽题机会
                logger.info(f"盘感训练样本预热跳过: {code}（仅 {len(bars)} 根日线）")
                continue
            _mark_ready(code)
            logger.info(f"盘感训练样本预热完成: {code}（{len(bars)} 根日线）")
    except Exception as e:
        logger.warning(f"盘感训练样本预热任务异常: {e}")


# ─────────────────────────── 会话存取 ───────────────────────────

def _save(sess: dict) -> None:
    redis_mgr.set_json(SESSION_KEY_PREFIX + sess["session_id"], sess, ex=SESSION_TTL)


def _load(sid: str) -> dict:
    sess = redis_mgr.get_json(SESSION_KEY_PREFIX + sid)
    if not sess:
        raise HTTPException(status_code=404, detail="训练会话不存在或已过期")
    # 兼容本版本之前创建的会话（没有分批买入与划线字段）
    sess.setdefault("lots", [])
    sess.setdefault("lines", [])
    return sess


def _delete(sid: str) -> None:
    redis_mgr.delete(SESSION_KEY_PREFIX + sid)


def _mask_date(no: int) -> str:
    """结算前的对外日期：训练区间内第 no 根（1-based）

    真实日历日期会暗示大盘所处的周期位置（牛熊阶段、季报窗口、政策时点），
    训练中一律用序号代替，结算之后再还原。
    """
    return f"D{no:04d}"


def _date_no_map(sess: dict) -> dict[str, int]:
    """训练区间内 真实日期 → 序号（1-based）"""
    return {b["date"]: i + 1 for i, b in enumerate(sess["bars"][sess["train_start"]:])}


def _chart(sess: dict, view: str) -> dict:
    """会话 → 当前可见图表数据（只暴露 cursor 及之前的数据）

    结算前把K线日期换成训练区间序号，结算后才还原真实日期。
    每根K线都带 no（训练区间序号），前端划线按序号锚定，切换周期视图时据此对齐。
    """
    chart = _build_chart(sess["bars"][: sess["cursor"] + 1], sess["train_start"], view)
    order = _date_no_map(sess)
    chart["bars"] = [
        {**b, "no": order.get(b["date"], 1),
         "date": b["date"] if sess["ended"] else _mask_date(order.get(b["date"], 1))}
        for b in chart["bars"]
    ]
    return chart


# ─────────────────────────── 交易与结算 ───────────────────────────

def _mark_price(sess: dict) -> float:
    return sess["bars"][sess["cursor"]]["close"]


def _can_buy(sess: dict) -> bool:
    """现金是否够买一手（含佣金）；已持仓时仍允许加仓"""
    lot_amount = round(_mark_price(sess) * (1 + SLIPPAGE_RATE), 3) * 100
    return sess["cash"] >= lot_amount + max(lot_amount * COMMISSION_RATE, MIN_COMMISSION)


def _check_ratio(ratio: float) -> float:
    if not 0 < ratio <= 1:
        raise HTTPException(status_code=400, detail="仓位比例需在 0~1 之间")
    return ratio


def _buy(sess: dict, ratio: float = 1.0) -> None:
    """按可用现金的 ratio 份额买入（ratio=1 为满仓），已持仓时可继续加仓"""
    _check_ratio(ratio)
    bar = sess["bars"][sess["cursor"]]
    price = round(bar["close"] * (1 + SLIPPAGE_RATE), 3)

    budget = sess["cash"] if ratio >= 1 else sess["cash"] * ratio
    shares = int(budget / (price * 100)) * 100
    while shares > 0:
        amount = shares * price
        commission = max(amount * COMMISSION_RATE, MIN_COMMISSION)
        if amount + commission <= sess["cash"]:
            break
        shares -= 100
    if shares <= 0:
        detail = "可用资金不足，无法买入一手（100 股）" if ratio >= 1 else \
            f"该仓位对应的资金不足一手（100 股），请调大仓位"
        raise HTTPException(status_code=400, detail=detail)

    amount = shares * price
    commission = max(amount * COMMISSION_RATE, MIN_COMMISSION)
    cost = round(amount + commission, 2)
    sess["cash"] = round(sess["cash"] - cost, 2)
    sess["lots"].append({
        "shares": shares,
        "price": price,
        "fee": round(commission, 2),
        "date": bar["date"],
    })

    pos = sess["position"]
    if pos:
        # 加仓：成本价为不含费的加权成交价，含费成本累计到 cost_amount
        total = pos["shares"] + shares
        pos["cost_price"] = round((pos["cost_price"] * pos["shares"] + price * shares) / total, 3)
        pos["shares"] = total
        pos["cost_amount"] = round(pos["cost_amount"] + cost, 2)
        pos["buy_date"] = bar["date"]
        pos["buy_index"] = sess["cursor"]     # T+1 按最后一次买入计算
    else:
        sess["position"] = {
            "shares": shares,
            "cost_price": price,
            "cost_amount": cost,
            "buy_date": bar["date"],
            "buy_index": sess["cursor"],
        }
    sess["trades"].append({
        "action": "BUY",
        "date": bar["date"],
        "price": price,
        "shares": shares,
        "amount": round(amount, 2),
        "fee": round(commission, 2),
        "ratio": ratio,
    })


def _consume_lots(sess: dict, shares: int, price: float, fee: float, sell_date: str,
                  forced: bool) -> list[dict]:
    """按 FIFO 消耗买入批次，返回本次卖出的配对明细

    卖出费用（佣金+印花税）按成交股数摊到每个批次上，保证配对盈亏之和与账户实收一致。
    """
    left = shares
    matches: list[dict] = []
    while left > 0 and sess["lots"]:
        lot = sess["lots"][0]
        lot_shares = lot["shares"]
        used = min(left, lot_shares)
        # 批次被部分消耗时，佣金也要按份额同步扣减，否则剩余股份会重复计入整笔佣金
        lot_fee = lot["fee"] * (used / lot_shares)
        buy_cost = lot["price"] * used + lot_fee
        income = price * used - fee * (used / shares)
        matches.append({
            "buy_date": lot["date"],
            "buy_price": lot["price"],
            "sell_date": sell_date,
            "sell_price": price,
            "shares": used,
            "pnl": round(income - buy_cost, 2),
            "pnl_pct": round((income / buy_cost - 1) * 100, 2) if buy_cost else 0.0,
            "days": (_parse_date(sell_date) - _parse_date(lot["date"])).days,
            "forced": forced,
        })
        left -= used
        if used == lot_shares:
            sess["lots"].pop(0)
        else:
            lot["shares"] = lot_shares - used
            lot["fee"] = round(lot["fee"] - lot_fee, 2)
    return matches


def _sell(sess: dict, ratio: float = 1.0, forced: bool = False) -> None:
    """按持仓比例卖出（ratio=1 为清仓），不足一手时按一手向下取整"""
    pos = sess["position"]
    if not pos:
        raise HTTPException(status_code=400, detail="当前无持仓")
    if not forced:
        _check_ratio(ratio)
        if sess["cursor"] <= pos["buy_index"]:
            raise HTTPException(status_code=400, detail="T+1 限制：买入当日不可卖出，请先推进K线")

    if forced or ratio >= 1:
        shares = pos["shares"]
    else:
        shares = min(int(pos["shares"] * ratio / 100) * 100, pos["shares"])
    if shares <= 0:
        raise HTTPException(status_code=400, detail="当前持仓不足一手（100 股），无法按该仓位卖出")

    bar = sess["bars"][sess["cursor"]]
    price = round(bar["close"] * (1 - SLIPPAGE_RATE), 3)
    amount = shares * price
    commission = max(amount * COMMISSION_RATE, MIN_COMMISSION)
    fee = commission + amount * STAMP_TAX_RATE
    sess["cash"] = round(sess["cash"] + amount - fee, 2)
    matches = _consume_lots(sess, shares, price, fee, bar["date"], forced)
    sess["trades"].append({
        "action": "SELL",
        "date": bar["date"],
        "price": price,
        "shares": shares,
        "amount": round(amount, 2),
        "fee": round(fee, 2),
        "ratio": ratio,
        "forced": forced,
        "matches": matches,
    })

    remain = pos["shares"] - shares
    if remain <= 0:
        sess["position"] = None
    else:
        pos["shares"] = remain
        pos["cost_amount"] = round(pos["cost_amount"] * remain / (remain + shares), 2)


def _settle(sess: dict, forced_exit: bool) -> dict:
    """平仓结算并落库统计（调用方保证只执行一次）"""
    if sess["position"]:
        _sell(sess, forced=True)
        forced_exit = True

    bars = sess["bars"]
    start_bar = bars[sess["train_start"]]
    end_bar = bars[sess["cursor"]]
    final_equity = round(sess["cash"], 2)
    return_pct = round((final_equity / INITIAL_CAPITAL - 1) * 100, 2)
    benchmark_pct = round((end_bar["close"] / start_bar["close"] - 1) * 100, 2) if start_bar["close"] else 0.0

    buys = [t for t in sess["trades"] if t["action"] == "BUY"]
    sells = [t for t in sess["trades"] if t["action"] == "SELL"]
    pairs = [m for t in sells for m in t.get("matches", [])]
    hold_days = 0
    if buys and sells:
        hold_days = (_parse_date(sells[-1]["date"]) - _parse_date(buys[0]["date"])).days

    record = {
        "session_id": sess["session_id"],
        "user": sess["user"],
        "code": sess["code"],
        "name": sess["name"],
        "start_date": start_bar["date"],
        "end_date": end_bar["date"],
        "window_end": bars[-1]["date"],   # 原定训练区间末尾（复盘可看到结束后市）
        "initial_capital": INITIAL_CAPITAL,
        "final_equity": final_equity,
        "return_pct": return_pct,
        "benchmark_pct": benchmark_pct,
        "excess_pct": round(return_pct - benchmark_pct, 2),
        "trade_count": len(pairs),        # 一笔买入配一笔卖出的完成次数（分批交易按 FIFO 配对）
        "hold_days": hold_days,
        "forced_exit": forced_exit,
        "trades": sess["trades"],
        "pairs": pairs,
        "lines": sess.get("lines", []),   # 训练中画的线，复盘按同一套序号还原
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }

    key = RECORD_KEY_PREFIX + sess["user"]
    try:
        redis_mgr.client.lpush(key, json.dumps(record, ensure_ascii=False))
        redis_mgr.client.ltrim(key, 0, MAX_RECORDS - 1)
    except Exception as e:
        logger.error(f"写入盘感训练统计失败: {e}")

    return record


def _state(sess: dict) -> dict:
    """对外状态（结算前不暴露标的代码、名称与真实日期）"""
    bar = sess["bars"][sess["cursor"]]
    pos = sess["position"]
    ended = sess["ended"]
    market_value = round(pos["shares"] * bar["close"], 2) if pos else 0.0
    equity = round(sess["cash"] + market_value, 2)
    float_pnl_pct = None
    if pos:
        float_pnl_pct = round((market_value / pos["cost_amount"] - 1) * 100, 2)

    order = _date_no_map(sess)
    pos_out = None
    if pos:
        pos_out = dict(pos)
        if not ended:
            pos_out["buy_date"] = _mask_date(order.get(pos["buy_date"], 1))
    trades_out = sess["trades"]
    if not ended:
        trades_out = [
            {**t, "date": _mask_date(order.get(t["date"], 1))} for t in sess["trades"]
        ]

    return {
        "session_id": sess["session_id"],
        "ended": ended,
        "current_date": bar["date"]
        if ended
        else _mask_date(sess["cursor"] - sess["train_start"] + 1),
        "start_date": sess["bars"][sess["train_start"]]["date"] if ended else _mask_date(1),
        "progress": {
            "current": sess["cursor"] - sess["train_start"] + 1,
            "total": len(sess["bars"]) - sess["train_start"],
        },
        "cash": round(sess["cash"], 2),
        "market_value": market_value,
        "equity": equity,
        "return_pct": round((equity / INITIAL_CAPITAL - 1) * 100, 2),
        "float_pnl_pct": float_pnl_pct,
        "position": pos_out,
        "trades": trades_out,
        "lines": sess.get("lines", []),
        "can_buy": not ended and _can_buy(sess),
        "can_sell": bool(pos) and not ended and sess["cursor"] > pos["buy_index"],
        "can_step": not ended and sess["cursor"] < len(sess["bars"]) - 1,
    }


def _load_records(user: str) -> list[dict]:
    key = RECORD_KEY_PREFIX + (user or "default")
    try:
        raw = redis_mgr.client.lrange(key, 0, MAX_RECORDS - 1)
    except Exception as e:
        logger.error(f"读取盘感训练统计失败: {e}")
        return []
    records = []
    for item in raw:
        try:
            records.append(json.loads(item))
        except (json.JSONDecodeError, TypeError):
            continue
    return records


def _stats(records: list[dict]) -> dict:
    n = len(records)
    if n == 0:
        return {"total": 0, "win_count": 0, "win_rate": None, "avg_return": None,
                "avg_excess": None, "best_return": None, "worst_return": None,
                "cumulative_return": None, "avg_hold_days": None,
                "avg_trade_count": None, "records": []}

    returns = [r["return_pct"] for r in records]
    excess = [r["excess_pct"] for r in records]
    win_count = sum(1 for x in returns if x > 0)
    cumulative = 1.0
    for x in returns:
        cumulative *= (1 + x / 100)

    return {
        "total": n,
        "win_count": win_count,
        "win_rate": round(win_count / n * 100, 1),
        "avg_return": round(sum(returns) / n, 2),
        "avg_excess": round(sum(excess) / n, 2),
        "best_return": max(returns),
        "worst_return": min(returns),
        "cumulative_return": round((cumulative - 1) * 100, 2),
        "avg_hold_days": round(sum(r["hold_days"] for r in records) / n, 1),
        "avg_trade_count": round(sum(r["trade_count"] for r in records) / n, 1),
        "records": records[:50],
    }


# ─────────────────────────── HTTP 接口 ───────────────────────────

_VALID_VIEWS = {"day", "week", "month"}
_VALID_UNITS = {"day", "week"}


def _check_view(view: str) -> str:
    if view not in _VALID_VIEWS:
        raise HTTPException(status_code=400, detail=f"view 仅支持 {sorted(_VALID_VIEWS)}")
    return view


@router.post("/start")
async def start_training(user: str = "default"):
    """开始一轮训练：随机抽标的 + 随机一年区间

    抽题包含 InfluxDB 查询与（必要时）AkShare 采集的同步阻塞 IO，放线程池执行。
    """
    sess = await asyncio.to_thread(_build_session, user)
    _save(sess)
    _spawn(_warm_ready(user))
    logger.info(f"盘感训练开始: {sess['session_id']} user={sess['user']} 标的={sess['name']}")
    return success_response(
        data={"session": _state(sess), "chart": _chart(sess, "day")},
        message="训练已开始",
    )


@router.get("/{sid}/chart")
async def get_chart(sid: str, view: str = "day"):
    """按天/周/月视图取当前可见K线（不推进）"""
    _check_view(view)
    sess = _load(sid)
    return success_response(data={"chart": _chart(sess, view), "session": _state(sess)})


@router.post("/{sid}/step")
async def step(sid: str, unit: str = "day", view: str = "day"):
    """推进K线：unit=day 推进一日，unit=week 推进到下一自然周的最后交易日"""
    if unit not in _VALID_UNITS:
        raise HTTPException(status_code=400, detail="unit 仅支持 day/week")
    _check_view(view)

    sess = _load(sid)
    if sess["ended"]:
        raise HTTPException(status_code=400, detail="训练已结束")

    last = len(sess["bars"]) - 1
    cursor = sess["cursor"]
    if cursor >= last:
        raise HTTPException(status_code=400, detail="已到回放末尾")

    if unit == "day":
        cursor += 1
    else:
        def _iso(d: str) -> tuple[int, int]:
            iso = _parse_date(d).isocalendar()
            return iso[0], iso[1]

        cur_week = _iso(sess["bars"][cursor]["date"])
        nxt = cursor + 1
        while nxt <= last and _iso(sess["bars"][nxt]["date"]) == cur_week:
            nxt += 1
        if nxt > last:
            cursor = last
        else:
            week = _iso(sess["bars"][nxt]["date"])
            cursor = nxt
            while cursor + 1 <= last and _iso(sess["bars"][cursor + 1]["date"]) == week:
                cursor += 1

    sess["cursor"] = cursor
    summary = None
    if cursor >= last:
        sess["ended"] = True
        summary = _settle(sess, forced_exit=False)
        _delete(sid)
    else:
        _save(sess)

    return success_response(
        data={"session": _state(sess), "chart": _chart(sess, view), "summary": summary},
        message="已推进",
    )


@router.post("/{sid}/trade")
async def trade(sid: str, action: str, view: str = "day", ratio: float = 1.0):
    """买入/卖出（以当前可见最后一根K线收盘价成交，ratio 为仓位比例）"""
    if action not in ("buy", "sell"):
        raise HTTPException(status_code=400, detail="action 仅支持 buy/sell")
    _check_view(view)
    _check_ratio(ratio)

    sess = _load(sid)
    if sess["ended"]:
        raise HTTPException(status_code=400, detail="训练已结束")

    if action == "buy":
        _buy(sess, ratio)
    else:
        _sell(sess, ratio)

    _save(sess)
    return success_response(
        data={"session": _state(sess), "chart": _chart(sess, view)},
        message="买入成功" if action == "buy" else "卖出成功",
    )


_LINE_ANCHORS = {"hline": 1, "trend": 2, "channel": 3, "rect": 2, "fib": 2}


def _clean_lines(raw, total: int) -> list[dict]:
    """校验并规整划线（前端整体覆盖提交；锚点为训练区间序号 + 价格）"""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise HTTPException(status_code=400, detail="lines 必须是数组")
    if len(raw) > MAX_LINES:
        raise HTTPException(status_code=400, detail=f"最多保留 {MAX_LINES} 条划线")
    out: list[dict] = []
    for ln in raw:
        if not isinstance(ln, dict):
            raise HTTPException(status_code=400, detail="划线项格式错误")
        kind = ln.get("type")
        need = _LINE_ANCHORS.get(kind)
        if not need:
            raise HTTPException(status_code=400, detail=f"不支持的划线类型：{kind}")
        pts = ln.get("points")
        if not isinstance(pts, list) or len(pts) != need:
            raise HTTPException(status_code=400, detail=f"{kind} 需要 {need} 个锚点")
        clean = []
        for p in pts:
            if not isinstance(p, dict):
                raise HTTPException(status_code=400, detail="划线锚点格式错误")
            try:
                no = int(p["x"])
                price = float(p["price"])
            except (KeyError, TypeError, ValueError):
                raise HTTPException(status_code=400, detail="锚点需包含 x（序号）与 price（价格）")
            if no < 1 or no > total or price <= 0:
                raise HTTPException(status_code=400, detail="锚点超出训练区间或价格非正")
            clean.append({"x": no, "price": round(price, 3)})
        color = ln.get("color")
        out.append({
            "type": kind,
            "points": clean,
            "color": color if isinstance(color, str) and color.startswith("#") and len(color) <= 9
            else "#e6a23c",
        })
    return out


@router.post("/{sid}/lines")
async def save_lines(sid: str, payload: dict):
    """保存训练中的划线（整体覆盖）"""
    sess = _load(sid)
    if sess["ended"]:
        raise HTTPException(status_code=400, detail="训练已结束")
    sess["lines"] = _clean_lines(payload.get("lines"), len(sess["bars"]) - sess["train_start"])
    _save(sess)
    return success_response(data={"lines": sess["lines"]}, message="已保存")


@router.post("/{sid}/finish")
async def finish(sid: str):
    """主动结束训练并按当前K线收盘价平仓结算"""
    sess = _load(sid)
    if sess["ended"]:
        raise HTTPException(status_code=400, detail="训练已结束")

    sess["ended"] = True
    summary = _settle(sess, forced_exit=False)
    _delete(sid)
    return success_response(
        data={"summary": summary, "session": _state(sess)},
        message="训练结束",
    )


@router.get("/stats/{user}")
async def get_stats(user: str):
    """训练统计汇总 + 历史记录"""
    return success_response(data=_stats(_load_records(user)))


# ─────────────────────────── 复盘 ───────────────────────────

def _find_record(user: str, session_id: str) -> dict | None:
    """按会话 ID 在历史记录中定位一轮训练"""
    for r in _load_records(user):
        if r.get("session_id") == session_id:
            return r
    return None


def _replay_chart(record: dict, view: str) -> dict:
    """按历史记录重新回放训练区间K线

    会话结算后已删除，这里用记录里的标的与区间从 InfluxDB 重查（含前置预热段，
    保证 MA60/MACD 在区间首根已收敛）。因为记录不保存 cursor 轨迹，
    复盘展示的是完整训练区间，而非当时的逐步视野。
    """
    code = record.get("code")
    start_date = record.get("start_date")
    end_date = record.get("end_date")
    if not (code and start_date and end_date):
        raise HTTPException(status_code=404, detail="训练记录缺少标的或区间信息")

    # 截止到原定区间末尾，提前结束的轮次也能看到「结束后行情怎么走」；
    # 旧记录没有 window_end，退回实际结束日。
    window_end = record.get("window_end") or end_date
    # 预热段：90 个交易日约 130 自然日，预留 180 天冗余
    warm_start = _parse_date(start_date) - timedelta(days=WARMUP_BARS * 2)
    bars = influx_query.query_stock_kline(code, warm_start.isoformat(), window_end)
    bars = [b for b in bars if b["date"] <= window_end]
    if not bars:
        raise HTTPException(status_code=404, detail="该标的历史日线已不可用，无法回放")

    start_idx = next((i for i, b in enumerate(bars) if b["date"] >= start_date), None)
    if start_idx is None:
        raise HTTPException(status_code=404, detail="训练区间内无K线数据，无法回放")

    warm = max(0, start_idx - WARMUP_BARS)
    chart = _build_chart(bars[warm:], start_idx - warm, view)
    # 与训练时同一套序号（训练区间第几根），复盘的划线才能落在原来的位置
    order = {b["date"]: i + 1 for i, b in enumerate(bars[start_idx:])}
    chart["bars"] = [{**b, "no": order.get(b["date"], 1)} for b in chart["bars"]]
    return chart


@router.get("/replay/{session_id}")
async def replay(session_id: str, user: str = "default", view: str = "day"):
    """复盘一轮已结算的训练：标的、区间、买卖点与K线"""
    _check_view(view)
    record = _find_record(user, session_id)
    if not record:
        raise HTTPException(status_code=404, detail="未找到该训练记录（仅保留最近 200 条）")
    chart = await asyncio.to_thread(_replay_chart, record, view)
    return success_response(data={"record": record, "chart": chart})
