"""策略引擎服务 - FastAPI主应用"""
import sys
import os
import calendar
import json
import numpy as np
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException
from loguru import logger

# 添加共享库路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# 常量定义
TRADING_DAYS_PER_YEAR = 252  # 年化交易日天数

from .config import settings
from .models import (
    StrategyType, StrategyParams, StrategyConfig,
    TradeSignal, BacktestRequest, BacktestResult,
)
from .scoring import scoring_model
from .influx_query import influx_query
from shared import RabbitMQManager, RedisManager

# 配置日志
logger.remove()
logger.add(sys.stderr, level=settings.log_level)

# 初始化连接管理器
rmq = RabbitMQManager()
redis_mgr = RedisManager()


def _calc_trade_cost(amount: float, commission_rate: float, stamp_tax_rate: float, slippage_rate: float, is_sell: bool = False) -> dict:
    commission = max(amount * commission_rate, 5.0)
    stamp_tax = amount * stamp_tax_rate if is_sell else 0.0
    slippage = amount * slippage_rate
    return {
        "commission": commission,
        "stamp_tax": stamp_tax,
        "slippage": slippage,
        "total": commission + stamp_tax + slippage,
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    rmq.connect(
        host=settings.rabbitmq_host,
        port=settings.rabbitmq_port,
        user=settings.rabbitmq_user,
        password=settings.rabbitmq_password,
    )
    redis_mgr.connect(
        host=settings.redis_host,
        port=settings.redis_port,
        password=settings.redis_password,
        db=settings.redis_db,
    )
    yield
    rmq.close()
    redis_mgr.close()


app = FastAPI(title="策略引擎服务", version="1.1.0", lifespan=lifespan)

# 默认策略配置 - 均衡参数
DEFAULT_CONFIGS = {
    StrategyType.AGGRESSIVE: StrategyConfig(
        id=1, strategy_type=StrategyType.AGGRESSIVE, name="激进轮动策略",
        params=StrategyParams(top_n=2, max_position=1.0, hold_days=3, capital_pct=0.5, stop_loss=0.12, commission_rate=0.0003, stamp_tax_rate=0.001, slippage_rate=0.001, min_score_threshold=2.0, score_gap_threshold=1.0, cooldown_days=2, keep_overlap=True, allow_empty=True, min_score_keep=3.0),
    ),
    StrategyType.MODERATE: StrategyConfig(
        id=2, strategy_type=StrategyType.MODERATE, name="稳健轮动策略",
        params=StrategyParams(top_n=3, max_position=0.5, hold_days=5, capital_pct=0.3, stop_loss=0.10, commission_rate=0.0003, stamp_tax_rate=0.001, slippage_rate=0.001, min_score_threshold=2.0, score_gap_threshold=1.0, cooldown_days=2, keep_overlap=True, allow_empty=True, min_score_keep=3.0),
    ),
    StrategyType.CONSERVATIVE: StrategyConfig(
        id=3, strategy_type=StrategyType.CONSERVATIVE, name="保守轮动策略",
        params=StrategyParams(top_n=5, max_position=0.3, hold_days=10, capital_pct=0.2, stop_loss=0.08, valuation_pct_max=50, commission_rate=0.0003, stamp_tax_rate=0.001, slippage_rate=0.001, min_score_threshold=2.0, score_gap_threshold=1.0, cooldown_days=3, keep_overlap=True, allow_empty=True, min_score_keep=3.0),
    ),
}


def publish_message(routing_key: str, message: dict):
    """发送消息到RabbitMQ（使用共享连接管理器）"""
    rmq.publish(routing_key, message)


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "strategy", "timestamp": datetime.now().isoformat()}


@app.get("/trade-day/check")
async def check_trade_day(date: str = None):
    """检查指定日期是否为交易日"""
    try:
        target_date = date or datetime.now().strftime("%Y-%m-%d")
        is_trade = _is_trade_day(target_date)
        return {
            "code": 200,
            "data": {
                "date": target_date,
                "is_trade_day": is_trade,
                "message": f"{target_date} {'是' if is_trade else '不是'}交易日",
            },
        }
    except Exception as e:
        logger.error(f"交易日检查失败: {e}")
        raise HTTPException(status_code=500, detail=f"交易日检查失败: {e}")


