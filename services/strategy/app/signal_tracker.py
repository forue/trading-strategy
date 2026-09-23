"""策略信号效果跟踪：信号落库、收益回填、复盘统计

为什么需要落库：信号原先只写入 Redis（TTL 7 天），过期即丢，导致"信号准不准"
无法长期统计。这里把信号持久化到 PostgreSQL，并在行情到位后回填信号后
N 个交易日的真实收益。

统计口径（页面文案需与之一致）：
- horizon 为持有交易日数，取 1/3/5/10，覆盖三档策略的持仓周期
- 成交假设：信号在 T 日收盘后（15:35）生成，最早只能 T+1 开盘买入，持有到
  第 T+horizon 个交易日收盘卖出，即 entry = open(T+1)、exit = close(T+horizon)。
  不使用 T 日收盘价作买入基准，避免"收盘前已知信号"的前视偏差。
- 价格来源：收盘价取 sector_capital_flow.index_close（与策略打分口径一致），
  开盘价取 sector_kline.open（同花顺行业指数真实开盘价）。sector_capital_flow
  的 open 仅在手动采集历史数据时才有值，日常定时采集不写入，不能作为唯一来源。
- 板块价格变动 raw_return = exit / entry - 1（未调整方向、未扣成本，仅作审计）
- 方向收益 direction_return = raw_return ×（买入 +1 / 卖出 -1）：卖出信号后板块
  下跌才是策略盈利，必须取反，否则"胜率"与"命中率"会互相矛盾
- 净收益 net_return = direction_return - cost_rate，成本率取自策略配置
  （往返 = 2×(佣金+滑点) + 印花税），与回测口径一致
- 命中率 = direction_return > 0 的占比（即方向判定正确的占比）
- 行情不足以走完持有期的信号计 pending；T+1 开盘价缺失的信号计 no_quote，
  两者都不进入命中率分母，避免把"尚未出结果"当成失败
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

import psycopg2
from loguru import logger
from psycopg2.extras import execute_values

from .config import settings
from .influx_query import influx_query

# 评估窗口：覆盖三档策略的持仓周期（AGGRESSIVE/CONSERVATIVE 10 天、MODERATE 5 天）
HORIZONS: tuple[int, ...] = (1, 3, 5, 10)
DEFAULT_HORIZON = 5
DEFAULT_LOOKBACK_DAYS = 365

# 成本回退默认值：与 StrategyParams 出厂默认一致（佣金万三、印花税千一、滑点千一）
_FALLBACK_COMMISSION_RATE = 0.0003
_FALLBACK_STAMP_TAX_RATE = 0.001
_FALLBACK_SLIPPAGE_RATE = 0.001

# base_close / end_close 的语义为"入场价 / 结算价"：入场价取 T+1 开盘价，
# 结算价取第 T+horizon 个交易日收盘价（见模块头口径说明）
_CREATE_SIGNAL_OUTCOMES = """
CREATE TABLE IF NOT EXISTS signal_outcomes (
    id BIGSERIAL PRIMARY KEY,
    signal_date DATE NOT NULL,
    strategy_type VARCHAR(20) NOT NULL,
    sector_code VARCHAR(20) NOT NULL,
    direction VARCHAR(10) NOT NULL,
    horizon_days INT NOT NULL,
    end_date DATE NOT NULL,
    base_close DECIMAL(12,4) NOT NULL,
    end_close DECIMAL(12,4) NOT NULL,
    forward_return DECIMAL(10,6) NOT NULL,
    direction_return DECIMAL(10,6),
    cost_rate DECIMAL(10,6),
    net_return DECIMAL(10,6),
    is_win BOOLEAN NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(signal_date, strategy_type, sector_code, direction, horizon_days)
)
"""

# 老库补列（ensure_schema 幂等执行）
_MIGRATE_SIGNAL_OUTCOMES = """
ALTER TABLE signal_outcomes
    ADD COLUMN IF NOT EXISTS direction_return DECIMAL(10,6),
    ADD COLUMN IF NOT EXISTS cost_rate DECIMAL(10,6),
    ADD COLUMN IF NOT EXISTS net_return DECIMAL(10,6)
"""

# 旧口径数据（T 日收盘基准、未按方向取号、未扣成本）与新口径不可混用，清除后重算。
# 该表是纯派生数据，可由 trade_signals + 行情完整重建，清除无副作用。
_PURGE_LEGACY_OUTCOMES = """
DELETE FROM signal_outcomes WHERE direction_return IS NULL
"""

_CREATE_SIGNAL_OUTCOMES_INDEX = """
CREATE INDEX IF NOT EXISTS idx_signal_outcomes_perf
    ON signal_outcomes (strategy_type, horizon_days, signal_date)
