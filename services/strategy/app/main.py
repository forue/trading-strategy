"""策略引擎服务 - FastAPI主应用"""
import calendar
import json
import hashlib
import pika
import redis as redis_lib
import numpy as np
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException
from loguru import logger

# 常量定义
TRADING_DAYS_PER_YEAR = 252  # 年化交易日天数

from .config import settings
from .models import (
    StrategyType, StrategyParams, StrategyConfig,
    TradeSignal, BacktestRequest, BacktestResult,
)
from .scoring import scoring_model, SECTOR_MAP
from .influx_query import influx_query

# RabbitMQ 连接管理
_rmq_connection = None
_rmq_channel = None


def _init_rmq():
    global _rmq_connection, _rmq_channel
    try:
        _rmq_connection = pika.BlockingConnection(
            pika.ConnectionParameters(
                host=settings.rabbitmq_host, port=settings.rabbitmq_port,
                credentials=pika.PlainCredentials(settings.rabbitmq_user, settings.rabbitmq_password),
            )
        )
        _rmq_channel = _rmq_connection.channel()
        _rmq_channel.exchange_declare(exchange="rotation", exchange_type="topic", durable=True)
        logger.info("RabbitMQ连接已建立")
    except Exception as e:
        logger.warning(f"RabbitMQ初始化失败: {e}")


def _close_rmq():
    global _rmq_connection, _rmq_channel
    try:
        if _rmq_channel and _rmq_channel.is_open:
            _rmq_channel.close()
        if _rmq_connection and _rmq_connection.is_open:
            _rmq_connection.close()
    except Exception as e:
        logger.debug(f"RabbitMQ关闭: {e}")
    finally:
        _rmq_connection = None
        _rmq_channel = None


def _get_rmq_channel():
    if _rmq_connection is None or _rmq_connection.is_closed:
        _init_rmq()
    return _rmq_channel


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


# InfluxDB日期范围缓存
_date_range_cache = {"result": None, "time": None}
DATE_RANGE_CACHE_TTL = 300  # 5分钟


@asynccontextmanager
async def lifespan(app: FastAPI):
    _init_rmq()
    yield
    _close_rmq()


app = FastAPI(title="策略引擎服务", version="1.0.0", lifespan=lifespan)

# Redis客户端
redis_client = redis_lib.Redis(
    host=settings.redis_host, port=settings.redis_port,
    password=settings.redis_password, db=settings.redis_db, decode_responses=True,
)

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
    """发送消息到RabbitMQ（复用持久连接）"""
    try:
        channel = _get_rmq_channel()
        if channel and channel.is_open:
            channel.basic_publish(exchange="rotation", routing_key=routing_key, body=json.dumps(message, ensure_ascii=False))
        else:
            logger.error("RabbitMQ通道不可用，消息未发送")
    except Exception as e:
        logger.error(f"RabbitMQ消息发送失败: {e}")


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
                "message": f"{target_date} {'是' if is_trade else '不是'}交易日"
            }
        }
    except Exception as e:
        logger.error(f"交易日检查失败: {e}")
        raise HTTPException(status_code=500, detail=f"交易日检查失败: {e}")