@app.post("/collect")
async def collect_data():
    """触发数据采集：从数据采集服务获取最新板块数据并写入InfluxDB"""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post("http://data-collector:8003/collect/sector-flow")
            if resp.status_code == 200:
                result = resp.json()
                logger.info(f"数据采集完成: {result}")
                return {"code": 200, "message": "数据采集完成", "data": result}
            else:
                logger.error(f"数据采集失败: {resp.status_code}")
                return {"code": 500, "message": "数据采集失败"}
    except Exception as e:
        logger.error(f"数据采集异常: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# 交易日历缓存
_trade_dates_cache = {"dates": set(), "update_time": None}
TRADE_DATES_CACHE_TTL = 86400  # 24小时


def _is_trade_day(date_str: str) -> bool:
    """检查是否为交易日（带缓存）"""
    now = datetime.now()
    # 检查缓存是否过期
    if _trade_dates_cache["update_time"] is None or \
       (now - _trade_dates_cache["update_time"]).total_seconds() > TRADE_DATES_CACHE_TTL:
        try:
            import akshare as ak
            df = ak.tool_trade_date_hist_sina()
            if df is not None and not df.empty:
                dates = df.iloc[:, 0].tolist()
                _trade_dates_cache["dates"] = {d.strftime("%Y%m%d") if hasattr(d, "strftime") else str(d) for d in dates}
                _trade_dates_cache["update_time"] = now
        except Exception:
            pass

    # 使用缓存
    if _trade_dates_cache["dates"]:
        return date_str.replace("-", "") in _trade_dates_cache["dates"]

    # 回退：简单跳过周末
    try:
        d = datetime.strptime(date_str.replace("-", ""), "%Y%m%d")
        return d.weekday() < 5
    except ValueError:
        return False


@app.post("/calculate")
async def calculate_signals(strategy_type: StrategyType, signal_date: str = None):
    """触发策略计算，生成买卖信号。非交易日不生成信号。"""
    try:
        effective_date = signal_date or datetime.now().strftime("%Y-%m-%d")

        # 非交易日检查：不生成信号
        if not _is_trade_day(effective_date):
            logger.info(f"{effective_date} 非交易日，跳过策略计算")
            return {"code": 200, "message": f"{effective_date} 非交易日，不生成信号", "data": []}

        config = DEFAULT_CONFIGS.get(strategy_type)
        if not config:
            raise HTTPException(status_code=400, detail=f"未知策略类型: {strategy_type}")

        # 尝试从Redis获取最新板块数据
        sector_data = []
        cached = redis_mgr.get("sector_capital_flow:latest")
        if cached:
            sector_data = json.loads(cached)
            logger.info(f"从Redis获取到 {len(sector_data)} 条板块数据")
        else:
            # 如果Redis中没有数据，从InfluxDB读取最新数据
            logger.info("Redis中没有板块数据，从InfluxDB读取")
            try:
                end_date = effective_date
                start_date = (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=3)).strftime("%Y-%m-%d")
                daily_data = influx_query.query_daily_sectors(start_date, end_date)

                if daily_data and len(daily_data) > 0:
                    sorted_dates = sorted(daily_data.keys())
                    latest_date = sorted_dates[-1]
                    sector_data = daily_data[latest_date]
                    logger.info(f"从InfluxDB获取到 {len(sector_data)} 条板块数据（日期: {latest_date}）")

                    redis_mgr.setex(
                        "sector_capital_flow:latest", 3600,
                        json.dumps(sector_data, ensure_ascii=False),
                    )
                else:
                    logger.warning(f"InfluxDB中没有找到板块数据，查询日期范围: {start_date} 到 {end_date}")
                    earlier_start_date = (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=30)).strftime("%Y-%m-%d")
                    earlier_data = influx_query.query_daily_sectors(earlier_start_date, end_date)
                    if earlier_data and len(earlier_data) > 0:
                        sorted_dates = sorted(earlier_data.keys())
                        latest_date = sorted_dates[-1]
                        sector_data = earlier_data[latest_date]
                        logger.info(f"从更早范围获取到 {len(sector_data)} 条板块数据（日期: {latest_date}）")
                        redis_mgr.setex(
                            "sector_capital_flow:latest", 3600,
                            json.dumps(sector_data, ensure_ascii=False),
                        )
                    else:
                        logger.error("InfluxDB中完全找不到板块数据")
            except Exception as e:
                logger.error(f"从InfluxDB读取数据失败: {e}")

        # 从Redis读取当前持仓
        current_positions = {}
        try:
            positions_raw = redis_mgr.get(f"positions:{strategy_type.value}")
            if positions_raw:
                current_positions = json.loads(positions_raw)
                logger.info(f"读取到当前持仓: {len(current_positions)}个板块")
        except Exception as e:
            logger.warning(f"读取持仓失败: {e}")

        signals = scoring_model.calculate_daily_signals(
            sector_data=sector_data,
            strategy_type=strategy_type,
            params=config.params,
            signal_date=signal_date,
            current_positions=current_positions,
        )

        # 填充 id 和 created_at
        now = datetime.now().isoformat()
        for idx, s in enumerate(signals, 1):
            s.id = idx
            s.created_at = now

        # 缓存信号到Redis
        signal_dicts = [s.model_dump() for s in signals]

        # 更新持仓到Redis（根据买卖信号）
        new_positions = {}
        for s in signals:
            if s.direction.value == "BUY":
                new_positions[s.sector_code] = s.position_ratio
        if new_positions or current_positions:
            sell_codes = [s.sector_code for s in signals if s.direction.value == "SELL"]
            for code in sell_codes:
                new_positions.pop(code, None)
            redis_mgr.setex(
                f"positions:{strategy_type.value}", 86400 * 7,
                json.dumps(new_positions, ensure_ascii=False),
            )
            logger.info(f"更新持仓到Redis: {len(new_positions)}个板块")

        redis_mgr.setex(
            f"signals:{strategy_type.value}:{signal_date or datetime.now().strftime('%Y-%m-%d')}",
            86400, json.dumps(signal_dicts, ensure_ascii=False),
        )

        # 通知信号服务
        publish_message("signal.generated", {
            "event": "signals_generated",
            "strategy_type": strategy_type.value,
            "signal_date": signal_date or datetime.now().strftime("%Y-%m-%d"),
            "count": len(signals),
            "signals": signal_dicts,
            "timestamp": datetime.now().isoformat(),
        })

        return {"code": 200, "message": "策略计算完成", "data": signal_dicts}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"策略计算失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _load_configs_from_redis():
    """从Redis加载策略配置，覆盖内存默认值"""
    try:
        raw = redis_mgr.get("strategy_configs")
        if raw:
            saved = json.loads(raw)
            for st in DEFAULT_CONFIGS:
                if st.value in saved:
                    saved_cfg = saved[st.value]
                    cfg = DEFAULT_CONFIGS[st]
                    cfg.name = saved_cfg.get("name", cfg.name)
                    cfg.is_active = saved_cfg.get("is_active", cfg.is_active)
                    if "params" in saved_cfg:
                        cfg.params = StrategyParams(**saved_cfg["params"])
            logger.info("从Redis加载策略配置成功")
    except Exception as e:
        logger.warning(f"从Redis加载策略配置失败，使用默认值: {e}")