"""

# 与 scripts/init-db.sql 保持一致：全新部署若未执行该脚本也能自愈
_CREATE_TRADE_SIGNALS = """
CREATE TABLE IF NOT EXISTS trade_signals (
    id BIGSERIAL PRIMARY KEY,
    signal_date DATE NOT NULL,
    strategy_type VARCHAR(20) NOT NULL,
    sector_code VARCHAR(20) NOT NULL,
    sector_name VARCHAR(50) NOT NULL,
    direction VARCHAR(10) NOT NULL,
    position_ratio DECIMAL(5,4) NOT NULL,
    score DECIMAL(10,4),
    reason TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(signal_date, strategy_type, sector_code, direction)
)
"""


def _enum_value(value: Any) -> str:
    """枚举成员转字符串

    Python 3.11 中 str(str-Enum 成员) 返回 "ClassName.MEMBER"，
    直接 str() 会把方向写成 SignalDirection.BUY，必须取 .value。
    """
    return value.value if hasattr(value, "value") else str(value)


def _connect():
    """建立 PostgreSQL 连接（调用频率低，不做连接池）"""
    return psycopg2.connect(
        host=settings.postgres_host,
        database=settings.postgres_db,
        user=settings.postgres_user,
        password=settings.postgres_password,
        connect_timeout=5,
    )


def ensure_schema() -> None:
    """幂等创建所需表（容器首次初始化才会执行 init-db.sql，老库不会自动补表）"""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(_CREATE_TRADE_SIGNALS)
            cur.execute(_CREATE_SIGNAL_OUTCOMES)
            cur.execute(_MIGRATE_SIGNAL_OUTCOMES)
            cur.execute(_PURGE_LEGACY_OUTCOMES)
            cur.execute(_CREATE_SIGNAL_OUTCOMES_INDEX)
        conn.commit()
        logger.info("信号跟踪表已就绪（trade_signals / signal_outcomes）")
    except Exception as e:
        logger.error(f"创建信号跟踪表失败: {e}")
        raise
    finally:
        conn.close()


def save_signals(strategy_type: str, signal_date: str, signals: list[dict]) -> int:
    """把信号写入 trade_signals（按业务唯一键幂等覆盖）

    Returns:
        实际写入条数
    """
    rows = []
    for s in signals:
        # 只入库属于当日信号日期的记录，避免把"历史清仓留痕"当成当日信号
        if str(s.get("signal_date", "")) != signal_date:
            continue
        code = s.get("sector_code")
        if not code:
            continue
        rows.append((
            signal_date,
            strategy_type,
            code,
            s.get("sector_name") or code,
            _enum_value(s.get("direction", "")),
            float(s.get("position_ratio") or 0.0),
            float(s.get("score") or 0.0),
            s.get("reason") or "",
        ))

    if not rows:
        return 0

    conn = _connect()
    try:
        with conn.cursor() as cur:
            execute_values(cur, """
                INSERT INTO trade_signals
                    (signal_date, strategy_type, sector_code, sector_name,
                     direction, position_ratio, score, reason)
                VALUES %s
                ON CONFLICT (signal_date, strategy_type, sector_code, direction)
                DO UPDATE SET
                    sector_name = EXCLUDED.sector_name,
                    position_ratio = EXCLUDED.position_ratio,
                    score = EXCLUDED.score,
                    reason = EXCLUDED.reason
            """, rows)
        conn.commit()
    finally:
        conn.close()
    logger.info(f"信号落库: {strategy_type} {signal_date} 共 {len(rows)} 条")
    return len(rows)


def sync_from_cache(lookback_days: int = 7) -> dict:
    """把 Redis 中仍然存活的信号补录到数据库

    信号缓存 TTL 为 7 天，所以最多只能补回最近一周的真实信号；用于
    /calculate 落库失败或历史版本未落库时的兜底。
    """
    from .main import redis_mgr  # 延迟导入，避免与 main.py 形成导入环
    from .models import StrategyType

    synced: dict[str, int] = {}
    skipped: list[str] = []
    today = datetime.now().date()
    for strategy in StrategyType:
        count = 0
        for delta in range(lookback_days + 1):
            date_str = (today - timedelta(days=delta)).strftime("%Y-%m-%d")
            raw = redis_mgr.get(f"signals:{strategy.value}:{date_str}")
            if not raw:
                continue
            try:
                signals = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                skipped.append(f"{strategy.value}:{date_str}")
                continue
            count += save_signals(strategy.value, date_str, signals)
        synced[strategy.value] = count

    logger.info(f"信号缓存补录完成: {synced}")
    return {"synced": synced, "skipped": skipped}


def _to_float(value: Any) -> float:
    """字段转 float，缺失/非法一律为 0"""
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _load_quote_series(start_date: str, end_date: str) -> dict[str, list[tuple[str, float, float]]]:
    """批量加载各板块 (日期, 开盘价, 收盘价) 序列（按日期升序）

    两个数据源分工合并，缺一不可：
    - 收盘价：取 sector_capital_flow.index_close，与策略因子/打分口径一致
    - 开盘价：取 sector_kline.open（同花顺行业指数真实开盘价）

    sector_capital_flow 的 open 只在手动触发 /collect/history 时才写入，日常定时
    采集为空；若只依赖它，绝大多数信号会因取不到 T+1 开盘价而无法结算。
    sector_kline 由 /collect/kline 采集，对该测量缺失的日期用资金流表兜底补齐。

    open 缺失的记录仍保留（收盘价仍可用于结算），只有真正作为入场价时才判为
    无行情；若因单日 open 缺失丢弃整条序列，会连带丢掉该板块其它可用信号。
    """
    daily = influx_query.query_daily_sectors(start_date, end_date) or {}
    klines = influx_query.query_all_sector_kline(start_date, end_date) or {}

    # (sector_code, 日期) -> [开盘价, 收盘价]
    merged: dict[tuple[str, str], list[float]] = {}
    for date_key, sectors in daily.items():
        day = str(date_key)[:10]
        for item in sectors or []:
            code = item.get("sector_code")
            if not code:
                continue
            close = _to_float(item.get("index_close"))
            if close <= 0:
                continue
            merged[(code, day)] = [_to_float(item.get("open")), close]

    for code, rows in klines.items():
        for row in rows:
            day = str(row.get("date"))[:10]
            if not code or not day:
                continue
            slot = merged.setdefault((code, day), [0.0, 0.0])
            kline_open = _to_float(row.get("open"))
            if kline_open > 0:
                slot[0] = kline_open
            if slot[1] <= 0:
                slot[1] = _to_float(row.get("close"))

    series: dict[str, list[tuple[str, float, float]]] = {}
    for (code, day), (open_price, close) in merged.items():
        if close > 0:
            series.setdefault(code, []).append((day, open_price, close))
    for code in series:
        series[code].sort(key=lambda row: row[0])
    return series


def _resolve_cost_rate(strategy_type: str) -> float:
    """信号往返交易成本率（买入 + 卖出），取自策略配置以与回测口径一致

    买入成本 = 佣金 + 滑点；卖出成本 = 佣金 + 印花税 + 滑点。
    复盘是收益率口径，无法套用回测里"佣金 5 元下限"的绝对金额约束，
    该下限对小额订单影响更大，此处不予考虑（页面文案已注明）。
    """
    commission = _FALLBACK_COMMISSION_RATE
    stamp_tax = _FALLBACK_STAMP_TAX_RATE
    slippage = _FALLBACK_SLIPPAGE_RATE
    try:
        from .main import DEFAULT_CONFIGS  # 延迟导入，避免与 main.py 形成导入环
        from .models import StrategyType

        cfg = DEFAULT_CONFIGS.get(StrategyType(strategy_type))
        if cfg is not None:
            commission = float(cfg.params.commission_rate)
            stamp_tax = float(cfg.params.stamp_tax_rate)
            slippage = float(cfg.params.slippage_rate)
    except Exception as e:  # 配置不可用时退回出厂默认，不阻断回填
        logger.warning(f"读取策略 {strategy_type} 成本参数失败，使用默认值: {e}")
    return 2 * (commission + slippage) + stamp_tax


def _fetch_signals(start_date: str, end_date: str) -> list[dict]:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT signal_date, strategy_type, sector_code, direction
                FROM trade_signals
                WHERE signal_date BETWEEN %s AND %s
            """, (start_date, end_date))
            return [
                {
                    "signal_date": row[0].strftime("%Y-%m-%d"),
                    "strategy_type": row[1],
                    "sector_code": row[2],
                    "direction": row[3],
                }
                for row in cur.fetchall()
            ]
    finally:
        conn.close()