@app.post("/collect")
async def collect_data():
    """触发数据采集：从数据采集服务获取最新板块数据并写入InfluxDB"""
    try:
        import requests
        data_collector_url = "http://data-collector:8001/collect/sector-flow"
        response = requests.post(data_collector_url, timeout=60)
        if response.status_code == 200:
            result = response.json()
            logger.info(f"数据采集完成: {result}")
            return {"code": 200, "message": "数据采集完成", "data": result}
        else:
            logger.error(f"数据采集失败: {response.status_code}")
            return {"code": 500, "message": "数据采集失败"}
    except Exception as e:
        logger.error(f"数据采集异常: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _is_trade_day(date_str: str) -> bool:
    """检查是否为交易日（使用akshare交易日历）"""
    try:
        import akshare as ak
        df = ak.tool_trade_date_hist_sina()
        if df is not None and not df.empty:
            dates = df.iloc[:, 0].tolist()
            trade_dates = {d.strftime("%Y%m%d") if hasattr(d, "strftime") else str(d) for d in dates}
            return date_str.replace("-", "") in trade_dates
    except Exception:
        pass
    # 回退：简单跳过周末
    try:
        from datetime import datetime as dt
        d = dt.strptime(date_str.replace("-", ""), "%Y%m%d")
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
        cached = redis_client.get("sector_capital_flow:latest")
        if cached:
            sector_data = json.loads(cached)
            logger.info(f"从Redis获取到 {len(sector_data)} 条板块数据")
        else:
            # 如果Redis中没有数据，从InfluxDB读取最新数据
            logger.info("Redis中没有板块数据，从InfluxDB读取")
            try:
                # 获取最近3天的数据，确保有足够的数据
                end_date = effective_date
                start_date = (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=3)).strftime("%Y-%m-%d")
                daily_data = influx_query.query_daily_sectors(start_date, end_date)
                
                if daily_data and len(daily_data) > 0:
                    # 获取最新一天的数据
                    sorted_dates = sorted(daily_data.keys())
                    latest_date = sorted_dates[-1]
                    sector_data = daily_data[latest_date]
                    logger.info(f"从InfluxDB获取到 {len(sector_data)} 条板块数据（日期: {latest_date}）")
                    
                    # 检查数据格式
                    if sector_data and len(sector_data) > 0:
                        sample_item = sector_data[0]
                        logger.info(f"数据样例字段: {list(sample_item.keys())}")
                        logger.info(f"数据样例值: main_net_inflow={sample_item.get('main_net_inflow')}, "
                                  f"north_net_inflow={sample_item.get('north_net_inflow')}, "
                                  f"index_change_pct={sample_item.get('index_change_pct')}")
                    
                    # 将数据缓存到Redis，供下次使用
                    redis_client.setex(
                        "sector_capital_flow:latest",
                        3600,  # 1小时过期
                        json.dumps(sector_data, ensure_ascii=False)
                    )
                else:
                    logger.warning(f"InfluxDB中也没有找到板块数据，查询日期范围: {start_date} 到 {end_date}")
                    # 尝试查询更早的数据
                    earlier_start_date = (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=30)).strftime("%Y-%m-%d")
                    earlier_data = influx_query.query_daily_sectors(earlier_start_date, end_date)
                    if earlier_data and len(earlier_data) > 0:
                        sorted_dates = sorted(earlier_data.keys())
                        latest_date = sorted_dates[-1]
                        sector_data = earlier_data[latest_date]
                        logger.info(f"从更早范围获取到 {len(sector_data)} 条板块数据（日期: {latest_date}）")
                        
                        # 将数据缓存到Redis，供下次使用
                        redis_client.setex(
                            "sector_capital_flow:latest",
                            3600,  # 1小时过期
                            json.dumps(sector_data, ensure_ascii=False)
                        )
                    else:
                        logger.error("InfluxDB中完全找不到板块数据")
            except Exception as e:
                logger.error(f"从InfluxDB读取数据失败: {e}")

        # 计算信号
        logger.info(f"准备计算信号，sector_data类型: {type(sector_data)}, 长度: {len(sector_data) if isinstance(sector_data, list) else 'N/A'}")
        if sector_data and isinstance(sector_data, list) and len(sector_data) > 0:
            logger.info(f"第一个板块数据样例: sector_code={sector_data[0].get('sector_code')}, "
                      f"main_net_inflow={sector_data[0].get('main_net_inflow')}, "
                      f"north_net_inflow={sector_data[0].get('north_net_inflow')}")
        
        signals = scoring_model.calculate_daily_signals(
            sector_data=sector_data,
            strategy_type=strategy_type,
            params=config.params,
            signal_date=signal_date,
        )

        # 填充 id 和 created_at
        now = datetime.now().isoformat()
        for idx, s in enumerate(signals, 1):
            s.id = idx
            s.created_at = now

        # 缓存信号到Redis
        signal_dicts = [s.model_dump() for s in signals]
        redis_client.setex(
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
        raw = redis_client.get("strategy_configs")
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
        redis_client.set("strategy_configs", json.dumps(data, ensure_ascii=False))
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
            # 持久化到Redis
            _save_configs_to_redis()
            return {"code": 200, "message": "配置更新成功", "data": cfg.model_dump()}
    raise HTTPException(status_code=404, detail="配置不存在")


@app.get("/signals/today")
async def get_today_signals(strategy_type: StrategyType):
    """获取今日信号"""
    today = datetime.now().strftime("%Y-%m-%d")
    cached = redis_client.get(f"signals:{strategy_type.value}:{today}")
    if cached:
        return {"code": 200, "data": json.loads(cached)}
    return {"code": 200, "data": []}


@app.get("/signals/calendar")
async def get_signal_calendar(strategy_type: StrategyType, month: str = None):
    """获取信号日历数据

    Args:
        strategy_type: 策略类型
        month: 月份 YYYY-MM，默认当月
    """
    try:
        if month is None:
            month = datetime.now().strftime("%Y-%m")

        # 计算该月的天数
        year, mon = int(month[:4]), int(month[5:7])
        last_day = calendar.monthrange(year, mon)[1]

        # 使用 pipeline 批量查询该月所有信号
        pipe = redis_client.pipeline()
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
        # 优先使用请求中的参数，否则使用默认配置
        config = DEFAULT_CONFIGS.get(request.strategy_type)
        if not config:
            raise HTTPException(status_code=400, detail="未知策略类型")
        params = request.params if request.params else config.params
        logger.info(f"回测请求参数: request.params={request.params}")
        logger.info(f"回测使用参数: stop_loss={params.stop_loss}, top_n={params.top_n}, hold_days={params.hold_days}")

        # 从InfluxDB查询历史数据
        daily_data = influx_query.query_daily_sectors(request.start_date, request.end_date)
        if not daily_data:
            raise HTTPException(
                status_code=404,
                detail="没有可用的历史数据，请先通过数据采集服务采集历史数据（POST /api/data/collect/history）",
            )

        # 按日期排序
        sorted_dates = sorted(daily_data.keys())
        trading_days = len(sorted_dates)
        logger.info(f"回测 {request.strategy_type.value}: {trading_days} 个交易日, {sorted_dates[0]} ~ {sorted_dates[-1]}")

        # 逐日回放：每天用评分模型选板块，用实际涨跌幅计算收益
        capital = request.initial_capital
        peak_capital = capital  # 历史最高净值
        nav_curve = []
        daily_returns = []  # 策略每日收益率
        benchmark_returns = []  # 基准每日收益率（所有板块等权平均）
        position_hold_counter = 0  # 持仓天数计数器
        current_positions = {}  # {sector_code: weight}
        stop_loss_triggered = False  # 止损标记
        stop_loss_cooldown = 0  # 止损冷静期倒计数
        total_commission = 0.0  # 累计佣金
        total_stamp_tax = 0.0  # 累计印花税
        total_slippage_cost = 0.0  # 累计滑点成本
        trade_count_actual = 0  # 实际交易笔数
        rebalance_cooldown = 0  # 调仓冷却期

        for i, date in enumerate(sorted_dates):
            sector_data = daily_data[date]
            sector_change_map = {s["sector_code"]: s.get("index_change_pct", 0) / 100
                                 for s in sector_data}

            # === Step 1: 计算当日收益（基于昨日持仓，用今日涨跌幅）===
            strategy_daily_return = 0.0
            if stop_loss_triggered:
                # 止损空仓期间收益为0
                strategy_daily_return = 0.0
            elif current_positions:
                for sector_code, weight in current_positions.items():
                    change = sector_change_map.get(sector_code, 0)
                    strategy_daily_return += weight * change

            # 基准收益：所有板块等权平均
            all_changes = [s.get("index_change_pct", 0) / 100 for s in sector_data]
            benchmark_return = np.mean(all_changes) if all_changes else 0.0

            capital *= (1 + strategy_daily_return)
            daily_returns.append(strategy_daily_return)
            benchmark_returns.append(benchmark_return)

            # === Step 2: 更新历史最高净值 ===
            if capital > peak_capital:
                peak_capital = capital

            # === Step 3: 止损检查（收益已计入，检查是否需要止损）===
            if params.stop_loss and not stop_loss_triggered and peak_capital > 0 and current_positions:
                drawdown_from_peak = (peak_capital - capital) / peak_capital
                # 记录每日回撤情况（仅在有持仓时）
                if i % 5 == 0:  # 每5天记录一次，减少日志量
                    logger.debug(f"止损检查: 日期={date}, 峰值={peak_capital:.2f}, 当前={capital:.2f}, 回撤={drawdown_from_peak:.2%}, 止损线={params.stop_loss:.2%}, 持仓={bool(current_positions)}")
                if drawdown_from_peak >= params.stop_loss:
                    # 止损触发，卖出所有持仓并计算交易成本
                    sell_trade_cost = 0.0
                    for sector_code, weight in current_positions.items():
                        sell_amount = capital * weight
                        cost = _calc_trade_cost(sell_amount, params.commission_rate, params.stamp_tax_rate, params.slippage_rate, is_sell=True)
                        sell_trade_cost += cost["total"]
                        total_commission += cost["commission"]
                        total_stamp_tax += cost["stamp_tax"]
                        total_slippage_cost += cost["slippage"]
                        trade_count_actual += 1
                    
                    # 扣减交易成本
                    capital -= sell_trade_cost
                    
                    stop_loss_triggered = True
                    stop_loss_cooldown = params.hold_days  # 冷静期 = 一个持仓周期
                    position_hold_counter = 0  # 重置持仓计数器
                    current_positions = {}
                    logger.info(f"止损触发! 日期={date}, 峰值={peak_capital:.2f}, 当前={capital:.2f}, 回撤={drawdown_from_peak:.2%}, 止损线={params.stop_loss:.2%}, 冷静期={stop_loss_cooldown}日, 卖出成本={sell_trade_cost:.2f}")

            # === Step 4: 持仓天数递减 ===
            if current_positions and position_hold_counter > 0:
                position_hold_counter -= 1

            # === Step 5: 更新冷静期 ===
            if stop_loss_cooldown > 0:
                stop_loss_cooldown -= 1

            # === Step 5.5: 更新调仓冷却期 ===
            if rebalance_cooldown > 0:
                rebalance_cooldown -= 1

            # === Step 6: 检查是否需要调仓（冷静期结束后才可建仓）===
            if not stop_loss_triggered and position_hold_counter <= 0 and stop_loss_cooldown <= 0 and rebalance_cooldown <= 0:
                # 用当天的数据选板块 → 新持仓从明天开始生效
                # 传递当前持仓以支持持仓保留逻辑
                signals = scoring_model.calculate_daily_signals(
                    sector_data=sector_data,
                    strategy_type=request.strategy_type,
                    params=params,
                    signal_date=date,
                    current_positions=current_positions,
                )

                # 构建新持仓：买入信号对应的板块
                new_positions = {}
                buy_signals = [s for s in signals if s.direction.value == "BUY"]
                if buy_signals:
                    # 修复：总仓位不超过1.0，防止杠杆超限
                    # 实际仓位 = min(max_position * capital_pct, 1.0) / 买入信号数量
                    total_weight = min(params.max_position * params.capital_pct, 1.0)
                    per_weight = total_weight / len(buy_signals)
                    for sig in buy_signals:
                        new_positions[sig.sector_code] = per_weight

                if new_positions:
                    # === 计算本次调仓的交易成本 ===
                    sell_trade_cost = 0.0
                    for sector_code, weight in current_positions.items():
                        sell_amount = capital * weight
                        cost = _calc_trade_cost(sell_amount, params.commission_rate, params.stamp_tax_rate, params.slippage_rate, is_sell=True)
                        sell_trade_cost += cost["total"]
                        total_commission += cost["commission"]
                        total_stamp_tax += cost["stamp_tax"]
                        total_slippage_cost += cost["slippage"]
                        trade_count_actual += 1

                    buy_trade_cost = 0.0
                    for sector_code, weight in new_positions.items():
                        buy_amount = capital * weight
                        cost = _calc_trade_cost(buy_amount, params.commission_rate, params.stamp_tax_rate, params.slippage_rate, is_sell=False)
                        buy_trade_cost += cost["total"]
                        total_commission += cost["commission"]
                        total_slippage_cost += cost["slippage"]
                        trade_count_actual += 1

                    total_trade_cost = sell_trade_cost + buy_trade_cost
                    capital -= total_trade_cost

                    current_positions = new_positions
                    position_hold_counter = params.hold_days
                    stop_loss_triggered = False
                    rebalance_cooldown = params.cooldown_days if params.cooldown_days else 2

            # === Step 7: 记录净值曲线 ===
            step = max(1, trading_days // 100)
            if i % step == 0 or i == trading_days - 1:
                # 计算基准净值（从开始到当前日的累计收益）
                benchmark_nav = request.initial_capital * np.prod([1 + r for r in benchmark_returns[:i+1]])
                nav_curve.append({
                    "date": date,
                    "nav": round(capital, 2),
                    "benchmark": round(float(benchmark_nav), 2),
                    "stop_loss": stop_loss_triggered,
                })

        # 计算回测指标
        total_return = (capital / request.initial_capital) - 1
        trading_years = max(trading_days / TRADING_DAYS_PER_YEAR, 0.01)
        annual_return = (1 + total_return) ** (1 / trading_years) - 1

        # 最大回撤 - 使用净值曲线计算
        if nav_curve:
            nav_array = np.array([p["nav"] for p in nav_curve])
            peak = np.maximum.accumulate(nav_array)
            drawdown = (nav_array - peak) / peak
            max_drawdown = abs(drawdown.min()) if len(drawdown) > 0 else 0
        else:
            max_drawdown = 0.0

        # 夏普比率
        daily_arr = np.array(daily_returns)
        sharpe = (np.mean(daily_arr) * TRADING_DAYS_PER_YEAR) / (np.std(daily_arr) * np.sqrt(TRADING_DAYS_PER_YEAR)) if np.std(daily_arr) > 0 else 0

        # 胜率
        win_rate = float(np.mean(daily_arr > 0)) if len(daily_arr) > 0 else 0

        now = datetime.now().isoformat()
        bt_id = f"bt_{request.strategy_type.value}_{datetime.now().strftime('%Y%m%d%H%M%S')}"

        result = BacktestResult(
            id=bt_id,
            strategy_type=request.strategy_type,
            start_date=request.start_date,
            end_date=request.end_date,
            initial_capital=request.initial_capital,
            total_return=round(float(total_return), 4),
            annual_return=round(float(annual_return), 4),
            max_drawdown=round(float(max_drawdown), 4),
            sharpe_ratio=round(float(sharpe), 2),
            win_rate=round(float(win_rate), 4),
            trade_count=max(1, trading_days // params.hold_days),
            # 交易成本统计
            total_commission=round(total_commission, 2),
            total_stamp_tax=round(total_stamp_tax, 2),
            total_slippage_cost=round(total_slippage_cost, 2),
            total_trade_cost=round(total_commission + total_stamp_tax + total_slippage_cost, 2),
            trade_count_actual=trade_count_actual,
            nav_curve=nav_curve,
            created_at=now,
        )

        # 将回测结果保存到Redis（保留7天）
        result_data = result.model_dump()
        redis_client.setex(
            f"backtest:{bt_id}",
            7 * 86400,
            json.dumps(result_data, ensure_ascii=False),
        )
        # 同时保存到回测历史列表
        history_key = f"backtest_history:{request.strategy_type.value}"
        history_entry = {
            "id": bt_id,
            "strategy_type": request.strategy_type.value,
            "start_date": request.start_date,
            "end_date": request.end_date,
            "initial_capital": request.initial_capital,
            "total_return": result.total_return,
            "annual_return": result.annual_return,
            "max_drawdown": result.max_drawdown,
            "sharpe_ratio": result.sharpe_ratio,
            "params": params.model_dump(),
            "created_at": now,
            "data_source": "influxdb",
            "trading_days": trading_days,
        }
        try:
            history_raw = redis_client.get(history_key)
            history = json.loads(history_raw) if history_raw else []
        except Exception:
            history = []
        history.insert(0, history_entry)
        history = history[:20]
        redis_client.setex(history_key, 30 * 86400, json.dumps(history, ensure_ascii=False))

        return {"code": 200, "data": result_data}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"回测失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
            raw = redis_client.get(key)
            if raw:
                results.extend(json.loads(raw))

        # 按创建时间降序排序
        results.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return {"code": 200, "data": results}
    except Exception as e:
        logger.error(f"获取回测历史失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/backtest/{bt_id}")
async def get_backtest_detail(bt_id: str):
    """获取回测详情"""
    raw = redis_client.get(f"backtest:{bt_id}")
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
        info = redis_client.info("memory")
        keyspace = redis_client.info("keyspace")
        db_idx = settings.redis_db
        db_info = keyspace.get(f"db{db_idx}", {})
        total_keys = db_info.get("keys", 0) if isinstance(db_info, dict) else 0

        # 分类统计各类缓存key
        categories = {}
        patterns = [
            ("backtest_result", "backtest:*"),
            ("backtest_history", "backtest_history:*"),
            ("signals", "signals:*"),
            ("sector_data", "sector_capital_flow:*"),
            ("system_settings", "settings:*"),
        ]
        for name, pattern in patterns:
            count = len(list(redis_client.scan_iter(match=pattern)))
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
        redis_client.flushdb()
        logger.info("缓存已全部清空")
        return {"code": 200, "message": "缓存已全部清空"}
    except Exception as e:
        logger.error(f"清空缓存失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/cache/expired")
async def clear_expired_cache():
    """清除已过期的缓存key（Redis会自动过期，此接口扫描无TTL的key并设置默认过期）"""
    try:
        cleared = 0
        cursor = 0
        while True:
            cursor, keys = redis_client.scan(cursor, count=200)
            for key in keys:
                ttl = redis_client.ttl(key)
                if ttl == -1:  # 没有设置过期时间
                    redis_client.expire(key, 7 * 86400)  # 默认7天过期
                    cleared += 1
            if cursor == 0:
                break
        return {"code": 200, "message": f"已为 {cleared} 个无过期时间的key设置7天TTL"}
    except Exception as e:
        logger.error(f"清理过期缓存失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/database/status")
async def get_database_status():
    """获取数据库状态信息"""
    try:
        # PostgreSQL状态（通过Docker网络访问）
        pg_status = "unavailable"
        try:
            import psycopg2
            conn = psycopg2.connect(
                host="postgres",
                database="rotation_db", user="admin", password="secret",
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
            # InfluxDB health() 返回 status: "pass"/"fail"
            raw_status = health.status if hasattr(health, "status") else "unknown"
            if raw_status == "pass":
                influx_status = "connected"
                influx_detail = health.message if hasattr(health, "message") else ""
            elif raw_status == "fail":
                influx_status = "unavailable"
                influx_detail = health.message if hasattr(health, "message") else "服务异常"
            else:
                influx_status = "connected"
        except Exception as e:
            logger.debug(f"InfluxDB连接检查: {e}")

        # Redis状态
        redis_status = "connected" if redis_client.ping() else "disconnected"
        redis_info = redis_client.info("server")
        redis_mem = redis_client.info("memory")

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
        # 从Redis读取自定义设置（使用SCAN避免阻塞）
        for key in redis_client.scan_iter(match="settings:*"):
            val = redis_client.get(key)
            short_key = key.replace("settings:", "")
            try:
                settings_map[short_key] = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                settings_map[short_key] = val

        # 默认设置
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
        # 合并：用户设置覆盖默认
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
            if isinstance(value, (dict, list)):
                redis_client.set(redis_key, json.dumps(value, ensure_ascii=False))
            else:
                redis_client.set(redis_key, str(value))
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
    """获取单个板块的历史数据序列（按板块回放）"""
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
    """获取某一天的板块交易数据用于回放

    Args:
        date: 日期 YYYY-MM-DD
        sector_code: 可选，筛选特定板块
    """
    try:
        daily_data = influx_query.query_daily_sectors(date, date, sector_code=sector_code)
        if date not in daily_data:
            raise HTTPException(status_code=404, detail=f"{date} 无数据")
        sectors = daily_data[date]
        # 按涨跌幅排序
        sectors.sort(key=lambda x: x.get("index_change_pct", 0), reverse=True)
        return {"code": 200, "data": {"date": date, "sectors": sectors, "count": len(sectors)}}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取回放数据失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/data/replay/strategy-optimize")
async def optimize_strategy_params(request_body: dict):
    """自动寻优 - 根据历史数据遍历参数组合找出最优参数
    
    Request Body:
        start_date: str - 起始日期
        end_date: str - 结束日期
        strategy_type: str - 策略类型
        initial_capital: float - 初始资金（默认100万）
    
    Returns:
        best_params: 最优参数
        best_result: 最优结果
        all_results: 所有组合的结果
    """
    try:
        start_date = request_body.get("start_date", "")
        end_date = request_body.get("end_date", "")
        strategy_type_str = request_body.get("strategy_type", "MODERATE")
        initial_capital = request_body.get("initial_capital", 1000000.0)
        
        if not start_date or not end_date:
            raise HTTPException(status_code=400, detail="必须提供 start_date 和 end_date")
        
        try:
            strategy_type = StrategyType(strategy_type_str)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"未知策略类型: {strategy_type_str}")
        
        # 参数组合（根据策略类型生成）
        param_combinations = _generate_param_combinations(strategy_type)
        logger.info(f"自动寻优: 将测试 {len(param_combinations)} 种参数组合")
        
        # 查询历史数据
        daily_data = influx_query.query_daily_sectors(start_date, end_date)
        if not daily_data:
            raise HTTPException(status_code=404, detail="该时间范围内无历史数据")
        
        sorted_dates = sorted(daily_data.keys())
        logger.info(f"自动寻优: 查询到 {len(sorted_dates)} 个交易日, 从 {sorted_dates[0]} 到 {sorted_dates[-1]}")
        
        # 遍历参数组合
        results = []
        for i, params_dict in enumerate(param_combinations):
            params = StrategyParams(**params_dict)
            
            # 运行回测
            result = _run_backtest(daily_data, sorted_dates, strategy_type, params, initial_capital)
            results.append({
                "params": params_dict,
                "total_return": result["total_return"],
                "annual_return": result["annual_return"],
                "max_drawdown": result["max_drawdown"],
                "trade_count": result["trade_count"],
            })
            
            logger.info(f"参数组合 {i+1}/{len(param_combinations)}: {params_dict}, 收益={result['total_return']*100:.2f}%")
        
        # 排序找最优
        results.sort(key=lambda x: x["total_return"], reverse=True)
        best = results[0]
        
        # 用最优参数再次运行获取完整结果
        best_params = StrategyParams(**best["params"])
        final_result = _run_backtest(daily_data, sorted_dates, strategy_type, best_params, initial_capital, return_full=True)
        
        return {
            "code": 200,
            "data": {
                "best_params": best["params"],
                "best_result": final_result,
                "all_results": results,
            }
        }
    except Exception as e:
        logger.error(f"自动寻优失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

def _generate_param_combinations(strategy_type: StrategyType) -> list[dict]:
    """根据策略类型生成参数组合"""
    combinations = []
    
    if strategy_type == StrategyType.AGGRESSIVE:
        # 激进策略：top_n 1-3, hold_days 2-5, stop_loss 6%-15%, min_score 1.0-3.0
        for top_n in [1, 2, 3]:
            for hold_days in [2, 3, 5]:
                for stop_loss in [0.06, 0.08, 0.10, 0.12, 0.15]:
                    for min_score in [1.0, 2.0, 2.5]:
                        combinations.append({
                            "top_n": top_n,
                            "max_position": 1.0,
                            "hold_days": hold_days,
                            "capital_pct": 0.5,
                            "stop_loss": stop_loss,
                            "commission_rate": 0.0003,
                            "stamp_tax_rate": 0.001,
                            "slippage_rate": 0.001,
                            "min_score_threshold": min_score,
                            "score_gap_threshold": 1.0,
                            "cooldown_days": 2,
                            "keep_overlap": True,
                            "allow_empty": True,
                            "min_score_keep": min(min_score + 0.5, 3.0),
                        })
    elif strategy_type == StrategyType.MODERATE:
        # 稳健策略
        for top_n in [2, 3, 4]:
            for hold_days in [3, 5, 7]:
                for stop_loss in [0.05, 0.08, 0.10, 0.12]:
                    for min_score in [1.5, 2.0, 2.5]:
                        combinations.append({
                            "top_n": top_n,
                            "max_position": 0.5,
                            "hold_days": hold_days,
                            "capital_pct": 0.3,
                            "stop_loss": stop_loss,
                            "commission_rate": 0.0003,
                            "stamp_tax_rate": 0.001,
                            "slippage_rate": 0.001,
                            "min_score_threshold": min_score,
                            "score_gap_threshold": 1.0,
                            "cooldown_days": 2,
                            "keep_overlap": True,
                            "allow_empty": True,
                            "min_score_keep": min(min_score + 0.5, 3.0),
                        })
    else:
        # 保守策略
        for top_n in [3, 4, 5]:
            for hold_days in [5, 7, 10]:
                for stop_loss in [0.03, 0.05, 0.08]:
                    for min_score in [2.0, 2.5, 3.0]:
                        combinations.append({
                            "top_n": top_n,
                            "max_position": 0.3,
                            "hold_days": hold_days,
                            "capital_pct": 0.2,
                            "stop_loss": stop_loss,
                            "valuation_pct_max": 50,
                            "commission_rate": 0.0003,
                            "stamp_tax_rate": 0.001,
                            "slippage_rate": 0.001,
                            "min_score_threshold": min_score,
                            "score_gap_threshold": 1.0,
                            "cooldown_days": 3,
                            "keep_overlap": True,
                            "allow_empty": True,
                            "min_score_keep": min(min_score + 0.5, 3.5),
                        })
    
    # 限制数量避免过长
    return combinations[:30] if len(combinations) > 30 else combinations

def _run_backtest(daily_data, sorted_dates, strategy_type, params, initial_capital, return_full=False):
    """运行回测的核心逻辑（使用模块级 TRADING_DAYS_PER_YEAR=252）"""
    
    capital = initial_capital
    peak_capital = capital
    position_hold_counter = 0
    current_positions = {}
    stop_loss_triggered = False
    stop_loss_cooldown = 0
    rebalance_cooldown = 0  # 调仓冷却期
    nav_curve = []
    daily_signals_out = []
    buy_count = 0
    sell_count = 0
    total_commission = 0.0
    total_stamp_tax = 0.0
    total_slippage_cost = 0.0
    
    logger.info(f"=== 回测开始: {sorted_dates[0]} ~ {sorted_dates[-1]}, 初始资金={initial_capital}, 日期数={len(sorted_dates)} ===")
    
    for date in sorted_dates:
        sector_data = daily_data[date]
        day_signals = []
        
        sector_change_map = {s["sector_code"]: s.get("index_change_pct", 0) / 100 for s in sector_data}
        
        strategy_daily_return = 0.0
        if stop_loss_triggered:
            strategy_daily_return = 0.0
        elif current_positions:
            for sector_code, weight in current_positions.items():
                strategy_daily_return += weight * sector_change_map.get(sector_code, 0)
        
        all_changes = [s.get("index_change_pct", 0) / 100 for s in sector_data]
        benchmark_return = float(np.mean(all_changes)) if all_changes else 0.0
        
        capital *= (1 + strategy_daily_return)
        if capital > peak_capital:
            peak_capital = capital
        
        # 止损检查
        if params.stop_loss and not stop_loss_triggered and peak_capital > 0 and current_positions:
            drawdown = (peak_capital - capital) / peak_capital
            if drawdown >= params.stop_loss:
                logger.info(f"{date}: 止损触发! 回撤={drawdown:.2%}, threshold={params.stop_loss:.2%}, 当前持仓={current_positions}")
                sell_trade_cost = 0.0
                for sector_code, weight in current_positions.items():
                    sell_amount = capital * weight
                    cost = _calc_trade_cost(sell_amount, params.commission_rate, params.stamp_tax_rate, params.slippage_rate, is_sell=True)
                    sell_trade_cost += cost["total"]
                    total_commission += cost["commission"]
                    total_stamp_tax += cost["stamp_tax"]
                    total_slippage_cost += cost["slippage"]
                capital -= sell_trade_cost
                stop_loss_triggered = True
                stop_loss_cooldown = params.hold_days + 1
                position_hold_counter = 0
                for code in current_positions:
                    day_signals.append({
                        "sector_code": code,
                        "sector_name": "止损",
                        "direction": "SELL",
                        "score": 0,
                        "reason": f"止损触发: 回撤{drawdown:.2%}",
                    })
                sell_count += len(current_positions)
                current_positions = {}
        
        if current_positions and position_hold_counter > 0:
            position_hold_counter -= 1
        
        if stop_loss_cooldown > 0:
            stop_loss_cooldown -= 1
            if stop_loss_cooldown <= 0:
                stop_loss_triggered = False
                logger.info(f"{date}: 止损冷却结束, 重置stop_loss_triggered=False, 持仓={current_positions}")
        
        if rebalance_cooldown > 0:
            rebalance_cooldown -= 1
        
        # 调仓检查：持仓到期且不在冷却期
        if not stop_loss_triggered and position_hold_counter <= 0 and stop_loss_cooldown <= 0 and rebalance_cooldown <= 0:
            signals = scoring_model.calculate_daily_signals(
                sector_data=sector_data,
                strategy_type=strategy_type,
                params=params,
                signal_date=date,
                current_positions=current_positions,
            )
            
            buy_sigs = [s for s in signals if s.direction.value == "BUY"]
            sell_sigs = [s for s in signals if s.direction.value == "SELL"]
            
            new_positions = {}
            buy_sigs = [s for s in signals if s.direction.value == "BUY"]
            
            if buy_sigs:
                total_weight = min(params.max_position * params.capital_pct, 1.0)
                per_weight = total_weight / len(buy_sigs)
                for sig in buy_sigs:
                    new_positions[sig.sector_code] = per_weight
                    day_signals.append({
                        "sector_code": sig.sector_code,
                        "sector_name": sig.sector_name,
                        "direction": sig.direction.value,
                        "score": sig.score,
                        "reason": sig.reason,
                    })
                    buy_count += 1
                logger.info(f"{date}: 买入建仓 {len(buy_sigs)} 个板块: {[s.sector_code for s in buy_sigs]}")
            
            sell_sigs = [s for s in signals if s.direction.value == "SELL"]
            for sig in sell_sigs:
                day_signals.append({
                    "sector_code": sig.sector_code,
                    "sector_name": sig.sector_name,
                    "direction": sig.direction.value,
                    "score": sig.score,
                    "reason": sig.reason,
                })
                sell_count += 1
            
            if new_positions:
                current_positions = new_positions
                position_hold_counter = params.hold_days
                stop_loss_triggered = False
                rebalance_cooldown = params.cooldown_days if params.cooldown_days else 2
        
        daily_signals_out.append({
            "date": date,
            "signals": day_signals,
            "strategy_return": round(strategy_daily_return * 100, 4),
            "benchmark_return": round(benchmark_return * 100, 4),
        })
        
        nav_curve.append({
            "date": date,
            "nav": round(capital, 2),
            "benchmark": 0.0,
        })
    
    total_return = (capital / initial_capital) - 1
    
    # 计算基准净值
    benchmark_nav = initial_capital
    for item in nav_curve:
        date = item["date"]
        sector_data = daily_data[date]
        all_changes = [s.get("index_change_pct", 0) / 100 for s in sector_data]
        benchmark_nav *= (1 + float(np.mean(all_changes)) if all_changes else 0)
        item["benchmark"] = round(benchmark_nav, 2)
    
    result = {
        "total_return": total_return,
        "annual_return": (1 + total_return) ** (TRADING_DAYS_PER_YEAR / len(sorted_dates)) - 1 if sorted_dates else 0,
        "max_drawdown": float(np.max((np.maximum.accumulate(np.array([n["nav"] for n in nav_curve])) - np.array([n["nav"] for n in nav_curve])) / np.maximum.accumulate(np.array([n["nav"] for n in nav_curve])))) if nav_curve else 0,
        "trade_count": buy_count + sell_count,
        "buy_count": buy_count,
        "sell_count": sell_count,
        "daily_signals": daily_signals_out,
        "nav_curve": nav_curve,
    }
    
    if return_full:
        return result
    
    return {
        "total_return": result["total_return"],
        "annual_return": result["annual_return"],
        "max_drawdown": result["max_drawdown"],
        "trade_count": result["trade_count"],
    }


@app.post("/data/replay/strategy-overlay")
async def replay_strategy_overlay(request_body: dict):
    """数据回放 - 策略叠加

    Request Body:
        start_date: str - 起始日期
        end_date: str - 结束日期
        strategy_type: str - 策略类型 AGGRESSIVE/MODERATE/CONSERVATIVE
        initial_capital: float - 初始资金（默认100万）
        params: dict - 可选，策略参数覆盖

    Returns:
        daily_signals: [{date, signals: [{sector_code, sector_name, direction, score, reason}], ...}]
        nav_curve: [{date, nav, benchmark, positions}]
        summary: {total_return, max_drawdown, trade_count, buy_count, sell_count}
    """
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

        # 获取策略参数
        config = DEFAULT_CONFIGS.get(strategy_type)
        if not config:
            raise HTTPException(status_code=400, detail="未知策略类型")
        if params_override:
            params = StrategyParams(**params_override)
        else:
            params = config.params

        # 查询历史数据
        daily_data = influx_query.query_daily_sectors(start_date, end_date)
        if not daily_data:
            raise HTTPException(status_code=404, detail="该时间范围内无历史数据")

        sorted_dates = sorted(daily_data.keys())
        trading_days = len(sorted_dates)

        # 逐日运行策略
        capital = initial_capital
        peak_capital = capital
        position_hold_counter = 0
        current_positions = {}  # {sector_code: weight}
        stop_loss_triggered = False
        stop_loss_cooldown = 0  # 止损冷静期倒计数
        total_commission = 0.0  # 累计佣金
        total_stamp_tax = 0.0  # 累计印花税
        total_slippage_cost = 0.0  # 累计滑点成本
        trade_count_actual = 0  # 实际交易笔数
        rebalance_cooldown = 0  # 调仓冷却期

        daily_signals_out = []
        nav_curve = []
        buy_count = 0
        sell_count = 0

        for i, date in enumerate(sorted_dates):
            sector_data = daily_data[date]
            day_signals = []

            sector_change_map = {s["sector_code"]: s.get("index_change_pct", 0) / 100 for s in sector_data}

            # === Step 1: 计算当日收益（基于昨日持仓，用今日涨跌幅）===
            strategy_daily_return = 0.0
            if stop_loss_triggered:
                # 止损触发后已空仓，当日无策略收益（持仓在当日开盘前已卖出）
                strategy_daily_return = 0.0
            elif current_positions:
                # 正常持仓，计算收益
                for sector_code, weight in current_positions.items():
                    strategy_daily_return += weight * sector_change_map.get(sector_code, 0)

            # 基准收益
            all_changes = [s.get("index_change_pct", 0) / 100 for s in sector_data]
            benchmark_return = float(np.mean(all_changes)) if all_changes else 0.0

            capital *= (1 + strategy_daily_return)
            if capital > peak_capital:
                peak_capital = capital

            # === Step 2: 止损检查 ===
            if params.stop_loss and not stop_loss_triggered and peak_capital > 0 and current_positions:
                drawdown = (peak_capital - capital) / peak_capital
                if drawdown >= params.stop_loss:
                    # 止损触发，卖出所有持仓并计算交易成本
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
                    day_signals.append({
                        "sector_code": "",
                        "sector_name": "全部持仓",
                        "direction": "SELL",
                        "score": 0,
                        "reason": f"止损触发: 回撤{drawdown:.2%} >= 止损线{params.stop_loss:.2%}, 冷静{stop_loss_cooldown}日, 卖出成本={sell_trade_cost:.2f}",
                    })
                    sell_count += 1

            # === Step 3: 持仓天数递减 ===
            if current_positions and position_hold_counter > 0:
                position_hold_counter -= 1

            # === Step 4: 更新冷静期 ===
            if stop_loss_cooldown > 0:
                stop_loss_cooldown -= 1
                # 冷静期结束后清除止损状态
                if stop_loss_cooldown <= 0:
                    stop_loss_triggered = False

            # === Step 4.5: 更新调仓冷却期 ===
            if rebalance_cooldown > 0:
                rebalance_cooldown -= 1

            # === Step 5: 检查是否需要调仓 ===
            if not stop_loss_triggered and position_hold_counter <= 0 and stop_loss_cooldown <= 0 and rebalance_cooldown <= 0:
                signals = scoring_model.calculate_daily_signals(
                    sector_data=sector_data,
                    strategy_type=strategy_type,
                    params=params,
                    signal_date=date,
                    current_positions=current_positions,
                )

                new_positions = {}
                buy_sigs = [s for s in signals if s.direction.value == "BUY"]
                sell_sigs = [s for s in signals if s.direction.value == "SELL"]
                
                if buy_sigs:
                    # 修复：总仓位不超过1.0，防止杠杆超限
                    # 实际仓位 = min(max_position * capital_pct, 1.0) / 买入信号数量
                    total_weight = min(params.max_position * params.capital_pct, 1.0)
                    per_weight = total_weight / len(buy_sigs)
                    for sig in buy_sigs:
                        new_positions[sig.sector_code] = per_weight
                        buy_count += 1
                
                sell_count += len(sell_sigs)
                
                # 记录所有信号
                for sig in signals:
                    day_signals.append({
                        "sector_code": sig.sector_code,
                        "sector_name": sig.sector_name,
                        "direction": sig.direction.value,
                        "score": round(sig.score, 2),
                        "reason": sig.reason,
                    })

                if new_positions:
                    # === 计算本次调仓的交易成本 ===
                    sell_trade_cost = 0.0
                    for sector_code, weight in current_positions.items():
                        sell_amount = capital * weight
                        cost = _calc_trade_cost(sell_amount, params.commission_rate, params.stamp_tax_rate, params.slippage_rate, is_sell=True)
                        sell_trade_cost += cost["total"]
                        total_commission += cost["commission"]
                        total_stamp_tax += cost["stamp_tax"]
                        total_slippage_cost += cost["slippage"]
                        trade_count_actual += 1

                    buy_trade_cost = 0.0
                    for sector_code, weight in new_positions.items():
                        buy_amount = capital * weight
                        cost = _calc_trade_cost(buy_amount, params.commission_rate, params.stamp_tax_rate, params.slippage_rate, is_sell=False)
                        buy_trade_cost += cost["total"]
                        total_commission += cost["commission"]
                        total_slippage_cost += cost["slippage"]
                        trade_count_actual += 1

                    total_trade_cost = sell_trade_cost + buy_trade_cost
                    capital -= total_trade_cost

                    current_positions = new_positions
                    position_hold_counter = params.hold_days
                    stop_loss_triggered = False
                    rebalance_cooldown = params.cooldown_days if params.cooldown_days else 2

            # 记录信号
            daily_signals_out.append({
                "date": date,
                "signals": day_signals,
                "strategy_return": round(strategy_daily_return * 100, 4),
                "benchmark_return": round(benchmark_return * 100, 4),
                "positions": {k: round(v, 4) for k, v in current_positions.items()} if not stop_loss_triggered else {},
            })

            # 净值曲线
            nav_curve.append({
                "date": date,
                "nav": round(capital, 2),
                "benchmark": 0.0,  # 将在后续循环中重新计算
                "positions": list(current_positions.keys()) if not stop_loss_triggered else [],
                "stop_loss": stop_loss_triggered,
            })

        # 预计算每日基准收益（性能优化：避免循环内重复计算）
        benchmark_returns = {}
        for date, sector_data in daily_data.items():
            all_changes = [s.get("index_change_pct", 0) / 100 for s in sector_data]
            benchmark_returns[date] = float(np.mean(all_changes)) if all_changes else 0.0

        # 计算基准净值（复利）
        benchmark_nav = initial_capital
        for i, nav_item in enumerate(nav_curve):
            date = nav_item["date"]
            benchmark_nav *= (1 + benchmark_returns.get(date, 0))
            nav_item["benchmark"] = round(benchmark_nav, 2)

        # 汇总
        total_return = (capital / initial_capital) - 1
        nav_array = np.array([p["nav"] for p in nav_curve])
        peak_arr = np.maximum.accumulate(nav_array)
        drawdown_arr = (nav_array - peak_arr) / peak_arr
        max_drawdown = abs(float(drawdown_arr.min())) if len(drawdown_arr) > 0 else 0

        summary = {
            "total_return": round(float(total_return), 4),
            "annual_return": round(float((1 + total_return) ** (TRADING_DAYS_PER_YEAR / max(trading_days, 1)) - 1), 4),
            "max_drawdown": round(float(max_drawdown), 4),
            "trade_count": max(1, trading_days // params.hold_days),
            "buy_count": buy_count,
            "sell_count": sell_count,
            "trading_days": trading_days,
            "strategy_type": strategy_type.value,
            "initial_capital": initial_capital,
            "final_capital": round(capital, 2),
            # 交易成本统计
            "total_commission": round(total_commission, 2),
            "total_stamp_tax": round(total_stamp_tax, 2),
            "total_slippage_cost": round(total_slippage_cost, 2),
            "total_trade_cost": round(total_commission + total_stamp_tax + total_slippage_cost, 2),
            "trade_count_actual": trade_count_actual,
            # 策略参数
            "params": {
                "top_n": params.top_n,
                "max_position": params.max_position,
                "hold_days": params.hold_days,
                "stop_loss": params.stop_loss,
                "min_score_threshold": params.min_score_threshold,
                "score_gap_threshold": params.score_gap_threshold,
                "cooldown_days": params.cooldown_days,
            },
        }

        return {
            "code": 200,
            "data": {
                "daily_signals": daily_signals_out,
                "nav_curve": nav_curve,
                "summary": summary,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"策略叠加回放失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.service_port)