def _save_configs_to_redis():
    """将当前策略配置保存到Redis"""
    try:
        data = {}
        for st, cfg in DEFAULT_CONFIGS.items():
            data[st.value] = {
                "name": cfg.name,
                "is_active": cfg.is_active,
                "params": cfg.params.model_dump(),
            }
        redis_mgr.set("strategy_configs", json.dumps(data, ensure_ascii=False))
        logger.info("策略配置已保存到Redis")
    except Exception as e:
        logger.error(f"保存策略配置到Redis失败: {e}")


# 启动时从Redis恢复配置
_load_configs_from_redis()


@app.get("/configs")
async def get_configs():
    """获取所有策略配置"""
    configs = []
    for cfg in DEFAULT_CONFIGS.values():
        c = cfg.model_dump()
        c["params"] = cfg.params.model_dump()
        configs.append(c)
    return {"code": 200, "data": configs}


@app.put("/configs/{config_id}")
async def update_config(config_id: int, config: StrategyConfig):
    """更新策略配置"""
    for st, cfg in DEFAULT_CONFIGS.items():
        if cfg.id == config_id:
            cfg.params = config.params
            cfg.name = config.name
            cfg.is_active = config.is_active
            _save_configs_to_redis()
            return {"code": 200, "message": "配置更新成功", "data": cfg.model_dump()}
    raise HTTPException(status_code=404, detail="配置不存在")


@app.get("/signals/today")
async def get_today_signals(strategy_type: StrategyType):
    """获取今日信号"""
    today = datetime.now().strftime("%Y-%m-%d")
    cached = redis_mgr.get(f"signals:{strategy_type.value}:{today}")
    if cached:
        return {"code": 200, "data": json.loads(cached)}
    return {"code": 200, "data": []}


@app.get("/signals/calendar")
async def get_signal_calendar(strategy_type: StrategyType, month: str = None):
    """获取信号日历数据"""
    try:
        if month is None:
            month = datetime.now().strftime("%Y-%m")

        year, mon = int(month[:4]), int(month[5:7])
        last_day = calendar.monthrange(year, mon)[1]

        pipe = redis_mgr.pipeline()
        cache_keys = []
        for day in range(1, last_day + 1):
            date_str = f"{month}-{day:02d}"
            cache_key = f"signals:{strategy_type.value}:{date_str}"
            cache_keys.append(date_str)
            pipe.get(cache_key)

        results = []
        for date_str, cached in zip(cache_keys, pipe.execute()):
            if cached:
                signals = json.loads(cached)
                for sig in signals:
                    sig["signal_date"] = date_str
                results.extend(signals)

        return {"code": 200, "data": results}
    except Exception as e:
        logger.error(f"获取信号日历失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/backtest")