def _fetch_existing_outcomes(start_date: str) -> set[tuple]:
    """已回填的评估键，避免重复计算"""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT signal_date, strategy_type, sector_code, direction, horizon_days
                FROM signal_outcomes
                WHERE signal_date >= %s
            """, (start_date,))
            return {
                (row[0].strftime("%Y-%m-%d"), row[1], row[2], row[3], int(row[4]))
                for row in cur.fetchall()
            }
    finally:
        conn.close()


def backfill_outcomes(lookback_days: int = DEFAULT_LOOKBACK_DAYS) -> dict:
    """回填信号后收益

    成交假设：T+1 开盘买入，第 T+horizon 个交易日收盘卖出（见模块头口径）。
    行情不足以走完持有期的信号保持待评估（不写库）。

    pending / no_quote 均按"信号"计数（而非信号 × horizon 的键数），
    与 /signals/performance 的 pending_count 口径保持一致。
    """
    today = datetime.now()
    end_date = today.strftime("%Y-%m-%d")
    start_date = (today - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

    signals = _fetch_signals(start_date, end_date)
    if not signals:
        return {"signals": 0, "evaluated": 0, "pending": 0, "no_quote": 0}

    existing = _fetch_existing_outcomes(start_date)
    series = _load_quote_series(start_date, end_date)
    cost_rate_cache: dict[str, float] = {}

    rows: list[tuple] = []
    pending_signals: set[tuple] = set()
    no_quote_signals: set[tuple] = set()
    for sig in signals:
        sig_key = (
            sig["signal_date"], sig["strategy_type"],
            sig["sector_code"], sig["direction"],
        )
        quotes = series.get(sig["sector_code"])
        if not quotes:
            no_quote_signals.add(sig_key)
            continue
        dates = [row[0] for row in quotes]
        if sig["signal_date"] not in dates:
            no_quote_signals.add(sig_key)
            continue
        idx = dates.index(sig["signal_date"])

        # 入场：T+1 开盘价（信号在 T 日收盘后才生成，无法以 T 日价格成交）
        entry_idx = idx + 1
        if entry_idx >= len(quotes):
            pending_signals.add(sig_key)
            continue
        _, entry_price, _ = quotes[entry_idx]
        if entry_price <= 0:
            no_quote_signals.add(sig_key)
            continue

        sign = 1.0 if sig["direction"] == "BUY" else -1.0
        cost_rate = cost_rate_cache.get(sig["strategy_type"])
        if cost_rate is None:
            cost_rate = _resolve_cost_rate(sig["strategy_type"])
            cost_rate_cache[sig["strategy_type"]] = cost_rate

        for horizon in HORIZONS:
            key = sig_key + (horizon,)
            if key in existing:
                continue
            exit_idx = idx + horizon
            if exit_idx >= len(quotes):
                # 持有期尚未走完：留到后续交易日再评估
                pending_signals.add(sig_key)
                continue
            quote_date, _, exit_price = quotes[exit_idx]
            if exit_price <= 0:
                no_quote_signals.add(sig_key)
                continue
            raw_return = exit_price / entry_price - 1
            direction_return = raw_return * sign
            net_return = direction_return - cost_rate
            rows.append((
                sig["signal_date"], sig["strategy_type"], sig["sector_code"],
                sig["direction"], horizon, quote_date,
                round(entry_price, 4), round(exit_price, 4),
                round(raw_return, 6), round(direction_return, 6),
                round(cost_rate, 6), round(net_return, 6),
                direction_return > 0,
            ))

    if rows:
        conn = _connect()
        try:
            with conn.cursor() as cur:
                execute_values(cur, """
                    INSERT INTO signal_outcomes
                        (signal_date, strategy_type, sector_code, direction,
                         horizon_days, end_date, base_close, end_close,
                         forward_return, direction_return, cost_rate,
                         net_return, is_win)
                    VALUES %s
                    ON CONFLICT (signal_date, strategy_type, sector_code, direction, horizon_days)
                    DO UPDATE SET
                        end_date = EXCLUDED.end_date,
                        base_close = EXCLUDED.base_close,
                        end_close = EXCLUDED.end_close,
                        forward_return = EXCLUDED.forward_return,
                        direction_return = EXCLUDED.direction_return,
                        cost_rate = EXCLUDED.cost_rate,
                        net_return = EXCLUDED.net_return,
                        is_win = EXCLUDED.is_win
                """, rows)
            conn.commit()
        finally:
            conn.close()

    logger.info(
        f"信号收益回填完成: 新增 {len(rows)} 条，待评估 {len(pending_signals)} 条，"
        f"无行情 {len(no_quote_signals)} 条"
    )
    return {
        "signals": len(signals),
        "evaluated": len(rows),
        "pending": len(pending_signals),
        "no_quote": len(no_quote_signals),
    }


def _rate(numerator, denominator) -> float | None:
    """比率：无样本时返回 None，避免把"没有样本"显示成 0%"""
    if not denominator:
        return None
    return round(int(numerator or 0) / int(denominator), 4)


def _round_or_none(value) -> float | None:
    return round(float(value), 6) if value is not None else None


def query_performance(
    strategy_type: str,
    horizon_days: int = DEFAULT_HORIZON,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    """汇总某策略在指定评估窗口下的收益与命中率指标

    收益一律取净收益 net_return（已按方向取号并扣除往返成本），
    同时给出方向调整后的毛收益 *_gross 供对比；命中率即方向判定正确率，
    与"平均收益为正"在口径上自洽（卖出信号后板块下跌才算命中且盈利）。
    """
    if horizon_days not in HORIZONS:
        raise ValueError(f"不支持的评估窗口: {horizon_days}，可选值 {list(HORIZONS)}")

    end = end_date or datetime.now().strftime("%Y-%m-%d")
    start = start_date or (
        datetime.now() - timedelta(days=DEFAULT_LOOKBACK_DAYS)
    ).strftime("%Y-%m-%d")

    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    COUNT(*),
                    COUNT(*) FILTER (WHERE direction_return > 0),
                    AVG(net_return),
                    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY net_return),
                    MAX(net_return),
                    MIN(net_return),
                    SUM(net_return) FILTER (WHERE net_return > 0),
                    SUM(-net_return) FILTER (WHERE net_return < 0),
                    AVG(direction_return),
                    SUM(direction_return) FILTER (WHERE direction_return > 0),
                    SUM(-direction_return) FILTER (WHERE direction_return < 0),
                    AVG(cost_rate),
                    COUNT(*) FILTER (WHERE direction = 'BUY'),
                    COUNT(*) FILTER (WHERE direction = 'BUY' AND direction_return > 0),
                    AVG(net_return) FILTER (WHERE direction = 'BUY'),
                    AVG(direction_return) FILTER (WHERE direction = 'BUY'),
                    COUNT(*) FILTER (WHERE direction = 'SELL'),
                    COUNT(*) FILTER (WHERE direction = 'SELL' AND direction_return > 0),
                    AVG(net_return) FILTER (WHERE direction = 'SELL'),
                    AVG(direction_return) FILTER (WHERE direction = 'SELL')
                FROM signal_outcomes
                WHERE strategy_type = %s AND horizon_days = %s
                  AND signal_date BETWEEN %s AND %s
            """, (strategy_type, horizon_days, start, end))
            agg = cur.fetchone()

            # 信号总数：用于说明还有多少信号尚未走完持有期
            cur.execute("""
                SELECT COUNT(*), MIN(signal_date), MAX(signal_date)
                FROM trade_signals
                WHERE strategy_type = %s AND signal_date BETWEEN %s AND %s
            """, (strategy_type, start, end))
            total, first_date, last_date = cur.fetchone()

            cur.execute("""
                SELECT to_char(signal_date, 'YYYY-MM'),
                       COUNT(*),
                       COUNT(*) FILTER (WHERE direction_return > 0),
                       AVG(net_return),
                       AVG(direction_return)
                FROM signal_outcomes
                WHERE strategy_type = %s AND horizon_days = %s
                  AND signal_date BETWEEN %s AND %s
                GROUP BY 1 ORDER BY 1
            """, (strategy_type, horizon_days, start, end))
            monthly = cur.fetchall()

            cur.execute("""
                SELECT o.sector_code,
                       MAX(s.sector_name),
                       COUNT(*),
                       COUNT(*) FILTER (WHERE o.direction_return > 0),
                       AVG(o.net_return),
                       AVG(o.direction_return)
                FROM signal_outcomes o
                LEFT JOIN trade_signals s
                  ON s.signal_date = o.signal_date
                 AND s.strategy_type = o.strategy_type
                 AND s.sector_code = o.sector_code
                 AND s.direction = o.direction
                WHERE o.strategy_type = %s AND o.horizon_days = %s
                  AND o.signal_date BETWEEN %s AND %s
                GROUP BY o.sector_code
                ORDER BY COUNT(*) DESC, o.sector_code
            """, (strategy_type, horizon_days, start, end))
            sectors = cur.fetchall()

            # 曲线横轴取结算日 end_date：收益在第 horizon 个交易日收盘才落袋，
            # 挂在信号日会让曲线提前反映尚未实现的收益
            cur.execute("""
                SELECT end_date, COUNT(*), AVG(net_return), AVG(direction_return)
                FROM signal_outcomes
                WHERE strategy_type = %s AND horizon_days = %s
                  AND signal_date BETWEEN %s AND %s
                GROUP BY 1 ORDER BY 1
            """, (strategy_type, horizon_days, start, end))
            daily = cur.fetchall()
    finally:
        conn.close()

    evaluated = int(agg[0] or 0)
    net_profit = float(agg[6] or 0.0)
    net_loss = float(agg[7] or 0.0)
    gross_profit = float(agg[9] or 0.0)
    gross_loss = float(agg[10] or 0.0)

    # 累计曲线口径：按结算日取当日已结算信号的等权平均净收益后累加（算术累计）。
    # 不用复利连乘：同一时刻存在 horizon 个头寸，按每日满仓复利会放大波动，
    # 该曲线只用于观察信号质量的时序趋势，不代表可直接复现的资金曲线。
    cumulative = 0.0
    equity_curve = []
    for day, count, avg_net, avg_gross in daily:
        cumulative += float(avg_net or 0.0)
        equity_curve.append({
            "date": day.strftime("%Y-%m-%d"),
            "evaluated": int(count or 0),
            "avg_return": round(float(avg_net or 0.0), 6),
            "avg_return_gross": round(float(avg_gross or 0.0), 6),
            "cum_return": round(cumulative, 6),
        })

    signal_count = int(total or 0)
    # 成本率取实际回填结果；无已评估样本时回退到当前策略配置
    cost_rate = (
        float(agg[11]) if agg[11] is not None else _resolve_cost_rate(strategy_type)
    )
    return {
        "strategy_type": strategy_type,
        "horizon_days": horizon_days,
        "start_date": start,
        "end_date": end,
        "signal_count": signal_count,
        "evaluated_count": evaluated,
        "pending_count": max(signal_count - evaluated, 0),
        "cost_rate": round(cost_rate, 6),
        "hit_count": int(agg[1] or 0),
        "hit_rate": _rate(agg[1], evaluated),
        "avg_return": _round_or_none(agg[2]),
        "avg_return_gross": _round_or_none(agg[8]),
        "median_return": _round_or_none(agg[3]),
        "best_return": _round_or_none(agg[4]),
        "worst_return": _round_or_none(agg[5]),
        "profit_factor": round(net_profit / net_loss, 4) if net_loss > 0 else None,
        "profit_factor_gross": (
            round(gross_profit / gross_loss, 4) if gross_loss > 0 else None
        ),
        "buy": {
            "count": int(agg[12] or 0),
            "hit_count": int(agg[13] or 0),
            "hit_rate": _rate(agg[13], agg[12]),
            "avg_return": _round_or_none(agg[14]),
            "avg_return_gross": _round_or_none(agg[15]),
        },
        "sell": {
            "count": int(agg[16] or 0),
            "hit_count": int(agg[17] or 0),
            "hit_rate": _rate(agg[17], agg[16]),
            "avg_return": _round_or_none(agg[18]),
            "avg_return_gross": _round_or_none(agg[19]),
        },
        "monthly": [
            {
                "month": month,
                "evaluated": int(count or 0),
                "hit_count": int(hits or 0),
                "hit_rate": _rate(hits, count),
                "avg_return": _round_or_none(avg_net),
                "avg_return_gross": _round_or_none(avg_gross),
            }
            for month, count, hits, avg_net, avg_gross in monthly
        ],
        "sectors": [
            {
                "sector_code": code,
                "sector_name": name or code,
                "evaluated": int(count or 0),
                "hit_count": int(hits or 0),
                "hit_rate": _rate(hits, count),
                "avg_return": _round_or_none(avg_net),
                "avg_return_gross": _round_or_none(avg_gross),
            }
            for code, name, count, hits, avg_net, avg_gross in sectors
        ],
        "equity_curve": equity_curve,
        "first_signal_date": first_date.strftime("%Y-%m-%d") if first_date else None,
        "last_signal_date": last_date.strftime("%Y-%m-%d") if last_date else None,
    }