async def run_backtest(request: BacktestRequest):
    """运行策略回测 - 基于真实历史数据逐日回放"""
    try:
        config = DEFAULT_CONFIGS.get(request.strategy_type)
        if not config:
            raise HTTPException(status_code=400, detail="未知策略类型")
        params = request.params if request.params else config.params

        daily_data = influx_query.query_daily_sectors(request.start_date, request.end_date)
        if not daily_data:
            raise HTTPException(status_code=404, detail="没有可用的历史数据")

        sorted_dates = sorted(daily_data.keys())
        trading_days = len(sorted_dates)
        logger.info(f"回测 {request.strategy_type.value}: {trading_days} 个交易日, {sorted_dates[0]} ~ {sorted_dates[-1]}")

        result_data = _run_backtest_core(
            daily_data, sorted_dates, request.strategy_type, params, request.initial_capital, return_full=True
        )

        bt_id = f"bt_{request.strategy_type.value}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        result_data["id"] = bt_id
        result_data["created_at"] = datetime.now().isoformat()

        # 保存回测结果到Redis
        redis_mgr.setex(f"backtest:{bt_id}", 7 * 86400, json.dumps(result_data, ensure_ascii=False))

        # 保存到回测历史列表
        history_key = f"backtest_history:{request.strategy_type.value}"
        history_entry = {
            "id": bt_id,
            "strategy_type": request.strategy_type.value,
            "start_date": request.start_date,
            "end_date": request.end_date,
            "initial_capital": request.initial_capital,
            "total_return": result_data["total_return"],
            "annual_return": result_data["annual_return"],
            "max_drawdown": result_data["max_drawdown"],
            "sharpe_ratio": result_data.get("sharpe_ratio", 0),
            "params": params.model_dump(),
            "created_at": result_data["created_at"],
            "trading_days": trading_days,
        }
        try:
            history_raw = redis_mgr.get(history_key)
            history = json.loads(history_raw) if history_raw else []
        except Exception:
            history = []
        history.insert(0, history_entry)
        history = history[:20]
        redis_mgr.setex(history_key, 30 * 86400, json.dumps(history, ensure_ascii=False))

        return {"code": 200, "data": result_data}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"回测失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _run_backtest_core(daily_data, sorted_dates, strategy_type, params, initial_capital, return_full=False):
    """回测核心逻辑（统一入口，消除重复代码）"""
    if not sorted_dates or initial_capital <= 0:
        return _empty_backtest_result(strategy_type, initial_capital, return_full)

    capital = initial_capital
    peak_capital = capital
    position_hold_counter = 0
    current_positions = {}
    stop_loss_triggered = False
    stop_loss_cooldown = 0
    rebalance_cooldown = 0
    nav_curve = []
    daily_returns = []
    benchmark_returns = []
    daily_signals_out = []
    total_commission = 0.0
    total_stamp_tax = 0.0
    total_slippage_cost = 0.0
    trade_count_actual = 0

    for i, date in enumerate(sorted_dates):
        sector_data = daily_data.get(date, [])
        if not sector_data:
            daily_returns.append(0.0)
            benchmark_returns.append(0.0)
            continue

        sector_change_map = {s["sector_code"]: s.get("index_change_pct", 0) / 100 for s in sector_data}

        # Step 1: 计算当日收益
        strategy_daily_return = 0.0
        if stop_loss_triggered:
            strategy_daily_return = 0.0
        elif current_positions:
            for sector_code, weight in current_positions.items():
                strategy_daily_return += weight * sector_change_map.get(sector_code, 0)

        all_changes = [s.get("index_change_pct", 0) / 100 for s in sector_data]
        benchmark_return = float(np.mean(all_changes)) if all_changes else 0.0

        capital *= (1 + strategy_daily_return)
        daily_returns.append(strategy_daily_return)
        benchmark_returns.append(benchmark_return)

        if capital > peak_capital:
            peak_capital = capital

        # Step 2: 止损检查
        if params.stop_loss and not stop_loss_triggered and peak_capital > 0 and current_positions:
            drawdown_from_peak = (peak_capital - capital) / peak_capital
            if drawdown_from_peak >= params.stop_loss:
                sell_trade_cost = 0.0
                for sector_code, weight in current_positions.items():
                    sell_amount = capital * weight
                    cost = _calc_trade_cost(sell_amount, params.commission_rate, params.stamp_tax_rate, params.slippage_rate, is_sell=True)
                    sell_trade_cost += cost["total"]
                    total_commission += cost["commission"]
                    total_stamp_tax += cost["stamp_tax"]
                    total_slippage_cost += cost["slippage"]
                    trade_count_actual += 1
                capital -= sell_trade_cost
                stop_loss_triggered = True
                stop_loss_cooldown = params.hold_days
                position_hold_counter = 0
                current_positions = {}

        # Step 3: 持仓天数递减
        if current_positions and position_hold_counter > 0:
            position_hold_counter -= 1

        # Step 4: 更新冷静期
        if stop_loss_cooldown > 0:
            stop_loss_cooldown -= 1
            # 冷静期结束后自动重置止损状态，允许重新建仓
            if stop_loss_cooldown <= 0:
                stop_loss_triggered = False

        # Step 5: 更新调仓冷却期
        if rebalance_cooldown > 0:
            rebalance_cooldown -= 1

        # Step 6: 检查是否需要调仓
        day_signals = []
        if not stop_loss_triggered and position_hold_counter <= 0 and stop_loss_cooldown <= 0 and rebalance_cooldown <= 0:
            signals = scoring_model.calculate_daily_signals(
                sector_data=sector_data,
                strategy_type=strategy_type,
                params=params,
                signal_date=date,
                current_positions=current_positions,
            )

            new_positions = {}
            buy_signals = [s for s in signals if s.direction.value == "BUY"]
            if buy_signals:
                total_weight = min(params.max_position * params.capital_pct, 1.0)
                per_weight = total_weight / len(buy_signals)
                for sig in buy_signals:
                    new_positions[sig.sector_code] = per_weight

            for sig in signals:
                day_signals.append({
                    "sector_code": sig.sector_code,
                    "sector_name": sig.sector_name,
                    "direction": sig.direction.value,
                    "score": round(sig.score, 2),
                    "reason": sig.reason,
                })

            # 执行调仓（有新买入 OR 有卖出信号需要执行）
            sell_codes = [s.sector_code for s in signals if s.direction.value == "SELL"]
            if new_positions or sell_codes:
                # 卖出旧持仓
                sell_trade_cost = 0.0
                for sector_code, weight in current_positions.items():
                    if sector_code not in new_positions:
                        sell_amount = capital * weight
                        cost = _calc_trade_cost(sell_amount, params.commission_rate, params.stamp_tax_rate, params.slippage_rate, is_sell=True)
                        sell_trade_cost += cost["total"]
                        total_commission += cost["commission"]
                        total_stamp_tax += cost["stamp_tax"]
                        total_slippage_cost += cost["slippage"]
                        trade_count_actual += 1

                # 买入新持仓
                buy_trade_cost = 0.0
                for sector_code, weight in new_positions.items():
                    buy_amount = capital * weight
                    cost = _calc_trade_cost(buy_amount, params.commission_rate, params.stamp_tax_rate, params.slippage_rate, is_sell=False)
                    buy_trade_cost += cost["total"]
                    total_commission += cost["commission"]
                    total_slippage_cost += cost["slippage"]
                    trade_count_actual += 1

                capital -= (sell_trade_cost + buy_trade_cost)
                if new_positions:
                    current_positions = new_positions
                    position_hold_counter = params.hold_days
                    stop_loss_triggered = False
                    rebalance_cooldown = params.cooldown_days if params.cooldown_days else 2
                else:
                    current_positions = {}

        # 记录每日信号
        daily_signals_out.append({
            "date": date,
            "signals": day_signals,
            "strategy_return": round(strategy_daily_return * 100, 4),
            "benchmark_return": round(benchmark_return * 100, 4),
            "positions": {k: round(v, 4) for k, v in current_positions.items()} if not stop_loss_triggered else {},
        })

        # Step 7: 记录净值曲线
        step = max(1, len(sorted_dates) // 100)
        if i % step == 0 or i == len(sorted_dates) - 1:
            benchmark_nav = initial_capital * np.prod([1 + r for r in benchmark_returns[:i + 1]])
            nav_curve.append({
                "date": date,
                "nav": round(capital, 2),
                "benchmark": round(float(benchmark_nav), 2),
                "stop_loss": stop_loss_triggered,
            })

    # 计算回测指标
    if initial_capital <= 0:
        return _empty_backtest_result(strategy_type, initial_capital, return_full)

    total_return = (capital / initial_capital) - 1
    trading_years = max(len(sorted_dates) / TRADING_DAYS_PER_YEAR, 0.01)
    annual_return = (1 + total_return) ** (1 / trading_years) - 1 if total_return > -1 else -1.0

    max_drawdown = 0.0
    if nav_curve:
        nav_array = np.array([p["nav"] for p in nav_curve])
        peak = np.maximum.accumulate(nav_array)
        drawdown = (nav_array - peak) / np.where(peak > 0, peak, 1)
        max_drawdown = abs(drawdown.min()) if len(drawdown) > 0 else 0

    sharpe = 0.0
    if daily_returns:
        daily_arr = np.array(daily_returns)
        std = np.std(daily_arr)
        if std > 0:
            sharpe = (np.mean(daily_arr) * TRADING_DAYS_PER_YEAR) / (std * np.sqrt(TRADING_DAYS_PER_YEAR))

    win_rate = float(np.mean(np.array(daily_returns) > 0)) if daily_returns else 0

    # 统计买入/卖出信号数量
    buy_count = 0
    sell_count = 0
    for day in daily_signals_out:
        for sig in day.get("signals", []):
            if sig.get("direction") == "BUY":
                buy_count += 1
            elif sig.get("direction") == "SELL":
                sell_count += 1

    result = {
        "strategy_type": strategy_type.value,
        "start_date": sorted_dates[0] if sorted_dates else "",
        "end_date": sorted_dates[-1] if sorted_dates else "",
        "initial_capital": initial_capital,
        "final_capital": round(capital, 2),
        "total_return": round(float(total_return), 4),
        "annual_return": round(float(annual_return), 4),
        "max_drawdown": round(float(max_drawdown), 4),
        "sharpe_ratio": round(float(sharpe), 2),
        "win_rate": round(float(win_rate), 4),
        "trading_days": len(sorted_dates),
        "trade_count": max(1, trade_count_actual) if trade_count_actual > 0 else max(1, len(sorted_dates) // max(params.hold_days, 1)),
        "buy_count": buy_count,
        "sell_count": sell_count,
        "total_commission": round(total_commission, 2),
        "total_stamp_tax": round(total_stamp_tax, 2),
        "total_slippage_cost": round(total_slippage_cost, 2),
        "total_trade_cost": round(total_commission + total_stamp_tax + total_slippage_cost, 2),
        "trade_count_actual": trade_count_actual,
        "params": {
            "top_n": params.top_n,
            "max_position": params.max_position,
            "hold_days": params.hold_days,
            "stop_loss": params.stop_loss,
            "capital_pct": params.capital_pct,
            "min_score_threshold": params.min_score_threshold,
            "score_gap_threshold": params.score_gap_threshold,
            "cooldown_days": params.cooldown_days,
        },
    }

    if return_full:
        result["nav_curve"] = nav_curve
        result["daily_signals"] = daily_signals_out

    return result


def _empty_backtest_result(strategy_type, initial_capital, return_full):
    """返回空的回测结果"""
    result = {
        "strategy_type": strategy_type.value if hasattr(strategy_type, "value") else str(strategy_type),
        "start_date": "",
        "end_date": "",
        "initial_capital": initial_capital,
        "final_capital": initial_capital,
        "total_return": 0.0,
        "annual_return": 0.0,
        "max_drawdown": 0.0,
        "sharpe_ratio": 0.0,
        "win_rate": 0.0,
        "trading_days": 0,
        "trade_count": 0,
        "buy_count": 0,
        "sell_count": 0,
        "total_commission": 0.0,
        "total_stamp_tax": 0.0,
        "total_slippage_cost": 0.0,
        "total_trade_cost": 0.0,
        "trade_count_actual": 0,
        "params": {},
    }
    if return_full:
        result["nav_curve"] = []
        result["daily_signals"] = []
    return result


@app.get("/backtest/history")
async def get_backtest_history(strategy_type: StrategyType = None):
    """获取回测历史记录"""
    try:
        results = []
        if strategy_type:
            keys = [f"backtest_history:{strategy_type.value}"]
        else:
            keys = [f"backtest_history:{st.value}" for st in StrategyType]

        for key in keys:
            raw = redis_mgr.get(key)
            if raw:
                results.extend(json.loads(raw))

        results.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return {"code": 200, "data": results}
    except Exception as e:
        logger.error(f"获取回测历史失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/backtest/{bt_id}")
async def get_backtest_detail(bt_id: str):
    """获取回测详情"""
    raw = redis_mgr.get(f"backtest:{bt_id}")
    if raw:
        return {"code": 200, "data": json.loads(raw)}
    raise HTTPException(status_code=404, detail="回测记录不存在")


@app.get("/data/availability")
async def get_data_availability():
    """查询InfluxDB中历史数据的可用日期范围"""
    try:
        min_date, max_date = influx_query.get_available_date_range()
        return {
            "code": 200,
            "data": {
                "has_data": bool(min_date and max_date),
                "min_date": min_date,
                "max_date": max_date,
            },
        }
    except Exception as e:
        logger.error(f"查询数据可用范围失败: {e}")
        return {"code": 200, "data": {"has_data": False, "min_date": "", "max_date": ""}}


@app.get("/cache/stats")
async def get_cache_stats():
    """获取缓存统计信息"""
    try:
        info = redis_mgr.info("memory")
        keyspace = redis_mgr.info("keyspace")
        db_idx = settings.redis_db
        db_info = keyspace.get(f"db{db_idx}", {})
        total_keys = db_info.get("keys", 0) if isinstance(db_info, dict) else 0

        categories = {}
        patterns = [
            ("backtest_result", "backtest:*"),
            ("backtest_history", "backtest_history:*"),
            ("signals", "signals:*"),
            ("sector_data", "sector_capital_flow:*"),
            ("system_settings", "settings:*"),
        ]
        for name, pattern in patterns:
            count = len(list(redis_mgr.scan_iter(match=pattern)))
            if count > 0:
                categories[name] = count

        return {
            "code": 200,
            "data": {
                "total_keys": total_keys,
                "used_memory_human": info.get("used_memory_human", "N/A"),
                "peak_memory_human": info.get("used_memory_peak_human", "N/A"),
                "categories": categories,
                "db_index": db_idx,
            },
        }
    except Exception as e:
        logger.error(f"获取缓存统计失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/cache/clear")
async def clear_all_cache():
    """清空当前数据库的所有缓存"""
    try:
        redis_mgr.flushdb()
        logger.info("缓存已全部清空")
        return {"code": 200, "message": "缓存已全部清空"}
    except Exception as e:
        logger.error(f"清空缓存失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/cache/expired")
async def clear_expired_cache():
    """清除已过期的缓存key"""
    try:
        cleared = 0
        for key in redis_mgr.scan_iter(match="*"):
            ttl = redis_mgr.ttl(key)
            if ttl == -1:
                redis_mgr.expire(key, 7 * 86400)
                cleared += 1
        return {"code": 200, "message": f"已为 {cleared} 个无过期时间的key设置7天TTL"}
    except Exception as e:
        logger.error(f"清理过期缓存失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/database/status")
async def get_database_status():
    """获取数据库状态信息"""
    try:
        # PostgreSQL状态
        pg_status = "unavailable"
        try:
            import psycopg2
            conn = psycopg2.connect(
                host="postgres",
                database="rotation_db",
                user=os.environ.get("DB_USER", "admin"),
                password=os.environ.get("DB_PASSWORD", ""),
                connect_timeout=3,
            )
            conn.close()
            pg_status = "connected"
        except Exception as e:
            logger.debug(f"PostgreSQL连接检查: {e}")

        # InfluxDB状态
        influx_status = "unavailable"
        influx_detail = ""
        try:
            health = influx_query.client.health()
            raw_status = health.status if hasattr(health, "status") else "unknown"
            if raw_status == "pass":
                influx_status = "connected"
                influx_detail = health.message if hasattr(health, "message") else ""
        except Exception as e:
            logger.debug(f"InfluxDB连接检查: {e}")

        # Redis状态
        redis_status = "connected" if redis_mgr.ping() else "disconnected"
        redis_info = redis_mgr.info("server")
        redis_mem = redis_mgr.info("memory")

        # 数据量统计
        data_counts = {}
        try:
            min_date, max_date = influx_query.get_available_date_range()
            data_counts["influx_days"] = 1 if min_date else 0
            data_counts["date_range"] = f"{min_date} ~ {max_date}" if min_date else "无数据"
        except Exception:
            data_counts["influx_days"] = 0
            data_counts["date_range"] = "查询失败"

        return {
            "code": 200,
            "data": {
                "postgresql": {"status": pg_status},
                "influxdb": {
                    "status": influx_status,
                    "detail": influx_detail,
                    "url": settings.influxdb_url,
                    "org": settings.influxdb_org,
                    "bucket": settings.influxdb_bucket,
                    "data_counts": data_counts,
                },
                "redis": {
                    "status": redis_status,
                    "version": redis_info.get("redis_version", "unknown"),
                    "used_memory": redis_mem.get("used_memory_human", "N/A"),
                    "connected_clients": redis_mem.get("connected_clients", 0),
                    "uptime_days": redis_info.get("uptime_in_days", 0),
                },
            },
        }
    except Exception as e:
        logger.error(f"获取数据库状态失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/settings")
async def get_system_settings():
    """获取系统设置"""
    try:
        settings_map = {}
        for key in redis_mgr.scan_iter(match="settings:*"):
            val = redis_mgr.get(key)
            short_key = key.replace("settings:", "")
            try:
                parsed = json.loads(val)
                settings_map[short_key] = parsed
            except (json.JSONDecodeError, TypeError):
                # 兼容旧格式：str(True) -> "True"
                if val == "True":
                    settings_map[short_key] = True
                elif val == "False":
                    settings_map[short_key] = False
                else:
                    try:
                        settings_map[short_key] = int(val)
                    except (ValueError, TypeError):
                        settings_map[short_key] = val

        defaults = {
            "ws_push_enabled": True,
            "ws_push_strategy_types": ["AGGRESSIVE", "MODERATE", "CONSERVATIVE"],
            "data_source": "akshare_ths",
            "data_source_config": {
                "name": "AkShare (同花顺)",
                "is_mock": False,
                "description": "AkShare同花顺数据源，提供真实K线和行业汇总数据",
            },
            "cache_ttl_days": 7,
            "scheduler_enabled": True,
            "scheduler_times": {
                "collect": "15:00",
                "calculate": "15:05",
                "north_bound": "16:00",
            },
        }
        for k, v in defaults.items():
            if k not in settings_map:
                settings_map[k] = v

        return {"code": 200, "data": settings_map}
    except Exception as e:
        logger.error(f"获取系统设置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/settings")
async def update_system_settings(settings_body: dict):
    """更新系统设置"""
    try:
        updated = {}
        for key, value in settings_body.items():
            redis_key = f"settings:{key}"
            redis_mgr.set(redis_key, json.dumps(value, ensure_ascii=False))
            updated[key] = value
        logger.info(f"系统设置已更新: {list(updated.keys())}")
        return {"code": 200, "message": "设置已更新", "data": updated}
    except Exception as e:
        logger.error(f"更新系统设置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/data/replay/dates")
async def get_replay_dates(start_date: str = None, end_date: str = None):
    """获取可用于回放的交易日列表"""
    try:
        min_range, max_range = influx_query.get_available_date_range()
        daily_data = influx_query.query_daily_sectors(
            start_date or (min_range or "2020-01-01"),
            end_date or (max_range or datetime.now().strftime("%Y-%m-%d")),
        )
        dates = sorted(daily_data.keys())
        return {"code": 200, "data": dates}
    except Exception as e:
        logger.error(f"获取回放日期列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/data/replay/sectors")
async def get_replay_sectors():
    """获取所有可用的板块列表"""
    try:
        sectors = influx_query.get_sector_list()
        return {"code": 200, "data": sectors}
    except Exception as e:
        logger.error(f"获取板块列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/data/replay/sector/{sector_code}")
async def get_replay_sector_history(sector_code: str, start_date: str = None, end_date: str = None):
    """获取单个板块的历史数据序列"""
    try:
        min_range, max_range = influx_query.get_available_date_range()
        history = influx_query.query_sector_history(
            sector_code=sector_code,
            start_date=start_date or (min_range or "2020-01-01"),
            end_date=end_date or (max_range or datetime.now().strftime("%Y-%m-%d")),
        )
        return {"code": 200, "data": history}
    except Exception as e:
        logger.error(f"获取板块历史数据失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/data/replay/day/{date}")
async def get_replay_day_data(date: str, sector_code: str = None):
    """获取某一天的板块交易数据用于回放"""
    try:
        daily_data = influx_query.query_daily_sectors(date, date, sector_code=sector_code)
        if date not in daily_data:
            raise HTTPException(status_code=404, detail=f"{date} 无数据")
        sectors = daily_data[date]
        sectors.sort(key=lambda x: x.get("index_change_pct", 0), reverse=True)
        return {"code": 200, "data": {"date": date, "sectors": sectors, "count": len(sectors)}}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取回放数据失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/data/replay/strategy-optimize")
async def optimize_strategy_params(request_body: dict):
    """自动寻优 - 使用 Optuna 贝叶斯优化找最优参数"""
    try:
        import optuna
        optuna.logging.set_verbosity(optuna.logging.WARNING)

        start_date = request_body.get("start_date", "")
        end_date = request_body.get("end_date", "")
        strategy_type_str = request_body.get("strategy_type", "MODERATE")
        initial_capital = request_body.get("initial_capital", 1000000.0)
        n_trials = request_body.get("n_trials", 50)

        if not start_date or not end_date:
            raise HTTPException(status_code=400, detail="必须提供 start_date 和 end_date")

        try:
            strategy_type = StrategyType(strategy_type_str)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"未知策略类型: {strategy_type_str}")

        daily_data = influx_query.query_daily_sectors(start_date, end_date)
        if not daily_data:
            raise HTTPException(status_code=404, detail="该时间范围内无历史数据")

        sorted_dates = sorted(daily_data.keys())
        logger.info(f"自动寻优: {len(sorted_dates)} 个交易日, 最多 {n_trials} 次试验")

        # Optuna 目标函数
        def objective(trial):
            params_dict = _suggest_params(trial, strategy_type)
            params = StrategyParams(**params_dict)
            result = _run_backtest_core(daily_data, sorted_dates, strategy_type, params, initial_capital)
            # 优化目标：收益/回撤比（越大越好）
            risk_adj = result["total_return"] / max(result["max_drawdown"], 0.01)
            return risk_adj

        study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=42))
        study.optimize(objective, n_trials=n_trials, show_progress_bar=False)

        # 收集所有试验结果
        all_results = []
        for trial in study.trials:
            if trial.state == optuna.trial.TrialState.COMPLETE:
                params_dict = _suggest_params(trial, strategy_type)
                params = StrategyParams(**params_dict)
                result = _run_backtest_core(daily_data, sorted_dates, strategy_type, params, initial_capital)
                all_results.append({
                    "params": params_dict,
                    "total_return": result["total_return"],
                    "annual_return": result["annual_return"],
                    "max_drawdown": result["max_drawdown"],
                    "sharpe_ratio": result["sharpe_ratio"],
                    "win_rate": result["win_rate"],
                    "trade_count": result["trade_count_actual"],
                    "risk_adj_score": round(trial.value, 4) if trial.value else 0,
                })

        all_results.sort(key=lambda x: x["risk_adj_score"], reverse=True)

        # 用最优参数跑完整回测
        best_params_dict = _suggest_params(study.best_trial, strategy_type)
        best_params = StrategyParams(**best_params_dict)
        final_result = _run_backtest_core(daily_data, sorted_dates, strategy_type, best_params, initial_capital, return_full=True)

        logger.info(f"自动寻优完成: {len(all_results)} 次有效试验, 最优收益={final_result['total_return']*100:.2f}%, 回撤={final_result['max_drawdown']*100:.2f}%")

        return {
            "code": 200,
            "data": {
                "best_params": best_params_dict,
                "best_result": final_result,
                "all_results": all_results,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"自动寻优失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _suggest_params(trial, strategy_type: StrategyType) -> dict:
    """根据策略类型生成 Optuna 参数建议"""
    # 交易成本参数（固定）
    base = {
        "commission_rate": 0.0003,
        "stamp_tax_rate": 0.001,
        "slippage_rate": 0.001,
        "keep_overlap": True,
        "allow_empty": True,
    }

    if strategy_type == StrategyType.AGGRESSIVE:
        min_score = trial.suggest_float("min_score_threshold", 0.5, 3.0, step=0.5)
        return {
            **base,
            "top_n": trial.suggest_int("top_n", 1, 3),
            "max_position": 1.0,
            "hold_days": trial.suggest_int("hold_days", 2, 5),
            "capital_pct": 0.5,
            "stop_loss": trial.suggest_float("stop_loss", 0.05, 0.20, step=0.01),
            "min_score_threshold": min_score,
            "score_gap_threshold": trial.suggest_float("score_gap_threshold", 0.5, 2.0, step=0.5),
            "cooldown_days": trial.suggest_int("cooldown_days", 1, 3),
            "min_score_keep": min(min_score + 0.5, 3.0),
        }
    elif strategy_type == StrategyType.MODERATE:
        min_score = trial.suggest_float("min_score_threshold", 1.0, 3.0, step=0.5)
        return {
            **base,
            "top_n": trial.suggest_int("top_n", 2, 4),
            "max_position": 0.5,
            "hold_days": trial.suggest_int("hold_days", 3, 7),
            "capital_pct": 0.3,
            "stop_loss": trial.suggest_float("stop_loss", 0.03, 0.15, step=0.01),
            "min_score_threshold": min_score,
            "score_gap_threshold": trial.suggest_float("score_gap_threshold", 0.5, 2.0, step=0.5),
            "cooldown_days": trial.suggest_int("cooldown_days", 1, 3),
            "min_score_keep": min(min_score + 0.5, 3.0),
        }
    else:  # CONSERVATIVE
        min_score = trial.suggest_float("min_score_threshold", 1.5, 3.5, step=0.5)
        return {
            **base,
            "top_n": trial.suggest_int("top_n", 3, 5),
            "max_position": 0.3,
            "hold_days": trial.suggest_int("hold_days", 5, 10),
            "capital_pct": 0.2,
            "stop_loss": trial.suggest_float("stop_loss", 0.02, 0.10, step=0.01),
            "valuation_pct_max": 50,
            "min_score_threshold": min_score,
            "score_gap_threshold": trial.suggest_float("score_gap_threshold", 0.5, 2.0, step=0.5),
            "cooldown_days": trial.suggest_int("cooldown_days", 2, 5),
            "min_score_keep": min(min_score + 0.5, 3.5),
        }


@app.post("/data/replay/strategy-overlay")
async def replay_strategy_overlay(request_body: dict):
    """数据回放 - 策略叠加"""
    try:
        start_date = request_body.get("start_date", "")
        end_date = request_body.get("end_date", "")
        strategy_type_str = request_body.get("strategy_type", "MODERATE")
        initial_capital = request_body.get("initial_capital", 1000000.0)
        params_override = request_body.get("params", None)

        if not start_date or not end_date:
            raise HTTPException(status_code=400, detail="必须提供 start_date 和 end_date")

        try:
            strategy_type = StrategyType(strategy_type_str)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"未知策略类型: {strategy_type_str}")

        config = DEFAULT_CONFIGS.get(strategy_type)
        if not config:
            raise HTTPException(status_code=400, detail="未知策略类型")
        params = StrategyParams(**params_override) if params_override else config.params

        daily_data = influx_query.query_daily_sectors(start_date, end_date)
        if not daily_data:
            raise HTTPException(status_code=404, detail="该时间范围内无历史数据")

        sorted_dates = sorted(daily_data.keys())
        trading_days = len(sorted_dates)

        result_data = _run_backtest_core(daily_data, sorted_dates, strategy_type, params, initial_capital, return_full=True)

        return {"code": 200, "data": result_data}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"策略叠加回放失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.service_port)
