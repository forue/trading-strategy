"""策略引擎服务 - FastAPI主应用"""
import sys
import os
import asyncio
import calendar
import hashlib
import json
import threading
import time
import uuid
import numpy as np
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
from loguru import logger

# 添加共享库路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared import (
    ADMIN_USER_ID,
    AuthError,
    get_current_user,
    set_jwt_secret,
    success_response,
    user_scope,
)

# 常量定义
TRADING_DAYS_PER_YEAR = 252  # 年化交易日天数

from .config import settings
from .models import (
    StrategyType, StrategyParams, StrategyConfig,
    TradeSignal, BacktestRequest, BacktestResult,
    FactorAnalyzeRequest, SignalDirection,
)
from .scoring import scoring_model
from .influx_query import influx_query
from .stock_sense import router as stock_sense_router
from . import signal_tracker, workshop
from shared import RabbitMQManager, RedisManager

# 配置日志
logger.remove()
logger.add(sys.stderr, level=settings.log_level)

# 初始化连接管理器
rmq = RabbitMQManager()
redis_mgr = RedisManager()

# 与 auth 服务共用密钥，本地验签即可识别当前用户
set_jwt_secret(settings.jwt_secret)


def _require_user(authorization: str | None):
    """解析当前登录用户，缺失或无效时返回 401"""
    try:
        return get_current_user(authorization)
    except AuthError as e:
        raise HTTPException(status_code=401, detail=str(e))


def _resolve_actor(authorization: str | None, internal_token: str | None = None):
    """确定本次请求的数据归属账号。

    浏览器请求走 JWT；调度器 / mcp-agent / ai-decision 这些没有登录态的内部调用
    用共享密钥换管理员身份。两者都没有时保持旧行为（视为管理员），避免内部
    调用方全部 401 —— 一旦配置了 INTERNAL_TOKEN，不带密钥的匿名请求就会被拒。
    """
    if settings.internal_token and internal_token and internal_token == settings.internal_token:
        return _SystemActor()
    if authorization:
        return _require_user(authorization)
    if settings.internal_token:
        raise HTTPException(status_code=401, detail="缺少访问凭证")
    return _SystemActor()


class _SystemActor:
    """内部服务调用者：数据归属管理员账号"""

    user_id = ADMIN_USER_ID
    username = "system"
    role = "ADMIN"


def _ukey(user_id: int, suffix: str) -> str:
    """用户维度 Redis 键：user:{id}:{suffix}"""
    return f"{user_scope(user_id)}:{suffix}"


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
    # 必须在 redis 连接建立之后恢复配置：模块导入期调用必然失败（Redis 未连接），
    # 会导致接口保存的策略配置在服务重启后被丢弃
    # 历史全局策略配置先归并到管理员，再预加载管理员配置
    _migrate_legacy_configs()
    _user_configs(ADMIN_USER_ID)
    # 历史全局个人设置归并到管理员账号，避免旧键与新键两套口径并存
    _migrate_legacy_user_settings()
    # 盘感训练历史记录：stock_sense:records:{username} -> user:{id}:stock_sense:records
    try:
        from .stock_sense import migrate_legacy_records

        migrate_legacy_records()
    except Exception as e:
        logger.warning(f"盘感训练历史记录迁移跳过: {e}")
    # 信号跟踪表：供复盘统计（PG 异常时降级，不影响信号生成主链路）
    try:
        signal_tracker.ensure_schema()
    except Exception as e:
        logger.error(f"初始化信号跟踪表失败，复盘统计不可用: {e}")
    try:
        workshop.ensure_schema()
    except Exception as e:
        logger.error(f"初始化策略工坊表失败，个人策略不可用: {e}")
    yield
    rmq.close()
    redis_mgr.close()


app = FastAPI(title="策略引擎服务", version="1.1.0", lifespan=lifespan)

# 盘感训练（个股K线盲盒回放），路由见 app/stock_sense.py
app.include_router(stock_sense_router)

# 默认策略配置 - 均衡参数
DEFAULT_CONFIGS = {
    StrategyType.AGGRESSIVE: StrategyConfig(
        id=1, strategy_type=StrategyType.AGGRESSIVE, name="激进轮动策略",
        params=StrategyParams(top_n=2, max_position=1.0, hold_days=10, capital_pct=0.7, stop_loss=0.08, commission_rate=0.0003, stamp_tax_rate=0.001, slippage_rate=0.001, min_score_threshold=1.5, score_gap_threshold=2.0, relative_score_gap_ratio=0.12, cooldown_days=6, keep_overlap=True, allow_empty=True, min_score_keep=2.5, market_bear_threshold=0.40, favorable_confirm_days=1,
            stop_loss_mode="trend_break", trend_confirm=True, trend_ma_days=60, ma_stop_loss=0.08),
    ),
    StrategyType.MODERATE: StrategyConfig(
        id=2, strategy_type=StrategyType.MODERATE, name="稳健轮动策略",
        params=StrategyParams(top_n=3, max_position=0.5, hold_days=5, capital_pct=0.6, stop_loss=0.10, commission_rate=0.0003, stamp_tax_rate=0.001, slippage_rate=0.001, min_score_threshold=2.0, score_gap_threshold=1.0, cooldown_days=2, keep_overlap=True, allow_empty=True, min_score_keep=3.0,
            stop_loss_mode="trend_break", trend_confirm=True, trend_ma_days=60, ma_stop_loss=0.08),
    ),
    StrategyType.CONSERVATIVE: StrategyConfig(
        id=3, strategy_type=StrategyType.CONSERVATIVE, name="保守轮动策略",
        params=StrategyParams(top_n=3, max_position=0.3, hold_days=10, capital_pct=0.6, stop_loss=0.08, valuation_pct_max=50, commission_rate=0.0003, stamp_tax_rate=0.001, slippage_rate=0.001, min_score_threshold=2.0, score_gap_threshold=1.0, cooldown_days=3, keep_overlap=True, allow_empty=True, min_score_keep=3.0,
            stop_loss_mode="trend_break", trend_confirm=True, trend_ma_days=60, ma_stop_loss=0.05),
    ),
}

# 出厂默认配置快照：供"恢复默认"使用，避免运行期配置被 Redis/接口修改后原始值丢失
DEFAULT_CONFIG_TEMPLATES = {
    st: cfg.model_copy(deep=True) for st, cfg in DEFAULT_CONFIGS.items()
}

# 用户维度策略配置：user:{id}:strategy_configs
# 进程内缓存按 user_id 分开，且每个用户拿到的是独立深拷贝 —— 早期实现直接原地
# 修改模块级 DEFAULT_CONFIGS，任何用户改参数都会改写全站配置
_CONFIGS_CACHE: dict[int, dict[StrategyType, StrategyConfig]] = {}
_CONFIGS_LOCK = threading.Lock()


def _default_configs() -> dict[StrategyType, StrategyConfig]:
    """返回一份全新的出厂配置（深拷贝，可安全修改）"""
    return {st: cfg.model_copy(deep=True) for st, cfg in DEFAULT_CONFIG_TEMPLATES.items()}


def _configs_key(user_id: int) -> str:
    return _ukey(user_id, "strategy_configs")


def publish_message(routing_key: str, message: dict):
    """发送消息到RabbitMQ（使用共享连接管理器）"""
    rmq.publish(routing_key, message)


@app.get("/health")
def health_check():
    checks = {}
    # InfluxDB
    try:
        checks["influxdb"] = influx_query.health_check()
    except Exception as e:
        checks["influxdb"] = {"status": "fail", "message": str(e)}
    # Redis
    try:
        redis_mgr._client.ping()
        checks["redis"] = {"status": "pass"}
    except Exception as e:
        checks["redis"] = {"status": "fail", "message": str(e)}
    # RabbitMQ
    try:
        rmq_ok = rmq._connection and rmq._connection.is_open
        checks["rabbitmq"] = {"status": "pass" if rmq_ok else "fail"}
    except Exception as e:
        checks["rabbitmq"] = {"status": "fail", "message": str(e)}

    all_ok = all(c.get("status") == "pass" for c in checks.values())
    return {
        "status": "healthy" if all_ok else "degraded",
        "service": "strategy",
        "checks": checks,
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/trade-day/check")
def check_trade_day(date: str = None):
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

# A 股法定节假日（休市日）——按年度维护，逐年追加即可
_HOLIDAYS_BY_YEAR: dict[int, set[str]] = {
    2025: {
        # 元旦
        "20250101",
        # 春节
        "20250128", "20250129", "20250130", "20250131", "20250201", "20250202", "20250203", "20250204",
        # 清明节
        "20250404", "20250405", "20250406",
        # 劳动节
        "20250501", "20250502", "20250503", "20250504", "20250505",
        # 端午节
        "20250531", "20250601", "20250602",
        # 中秋+国庆
        "20251001", "20251002", "20251003", "20251004", "20251005", "20251006", "20251007", "20251008",
    },
    2026: {
        # 元旦
        "20260101", "20260102", "20260103",
        # 春节
        "20260215", "20260216", "20260217", "20260218", "20260219", "20260220", "20260221",
        # 清明节
        "20260404", "20260405", "20260406",
        # 劳动节
        "20260501", "20260502", "20260503", "20260504", "20260505",
        # 端午节
        "20260619", "20260620", "20260621",
        # 中秋节
        "20260925", "20260926", "20260927",
        # 国庆节
        "20261001", "20261002", "20261003", "20261004", "20261005", "20261006", "20261007",
    },
    2027: {
        # 元旦
        "20270101", "20270102", "20270103",
        # 春节（预估，以证监会公告为准）
        "20270206", "20270207", "20270208", "20270209", "20270210", "20270211", "20270212",
        # 清明节
        "20270403", "20270404", "20270405",
        # 劳动节
        "20270501", "20270502", "20270503",
        # 端午节
        "20270609", "20270610", "20270611",
        # 中秋节
        "20270915", "20270916", "20270917",
        # 国庆节
        "20271001", "20271002", "20271003", "20271004", "20271005", "20271006", "20271007",
    },
}


def _get_holidays_for_year(year: int) -> set[str]:
    """获取指定年份的节假日集合，未维护的年份返回空集合"""
    return _HOLIDAYS_BY_YEAR.get(year, set())


def _is_trade_day(date_str: str) -> bool:
    """检查是否为交易日

    判断逻辑：
    1. 周末（周六、周日）不是交易日
    2. 法定节假日不是交易日
    """
    try:
        d = datetime.strptime(date_str.replace("-", ""), "%Y%m%d")
    except ValueError:
        return False

    # 周末不是交易日
    if d.weekday() >= 5:
        return False

    # 法定节假日不是交易日
    date_compact = d.strftime("%Y%m%d")
    if date_compact in _get_holidays_for_year(d.year):
        return False

    return True


# 板块日快照缓存 TTL（秒）。按数据日期分键存储，杜绝跨交易日复用。
SECTOR_SNAPSHOT_TTL = 3600
# 允许回退时，最多向前查找多少个自然日内的有效板块数据
STALE_LOOKBACK_DAYS = 30
# 信号缓存 TTL（7天）：与持仓周期对齐，保证历史信号可追溯、可回看
SIGNAL_CACHE_TTL = 86400 * 7
# /signals/today 在今日无信号时，向前回看多少天
SIGNAL_LOOKBACK_DAYS = 7
# 市场状态（BULL/NEUTRAL/BEAR）保留天数，用于跨交易日连续确认
REGIME_TTL = 86400 * 30
REGIME_HISTORY_DAYS = 10


def _snapshot_cache_key(date_str: str) -> str:
    """板块日快照缓存键（按数据日期分键）"""
    return f"sector_capital_flow:{date_str}"


def _load_sector_snapshot(target_date: str, force_refresh: bool = False) -> list:
    """按精确日期加载板块快照：Redis → InfluxDB。

    只返回 target_date 当天的数据，绝不回退到其它日期；当天无数据时返回空列表，
    由调用方决定是拒绝生成信号，还是改用最近有数据的交易日（并同步修正信号日期）。

    Args:
        force_refresh: 为 True 时跳过 Redis 缓存直接回源 InfluxDB，并用回源结果覆盖
            缓存。信号计算必须走此路径——快照缓存 TTL 为 1 小时，若当日采集入库前
            已缓存过旧值（例如旧口径的估值分位），命中缓存会让评分与 AI 解读
            （后者直查 InfluxDB）在同一分钟拿到两套不同的数据，导致保守档估值
            筛选失真。
    """
    cache_key = _snapshot_cache_key(target_date)
    cached = None if force_refresh else redis_mgr.get(cache_key)
    if cached:
        try:
            rows = json.loads(cached)
            if rows:
                logger.info(f"从Redis获取到 {len(rows)} 条板块数据（日期: {target_date}）")
                return rows
        except (json.JSONDecodeError, TypeError):
            logger.warning(f"板块缓存解析失败，回源InfluxDB: {cache_key}")

    try:
        daily_data = influx_query.query_daily_sectors(target_date, target_date) or {}
        rows = daily_data.get(target_date) or []
        if rows:
            redis_mgr.setex(cache_key, SECTOR_SNAPSHOT_TTL, json.dumps(rows, ensure_ascii=False))
            logger.info(f"从InfluxDB获取到 {len(rows)} 条板块数据（日期: {target_date}）")
        else:
            logger.info(f"InfluxDB中无 {target_date} 的板块数据")
        return rows
    except Exception as e:
        logger.error(f"从InfluxDB读取 {target_date} 板块数据失败: {e}")
        return []


def _regime_key(strategy_type: StrategyType, date_str: str, user_id: int = ADMIN_USER_ID) -> str:
    """市场状态缓存键（按账号+策略+日期，供连续确认 BEAR 使用）

    市场状态虽由行情推导，但强依赖各账号自己的参数（熊市阈值），
    因此不能共享一份，否则乙账号会拿甲账号的 BEAR 判定做连续确认。
    """
    return _ukey(user_id, f"market_regime:{strategy_type.value}:{date_str}")


def _load_regime_history(
    strategy_type: StrategyType, before_date: str,
    user_id: int = ADMIN_USER_ID, days: int = REGIME_HISTORY_DAYS,
) -> list:
    """读取 before_date 之前的市场状态序列（升序，元素为 BULL/NEUTRAL/BEAR）"""
    collected = []
    try:
        for offset in range(1, days + 1):
            d = (
                datetime.strptime(before_date, "%Y-%m-%d") - timedelta(days=offset)
            ).strftime("%Y-%m-%d")
            value = redis_mgr.get(_regime_key(strategy_type, d, user_id))
            if value:
                collected.append(value)
    except Exception as e:
        logger.warning(f"读取市场状态历史失败: {e}")
    collected.reverse()  # 由近及远采集，反转后为时间升序
    return collected


def _save_regime(
    strategy_type: StrategyType, date_str: str, regime: str,
    user_id: int = ADMIN_USER_ID,
) -> None:
    """记录当日市场状态，供后续交易日做连续确认"""
    try:
        redis_mgr.setex(_regime_key(strategy_type, date_str, user_id), REGIME_TTL, regime)
    except Exception as e:
        logger.warning(f"保存市场状态失败: {e}")


def _find_latest_available_date(before_date: str, lookback_days: int = STALE_LOOKBACK_DAYS) -> str:
    """查找不晚于 before_date 且存在板块数据的最近日期，找不到返回空串"""
    try:
        start_date = (
            datetime.strptime(before_date, "%Y-%m-%d") - timedelta(days=lookback_days)
        ).strftime("%Y-%m-%d")
        daily_data = influx_query.query_daily_sectors(start_date, before_date) or {}
        candidates = [d for d, rows in daily_data.items() if rows and d <= before_date]
        return max(candidates) if candidates else ""
    except Exception as e:
        logger.error(f"查找 {before_date} 之前可用数据日期失败: {e}")
        return ""


def _no_data_response(strategy_type: StrategyType, requested_date: str, message: str) -> dict:
    """数据未就绪的统一响应：不生成信号、不动持仓、不推送"""
    return {
        "code": 200,
        "message": message,
        "data": [],
        "strategy_type": strategy_type.value,
        "signal_date": requested_date,
        "data_ready": False,
        "stale": False,
    }


def _load_previous_clear_signals(
    strategy_type: str, signal_date: str, user_id: int = ADMIN_USER_ID,
) -> list:
    """读取该账号当日已缓存的"清仓"卖出信号（direction=SELL 且理由含"清仓"）。

    用于重算得到空仓时保留清仓留痕，避免被空列表覆盖。
    """
    try:
        raw = redis_mgr.get(_ukey(user_id, f"signals:{strategy_type}:{signal_date}"))
        if not raw:
            return []
        return [
            s for s in (json.loads(raw) or [])
            if s.get("direction") == "SELL" and "清仓" in str(s.get("reason") or "")
        ]
    except (json.JSONDecodeError, TypeError) as e:
        logger.warning(f"读取历史清仓记录失败（{strategy_type} {signal_date}）: {e}")
        return []


def _merge_clear_records(signal_dicts: list, signals: list, previous_clears: list):
    """空仓重算时保留历史清仓记录。

    仅当本次计算完全没有信号（空仓）、且该日历史缓存中存在清仓记录时，
    才用历史清仓记录替换本次的空列表；否则沿用本次计算结果。
    返回 (最终写入缓存的信号列表, 是否发生了保留)。
    """
    if signals or not previous_clears:
        return signal_dicts, False
    return previous_clears, True


@app.post("/calculate")
async def calculate_signals(
    strategy_type: StrategyType,
    signal_date: str = None,
    allow_stale: bool = False,
    force: bool = False,
    authorization: str | None = Header(None, alias="Authorization"),
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    """触发当前账号的策略计算，生成买卖信号。

    核心约束：信号日期必须与所用板块数据的日期严格一致，禁止用 T-1 数据生成 T 日信号。

    Args:
        strategy_type: 策略类型
        signal_date: 期望的信号日期，默认今天
        allow_stale: 目标日期无数据（含周末/节假日手动触发、数据尚未采集入库）时，
            是否允许回退到最近有数据的交易日。回退时信号日期会一并修正为该交易日，
            保证"信号日期 == 数据日期"；为 False 时直接拒绝生成信号。
        force: 回退场景下若该日期已有信号，是否强制重算（默认直接返回已有信号，
            避免手动/登录重复触发覆盖当日持仓）
    """
    actor = _resolve_actor(authorization, x_internal_token)
    return await _calculate_for_user(
        actor.user_id, strategy_type, signal_date, allow_stale, force,
    )


@app.post("/calculate/all")
async def calculate_all_users(
    signal_date: str = None,
    allow_stale: bool = True,
    authorization: str | None = Header(None, alias="Authorization"),
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    """为所有启用账号各算一套信号（调度器每日调用）

    每个账号使用自己的策略参数、自己的持仓与 regime 历史，结果写入各自的
    Redis 键并各自推送。行情快照与历史 K 线在同一次批处理里只加载一遍，
    避免 N 个账号重复打 InfluxDB。
    """
    actor = _resolve_actor(authorization, x_internal_token)
    if actor.role != "ADMIN":
        raise HTTPException(status_code=403, detail="仅管理员或内部调度可批量计算")

    user_ids = await asyncio.to_thread(_active_user_ids)
    if not user_ids:
        user_ids = [ADMIN_USER_ID]

    shared: dict = {}
    results = []
    for uid in user_ids:
        for st in StrategyType:
            try:
                r = await _calculate_for_user(uid, st, signal_date, allow_stale, False, shared)
                results.append({
                    "user_id": uid,
                    "strategy_type": st.value,
                    "signal_date": r.get("signal_date"),
                    "count": len(r.get("data") or []),
                    "data_ready": r.get("data_ready", True),
                })
            except Exception as e:
                logger.error(f"批量计算失败: user={uid}, {st.value}: {e}")
                results.append({
                    "user_id": uid, "strategy_type": st.value,
                    "error": str(e),
                })
    logger.info(f"批量信号计算完成: {len(user_ids)} 个账号, {len(results)} 次计算")
    return {"code": 200, "data": results, "users": user_ids}


@app.post("/internal/users/{user_id}/purge")
async def purge_user_data(
    user_id: int,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    """清理已删除账号的全部个人数据（仅服务间调用）

    账号被删除后其 id 会被再次分配——库还原、序列回退、甚至同名重建都可能触发，
    而 Redis 的 user:{id}: 键与 signal_outcomes / trade_signals 里的行都还挂着旧账号
    的数据，新账号一登录就能看到别人的训练记录、信号缓存和市场状态。所以 auth 删除
    账号前必须先调这里清干净，清理失败就不允许删号。
    """
    if not settings.internal_token or x_internal_token != settings.internal_token:
        raise HTTPException(status_code=401, detail="缺少内部凭证")
    if int(user_id) <= 0:
        raise HTTPException(status_code=400, detail="用户 ID 非法")
    try:
        redis_deleted = await asyncio.to_thread(_purge_user_redis, int(user_id))
        pg_rows = await asyncio.to_thread(signal_tracker.purge_user_rows, int(user_id))
        pg_rows += await asyncio.to_thread(workshop.purge_user_rows, int(user_id))
    except Exception as e:
        logger.error(f"清理账号数据失败: user={user_id}, {e}")
        raise HTTPException(status_code=500, detail=f"清理账号数据失败: {e}")
    logger.info(f"账号数据已清理: user={user_id} redis_keys={redis_deleted} pg_rows={pg_rows}")
    return {"code": 200, "data": {"redis_keys": redis_deleted, "pg_rows": pg_rows}}


def _purge_user_redis(user_id: int) -> int:
    """删除该账号在 Redis 中的全部个人数据，返回删除的键数

    RedisManager.delete 失败时只返回 0 而不抛异常，这里每轮删完再扫一次确认，
    三轮还有残留就报错——宁可删号失败，也不能让下一个账号继承旧数据。
    """
    pattern = f"{user_scope(user_id)}:*"
    deleted = 0
    for _ in range(3):
        batch: list[str] = []
        for key in redis_mgr.scan_iter(match=pattern, count=200):
            batch.append(key)
            if len(batch) >= 200:
                deleted += redis_mgr.delete(*batch)
                batch.clear()
        if batch:
            deleted += redis_mgr.delete(*batch)
        if next(iter(redis_mgr.scan_iter(match=pattern, count=10)), None) is None:
            break
    else:
        raise RuntimeError(f"账号 {user_id} 的 Redis 个人数据未清理干净")
    with _CONFIGS_LOCK:
        _CONFIGS_CACHE.pop(user_id, None)
    return int(deleted or 0)


def _active_user_ids() -> list[int]:
    """读取启用状态的账号列表（PG 故障时回退为仅管理员）"""
    try:
        from .signal_tracker import _connect

        conn = _connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM users WHERE status = 'ACTIVE' ORDER BY id"
                )
                rows = [int(r[0]) for r in cur.fetchall()]
            return rows or [ADMIN_USER_ID]
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"读取账号列表失败，退化为仅计算管理员: {e}")
        return [ADMIN_USER_ID]


async def _calculate_for_user(
    user_id: int,
    strategy_type: StrategyType,
    signal_date: str = None,
    allow_stale: bool = False,
    force: bool = False,
    shared: dict | None = None,
) -> dict:
    """单个账号的策略计算流程

    shared 用于批处理时复用当日行情快照（同一交易日所有账号口径一致）。
    """
    scope = user_scope(user_id)
    try:
        requested_date = signal_date or datetime.now().strftime("%Y-%m-%d")
        effective_date = requested_date
        is_stale = False
        note = ""

        config = _user_configs(user_id).get(strategy_type)
        if not config:
            raise HTTPException(status_code=400, detail=f"未知策略类型: {strategy_type}")

        # 只取目标日期当天的板块数据，不做任何隐式回退
        if _is_trade_day(requested_date):
            if shared is not None and requested_date in shared:
                sector_data = shared[requested_date]
            else:
                sector_data = _load_sector_snapshot(requested_date, force_refresh=True)
                if shared is not None:
                    shared[requested_date] = sector_data
        else:
            sector_data = []

        if not sector_data:
            if not allow_stale:
                reason = "非交易日" if not _is_trade_day(requested_date) else "当日板块数据尚未入库"
                logger.info(f"{requested_date} {reason}，跳过策略计算（allow_stale=False）")
                return _no_data_response(
                    strategy_type, requested_date, f"{requested_date} {reason}，不生成信号"
                )

            # 手动触发场景：回退到最近有数据的交易日，并把信号日期一并修正
            fallback_date = _find_latest_available_date(requested_date)
            if not fallback_date:
                logger.warning(f"{requested_date} 及此前 {STALE_LOOKBACK_DAYS} 天均无板块数据，无法计算")
                return _no_data_response(
                    strategy_type, requested_date,
                    f"{requested_date} 及此前 {STALE_LOOKBACK_DAYS} 天均无板块数据，不生成信号",
                )

            effective_date = fallback_date
            is_stale = True
            note = f"{requested_date} 无板块数据，已回退到最近有数据的交易日 {fallback_date}"
            logger.info(note)

            # 历史日期已有信号时默认不重算，避免重复触发覆盖当日持仓
            cached_signals = redis_mgr.get(f"{scope}:signals:{strategy_type.value}:{effective_date}")
            if cached_signals and not force:
                try:
                    existing = json.loads(cached_signals)
                except (json.JSONDecodeError, TypeError):
                    existing = None
                if existing is not None:
                    logger.info(f"{effective_date} 信号已存在，直接返回（force=False）")
                    return {
                        "code": 200,
                        "message": f"{effective_date} 信号已存在，未重复计算",
                        "data": existing,
                        "strategy_type": strategy_type.value,
                        "signal_date": effective_date,
                        "requested_date": requested_date,
                        "data_ready": True,
                        "stale": True,
                        "note": note,
                    }

            sector_data = _load_sector_snapshot(effective_date, force_refresh=True)
            if not sector_data:
                logger.error(f"回退日期 {effective_date} 仍无板块数据，放弃计算")
                return _no_data_response(
                    strategy_type, requested_date, f"回退日期 {effective_date} 无板块数据，不生成信号"
                )

        # 从Redis读取当前持仓
        current_positions = {}
        try:
            positions_raw = redis_mgr.get(f"{scope}:positions:{strategy_type.value}")
            if positions_raw:
                current_positions = json.loads(positions_raw)
                logger.info(f"读取到当前持仓: {len(current_positions)}个板块")
        except Exception as e:
            # 持仓损坏会导致后续按"空仓"处理（跳过调仓缺口、清仓信号丢失），必须显眼告警
            logger.error(f"读取持仓失败，本次按空仓处理，请检查 {scope}:positions:{strategy_type.value}: {e}")
            current_positions = {}

        # 为单日快照补充板块历史K线/资金流序列。
        # 走势/技术类因子（ma_trend/mfi/vol_ratio等）依赖板块 _history，
        # 若仅用当日快照将导致该类因子置信度为0被剔除，单日信号将无法结合走势与技术指标。
        try:
            if sector_data:
                from bisect import bisect_right
                # 历史序列一律以生效信号日期为界，避免截断到未来或混入 T 日之后的走势
                snapshot_date = effective_date
                item_dates = [str(s.get("date", ""))[:10] for s in sector_data if s.get("date")]
                if item_dates:
                    data_date = max(item_dates)
                    if data_date != effective_date:
                        logger.warning(
                            f"板块数据自带日期 {data_date} 与信号日期 {effective_date} 不一致，以信号日期为准"
                        )
                _hist = _load_sector_history_cache([snapshot_date])
                _attached = 0
                for _s in sector_data:
                    _code = _s.get("sector_code")
                    _rows = _hist.get(_code) if _code else None
                    if not _rows:
                        continue
                    _dates = [r.get("date", "") for r in _rows]
                    _s["_history"] = _rows[:bisect_right(_dates, snapshot_date)]
                    if not _s.get("date"):
                        _s["date"] = snapshot_date
                    _attached += 1
                logger.info(f"已为 {_attached} 条板块补充历史序列（截至 {snapshot_date}），走势/技术因子可用")
        except Exception as e:
            logger.warning(f"补充板块历史序列失败（信号仍可生成，但缺少走势/技术维度）: {e}")

        diagnostics: dict = {}
        regime_history = _load_regime_history(strategy_type, effective_date, user_id)
        signals = scoring_model.calculate_daily_signals(
            sector_data=sector_data,
            strategy_type=strategy_type,
            params=config.params,
            signal_date=effective_date,
            current_positions=current_positions,
            regime_history=regime_history,
            diagnostics=diagnostics,
        )

        # 记录当日市场状态，供后续交易日做连续确认（BEAR 连续确认后才清仓）
        if diagnostics.get("market_regime"):
            _save_regime(strategy_type, effective_date, diagnostics["market_regime"], user_id)

        # 填充 id 和 created_at
        now = datetime.now().isoformat()
        for idx, s in enumerate(signals, 1):
            s.id = idx
            s.created_at = now

        # 扩展信号带价：实盘信号生成时填充 ETF 最新价，供 fund-management 开仓计算数量。
        # 价格统一由 data-collector 采集落库（与收盘盯市同源），此处只查询，不直连数据源。
        # 仅当 effective_date 为今日时填充，避免历史重算/回测路径引入未来函数。
        if effective_date == datetime.now().strftime("%Y-%m-%d"):
            try:
                import httpx

                with httpx.Client(timeout=30) as client:
                    resp = client.get(
                        f"{settings.data_collector_url}/query/etf-prices",
                        params={"date": effective_date},
                    )
                    price_map = resp.json().get("data") or {}
                for s in signals:
                    if s.etf_code and s.etf_code in price_map:
                        s.current_price = float(price_map[s.etf_code])
                if not price_map and signals:
                    # 明确告警：无价信号会被 fund 拒绝开仓，避免误以为是"无信号"
                    logger.warning(
                        f"当日({effective_date}) ETF 收盘价缺失，信号不带价；"
                        f"fund 将因价格非正拒绝开仓（不会静默成交）"
                    )
            except Exception as e:
                logger.warning(f"补充信号 ETF 价格失败（不影响信号生成）: {e}")

        # 缓存信号到Redis
        signal_dicts = [s.model_dump() for s in signals]

        # 更新持仓到Redis（仅在确实产生买卖信号时）。
        # 未产生信号意味着"维持现有持仓"（评分差距不足/市场不景气保持空仓），
        # 此时绝不能用空仓位覆盖，否则真实持仓会被凭空清零、次日被误判为建仓。
        buy_signals = [s for s in signals if s.direction.value == "BUY"]
        sell_signals = [s for s in signals if s.direction.value == "SELL"]
        if buy_signals or sell_signals:
            new_positions = {s.sector_code: s.position_ratio for s in buy_signals}
            for code in [s.sector_code for s in sell_signals]:
                new_positions.pop(code, None)
            redis_mgr.setex(
                f"{scope}:positions:{strategy_type.value}", 86400 * 7,
                json.dumps(new_positions, ensure_ascii=False),
            )
            logger.info(
                f"更新持仓到Redis: {len(new_positions)}个板块 "
                f"(买入{len(buy_signals)}/卖出{len(sell_signals)})"
            )
        else:
            logger.info(f"本次未产生买卖信号，保持现有持仓不变（{len(current_positions)}个板块）")

        # 持仓状态：空仓必须被明确表达，而不是"什么都不返回"
        regime = diagnostics.get("market_regime", "")
        breadth_detail = diagnostics.get("breadth_detail", "")
        if buy_signals:
            position_status = "HOLD"
            empty_reason = ""
        elif sell_signals:
            position_status = "EMPTY"
            empty_reason = f"市场转弱触发清仓（{breadth_detail}）" if breadth_detail else "市场转弱触发清仓"
        elif current_positions:
            position_status = "HOLD"
            empty_reason = ""
        else:
            position_status = "EMPTY"
            if regime == "BEAR":
                empty_reason = f"市场判定熊市，空仓观望（{breadth_detail}）"
            else:
                empty_reason = (
                    f"无板块满足买入条件（{breadth_detail}）" if breadth_detail
                    else "无板块满足买入条件"
                )

        if position_status == "EMPTY":
            logger.info(f"{strategy_type.value} {effective_date} 空仓: {empty_reason}")

        # 写缓存前保留已发生的"清仓"留痕：
        # 清仓是已执行的历史事实，一旦某日产生过清仓卖出信号，后续重算若因市场转平
        # 得到"无信号"，不能用空列表覆盖掉清仓记录，否则日历与推送会丢失"当日已清仓"的证据。
        if not signals:
            previous_clears = _load_previous_clear_signals(
                strategy_type.value, effective_date, user_id
            )
            signal_dicts, preserved = _merge_clear_records(
                signal_dicts, signals, previous_clears
            )
            if preserved:
                position_status = "EMPTY"
                empty_reason = previous_clears[0].get("reason") or empty_reason
                logger.info(
                    f"保留 {len(previous_clears)} 条历史清仓记录，避免空仓重算覆盖"
                    f"（{strategy_type.value} {effective_date}）"
                )

        redis_mgr.setex(
            f"{scope}:signals:{strategy_type.value}:{effective_date}",
            SIGNAL_CACHE_TTL, json.dumps(signal_dicts, ensure_ascii=False),
        )
        # 持仓状态与空仓原因一并缓存，供"今日信号"接口表达空仓语义
        redis_mgr.setex(
            f"{scope}:signals:{strategy_type.value}:{effective_date}:status",
            SIGNAL_CACHE_TTL,
            json.dumps(
                {
                    "position_status": position_status,
                    "market_regime": regime,
                    "empty_reason": empty_reason,
                    "signal_date": effective_date,
                },
                ensure_ascii=False,
            ),
        )

        # 落库供长期复盘统计：信号缓存只有 7 天 TTL，过期后无法统计准确率。
        # PG 异常不能让信号生成失败，这里降级处理。
        try:
            await asyncio.to_thread(
                signal_tracker.save_signals,
                user_id, strategy_type.value, effective_date, signal_dicts,
            )
        except Exception as e:
            logger.error(f"信号落库失败（不影响信号生成）: {e}")

        # 通知信号服务：user_id 决定这条信号推给谁，避免把甲账号的信号推给乙
        publish_message("signal.generated", {
            "event": "signals_generated",
            "user_id": user_id,
            "strategy_type": strategy_type.value,
            "signal_date": effective_date,
            "requested_date": requested_date,
            "count": len(signal_dicts),
            "position_status": position_status,
            "empty_reason": empty_reason,
            "signals": signal_dicts,
            "timestamp": datetime.now().isoformat(),
        })

        message = (
            f"策略计算完成：{position_status}，{empty_reason}"
            if position_status == "EMPTY"
            else f"策略计算完成，共生成 {len(signal_dicts)} 条信号"
        )
        if note:
            message = f"{message}；{note}"
        return {
            "code": 200,
            "message": message,
            "data": signal_dicts,
            "strategy_type": strategy_type.value,
            "signal_date": effective_date,
            "requested_date": requested_date,
            "data_ready": True,
            "stale": is_stale,
            "note": note,
            "position_status": position_status,
            "market_regime": regime,
            "empty_reason": empty_reason,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"策略计算失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _load_configs_from_redis(user_id: int) -> dict[StrategyType, StrategyConfig]:
    """加载指定用户的策略配置，缺失项回落到出厂默认值"""
    configs = _default_configs()
    try:
        raw = redis_mgr.get(_configs_key(user_id))
        if raw:
            saved = json.loads(raw)
            for st, cfg in configs.items():
                if st.value in saved:
                    saved_cfg = saved[st.value]
                    cfg.name = saved_cfg.get("name", cfg.name)
                    cfg.is_active = saved_cfg.get("is_active", cfg.is_active)
                    if "params" in saved_cfg:
                        cfg.params = StrategyParams(**saved_cfg["params"])
            logger.info(f"从Redis加载策略配置成功: user={user_id}")
    except Exception as e:
        logger.warning(f"从Redis加载策略配置失败，使用默认值: user={user_id}, {e}")
    return configs


def _migrate_legacy_configs() -> None:
    """历史全局策略配置归并到管理员账号（幂等）

    改造前所有用户共用 strategy_configs 单键。这里搬到 user:1 名下，
    让管理员保留原有参数，其他用户从出厂默认值起步。
    """
    try:
        legacy = redis_mgr.get("strategy_configs")
        if legacy is None:
            return
        target = _configs_key(ADMIN_USER_ID)
        if redis_mgr.get(target) is None:
            redis_mgr.set(target, legacy)
            logger.info(f"历史全局策略配置已归并到管理员账号: strategy_configs -> {target}")
        redis_mgr.delete("strategy_configs")
    except Exception as e:
        logger.warning(f"历史策略配置迁移跳过: {e}")


def _user_configs(user_id: int) -> dict[StrategyType, StrategyConfig]:
    """取用户策略配置（进程内缓存，首次访问从 Redis 加载）"""
    with _CONFIGS_LOCK:
        cached = _CONFIGS_CACHE.get(user_id)
    if cached is not None:
        return cached
    configs = _load_configs_from_redis(user_id)
    with _CONFIGS_LOCK:
        _CONFIGS_CACHE[user_id] = configs
    return configs


def _save_configs_to_redis(user_id: int) -> None:
    """将指定用户的策略配置写入 Redis"""
    try:
        data = {}
        for st, cfg in _user_configs(user_id).items():
            data[st.value] = {
                "name": cfg.name,
                "is_active": cfg.is_active,
                "params": cfg.params.model_dump(),
            }
        redis_mgr.set(_configs_key(user_id), json.dumps(data, ensure_ascii=False))
        logger.info(f"策略配置已保存到Redis: user={user_id}")
    except Exception as e:
        logger.error(f"保存策略配置到Redis失败: user={user_id}, {e}")


@app.get("/configs")
def get_configs(
    authorization: str | None = Header(None, alias="Authorization"),
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    """获取当前账号的策略配置"""
    actor = _resolve_actor(authorization, x_internal_token)
    configs = []
    for cfg in _user_configs(actor.user_id).values():
        c = cfg.model_dump()
        c["params"] = cfg.params.model_dump()
        configs.append(c)
    return {"code": 200, "data": configs}


@app.put("/configs/{config_id}")
def update_config(
    config_id: int,
    config: StrategyConfig,
    authorization: str | None = Header(None, alias="Authorization"),
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    """更新当前账号的策略配置

    注意: 前端仅提交部分参数（如 top_n/hold_days/stop_loss 等），
    未提交的参数必须保留原值，否则会退化为 StrategyParams 的默认值，
    导致调仓阈值/止损模式/仓位比例等关键参数被意外重置。
    """
    actor = _resolve_actor(authorization, x_internal_token)
    for st, cfg in _user_configs(actor.user_id).items():
        if cfg.id == config_id:
            if config.model_fields_set:
                if "name" in config.model_fields_set and config.name:
                    cfg.name = config.name
                if "is_active" in config.model_fields_set:
                    cfg.is_active = config.is_active
            if config.params is not None:
                incoming = config.params.model_dump(exclude_unset=True)
                if incoming:
                    cfg.params = cfg.params.model_copy(update=incoming)
            _save_configs_to_redis(actor.user_id)
            return {"code": 200, "message": "配置更新成功", "data": cfg.model_dump()}
    raise HTTPException(status_code=404, detail="配置不存在")


@app.post("/configs/{config_id}/reset")
def reset_config(
    config_id: int,
    authorization: str | None = Header(None, alias="Authorization"),
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    """将指定策略恢复为出厂默认值（仅影响当前账号）"""
    actor = _resolve_actor(authorization, x_internal_token)
    configs = _user_configs(actor.user_id)
    for st, tmpl in DEFAULT_CONFIG_TEMPLATES.items():
        if tmpl.id == config_id:
            cfg = configs[st]
            cfg.name = tmpl.name
            cfg.is_active = tmpl.is_active
            cfg.params = tmpl.params.model_copy(deep=True)
            _save_configs_to_redis(actor.user_id)
            data = cfg.model_dump()
            data["params"] = cfg.params.model_dump()
            return {"code": 200, "message": "配置已恢复默认", "data": data}
    raise HTTPException(status_code=404, detail="配置不存在")


@app.get("/signals/today")
def get_today_signals(
    strategy_type: StrategyType,
    authorization: str | None = Header(None, alias="Authorization"),
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    """获取当前账号的今日信号

    今日无信号时（周末/节假日手动触发生成的信号落在最近交易日），
    自动回退到最近存在信号的日期并返回，响应中标注实际信号日期。
    """
    actor = _resolve_actor(authorization, x_internal_token)
    user_id = actor.user_id

    def _status_of(date_str: str, rows: list, stale: bool) -> dict:
        """组装响应：持仓状态以信号数组为准，缓存仅补充市场状态与空仓原因"""
        # 以实际信号为准，避免缓存状态与信号不一致时给出误导性结论
        position_status = "HOLD" if rows else "EMPTY"
        regime = ""
        reason = ""
        raw_status = redis_mgr.get(_ukey(user_id, f"signals:{strategy_type.value}:{date_str}:status"))
        if raw_status:
            try:
                parsed = json.loads(raw_status)
                regime = parsed.get("market_regime", "")
                if parsed.get("position_status") == position_status:
                    reason = parsed.get("empty_reason", "")
            except (json.JSONDecodeError, TypeError):
                pass
        return {
            "code": 200,
            "data": rows,
            "signal_date": date_str,
            "stale": stale,
            "position_status": position_status,
            "market_regime": regime,
            "empty_reason": reason,
        }

    today = datetime.now().strftime("%Y-%m-%d")
    cached = redis_mgr.get(_ukey(user_id, f"signals:{strategy_type.value}:{today}"))
    if cached:
        return _status_of(today, json.loads(cached), False)

    for offset in range(1, SIGNAL_LOOKBACK_DAYS + 1):
        fallback = (
            datetime.strptime(today, "%Y-%m-%d") - timedelta(days=offset)
        ).strftime("%Y-%m-%d")
        cached = redis_mgr.get(_ukey(user_id, f"signals:{strategy_type.value}:{fallback}"))
        if cached:
            logger.info(f"今日无信号，回退返回 {fallback} 的信号: user={user_id}")
            return _status_of(fallback, json.loads(cached), True)

    # 无任何信号缓存：区分于"已计算且空仓"
    return {
        "code": 200, "data": [], "signal_date": today, "stale": False,
        "position_status": "NO_DATA", "market_regime": "", "empty_reason": "",
    }


@app.get("/positions")
def get_positions(
    strategy_type: StrategyType,
    authorization: str | None = Header(None, alias="Authorization"),
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    """获取当前账号指定策略的持仓

    持仓由策略计算流程写入 Redis（键 user:{id}:positions:{strategy_type}，TTL 7 天），
    此处仅做只读暴露，供 AI 决策复盘与前端查询。
    """
    actor = _resolve_actor(authorization, x_internal_token)
    key = _ukey(actor.user_id, f"positions:{strategy_type.value}")
    try:
        raw = redis_mgr.get(key)
    except Exception as e:
        logger.error(f"读取持仓失败: {key}: {e}")
        raise HTTPException(status_code=503, detail="持仓读取失败")

    positions = {}
    if raw:
        try:
            positions = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            logger.error(f"持仓数据解析失败: positions:{strategy_type.value}")
            positions = {}

    return success_response(data={
        "positions": positions,
        "total_weight": round(sum(_safe_num(w) for w in positions.values()), 4),
        "count": len(positions),
    })


@app.get("/signals/calendar")
def get_signal_calendar(
    strategy_type: StrategyType,
    month: str = None,
    authorization: str | None = Header(None, alias="Authorization"),
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    """获取当前账号的信号日历数据"""
    actor = _resolve_actor(authorization, x_internal_token)
    scope = user_scope(actor.user_id)
    try:
        if month is None:
            month = datetime.now().strftime("%Y-%m")

        year, mon = int(month[:4]), int(month[5:7])
        last_day = calendar.monthrange(year, mon)[1]

        pipe = redis_mgr.pipeline()
        status_pipe = redis_mgr.pipeline()
        cache_keys = []
        for day in range(1, last_day + 1):
            date_str = f"{month}-{day:02d}"
            cache_key = f"{scope}:signals:{strategy_type.value}:{date_str}"
            cache_keys.append(date_str)
            pipe.get(cache_key)
            status_pipe.get(f"{cache_key}:status")

        signal_caches = pipe.execute()
        status_caches = status_pipe.execute()

        results = []
        for date_str, cached, raw_status in zip(cache_keys, signal_caches, status_caches):
            # 注意：已计算但空仓的日期，信号缓存是空列表 "[]"（键存在）而非不存在，
            # 因此不能用 `if cached:` 判断"是否有信号"，否则空仓标记会被短路而永远不输出。
            try:
                signals = json.loads(cached) if cached else []
            except (json.JSONDecodeError, TypeError):
                signals = []
            if signals:
                for sig in signals:
                    sig["signal_date"] = date_str
                results.extend(signals)
                continue
            if cached is None and not raw_status:
                # 既无信号缓存也无状态缓存 → 未计算/无数据，不输出标记
                continue
            # 已计算但空仓（无持仓信号）：输出标记记录，
            # 使日历能以独立颜色区分"空仓"与"未计算/无数据"
            parsed = {}
            if raw_status:
                try:
                    parsed = json.loads(raw_status) or {}
                except (json.JSONDecodeError, TypeError):
                    parsed = {}
            if parsed.get("position_status", "EMPTY") != "EMPTY":
                continue
            results.append({
                "signal_date": date_str,
                "strategy_type": strategy_type.value,
                "sector_code": "",
                "sector_name": "空仓",
                "direction": "EMPTY",
                "position_ratio": 0.0,
                "score": 0.0,
                "reason": parsed.get("empty_reason") or "当日空仓，无持仓信号",
                "is_empty_position": True,
                "market_regime": parsed.get("market_regime", ""),
            })

        return {"code": 200, "data": results}
    except Exception as e:
        logger.error(f"获取信号日历失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/signals/performance")
async def get_signal_performance(
    strategy_type: StrategyType = StrategyType.MODERATE,
    horizon_days: int = signal_tracker.DEFAULT_HORIZON,
    start_date: str = None,
    end_date: str = None,
    authorization: str | None = Header(None, alias="Authorization"),
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    """策略信号复盘统计：命中率、平均净/毛收益、盈亏比等

    口径见 signal_tracker 模块：T+1 开盘价买入、第 N 个交易日收盘价结算；
    收益已按方向取号（卖出后下跌计为盈利）并扣除往返交易成本；
    尚未走完持有期的信号计入 pending_count，不进入命中率分母。
    """
    actor = _resolve_actor(authorization, x_internal_token)
    try:
        data = await asyncio.to_thread(
            signal_tracker.query_performance,
            strategy_type.value, horizon_days, start_date, end_date, actor.user_id,
        )
        data["horizons"] = list(signal_tracker.HORIZONS)
        return {"code": 200, "data": data}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"获取策略复盘统计失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/signals/sync")
async def sync_signal_cache(
    lookback_days: int = 7,
    all_users: bool = False,
    authorization: str | None = Header(None, alias="Authorization"),
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    """把 Redis 中仍然存活的信号补录到数据库（信号缓存仅 7 天，用于兜底）

    all_users=True 时遍历全部启用账号（调度器使用），否则只补录当前账号。
    """
    actor = _resolve_actor(authorization, x_internal_token)
    try:
        user_id = None if all_users else actor.user_id
        data = await asyncio.to_thread(signal_tracker.sync_from_cache, lookback_days, user_id)
        return {"code": 200, "data": data, "message": "信号缓存补录完成"}
    except Exception as e:
        logger.error(f"补录信号缓存失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/signals/backfill")
async def backfill_signal_outcomes(
    lookback_days: int = signal_tracker.DEFAULT_LOOKBACK_DAYS,
    all_users: bool = False,
    authorization: str | None = Header(None, alias="Authorization"),
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    """回填信号后收益：行情走完持有期后按 T+1 开盘价入场自动评估命中率与净收益

    all_users=True 时遍历全部启用账号（调度器使用），否则只回填当前账号。
    """
    actor = _resolve_actor(authorization, x_internal_token)
    try:
        user_id = None if all_users else actor.user_id
        data = await asyncio.to_thread(signal_tracker.backfill_outcomes, lookback_days, user_id)
        return {"code": 200, "data": data, "message": "信号收益回填完成"}
    except Exception as e:
        logger.error(f"回填信号收益失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 回测执行（同步接口与后台任务共用） ====================

# 回测单次 10~20 秒，走同步 HTTP 时手机切换网络会让浏览器断开连接并重发请求：
# 用户看到「回测失败」，后端却已经算完并写库，重发一次就多出一条重复记录。
# 因此前端改为「提交任务 → 轮询状态」，提交端用参数指纹做幂等，任务状态存 Redis。
_BACKTEST_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="backtest-task")
_BACKTEST_TASK_TTL = 1800   # 任务状态保留 30 分钟，够前端轮询与刷新后查询
_BACKTEST_LOCK_TTL = 900    # 同参数任务锁，任务结束立即释放


def _merge_backtest_params(user_id: int, request: BacktestRequest) -> StrategyParams:
    """回测参数采用“当前策略配置 + 请求覆盖字段”合并：
    前端仅提交表单可见字段，未提交字段必须保留配置中的止损模式/评分门槛/冷却期等，
    否则会退化为 StrategyParams 模型默认值（fixed 止损、高买入门槛），与页面展示的配置严重不一致。
    """
    config = _user_configs(user_id).get(request.strategy_type)
    if not config:
        raise HTTPException(status_code=400, detail="未知策略类型")
    if request.params is None:
        return config.params
    incoming = request.params.model_dump(exclude_unset=True)
    return config.params.model_copy(update=incoming)


def _backtest_fingerprint(request: BacktestRequest, params: StrategyParams) -> str:
    """同账号下「策略 + 区间 + 本金 + 完整参数」的指纹，用于识别重复提交"""
    payload = json.dumps(
        {
            "strategy_type": request.strategy_type.value,
            "start_date": request.start_date,
            "end_date": request.end_date,
            "initial_capital": round(float(request.initial_capital), 2),
            "params": params.model_dump(),
        },
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


def _execute_backtest(
    user_id: int,
    strategy_type: StrategyType,
    start_date: str,
    end_date: str,
    initial_capital: float,
    params: StrategyParams,
    on_progress=None,
) -> dict:
    """执行一次回测并落库（同步），返回完整结果

    on_progress(done, total): 逐日回放进度回调，同步接口不传，异步任务用它刷新任务进度。
    """
    scope = user_scope(user_id)
    daily_data = influx_query.query_daily_sectors(start_date, end_date)
    if not daily_data:
        raise HTTPException(status_code=404, detail="没有可用的历史数据")

    sorted_dates = sorted(daily_data.keys())
    trading_days = len(sorted_dates)
    logger.info(f"回测 {strategy_type.value}: {trading_days} 个交易日, {sorted_dates[0]} ~ {sorted_dates[-1]}")

    # 获取上证指数数据作为基准
    sh_returns = influx_query.query_sh_index_returns(sorted_dates[0], sorted_dates[-1])
    result_data = _run_backtest_core(
        daily_data, sorted_dates, strategy_type, params, initial_capital,
        return_full=True, sh_index_returns=sh_returns, on_progress=on_progress,
    )

    bt_id = f"bt_{strategy_type.value}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"
    result_data["id"] = bt_id
    result_data["created_at"] = datetime.now().isoformat()

    # 保存回测结果到Redis（按账号隔离）
    redis_mgr.setex(f"{scope}:backtest:{bt_id}", 7 * 86400, json.dumps(result_data, ensure_ascii=False))

    # 保存到回测历史列表
    history_key = f"{scope}:backtest_history:{strategy_type.value}"
    history_entry = {
        "id": bt_id,
        "strategy_type": strategy_type.value,
        "start_date": start_date,
        "end_date": end_date,
        "initial_capital": initial_capital,
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

    return result_data


def _update_backtest_task(task_key: str, **fields) -> None:
    """合并更新任务状态（状态量小，整体重写即可）"""
    raw = redis_mgr.get(task_key)
    try:
        data = json.loads(raw) if raw else {}
    except Exception:
        data = {}
    data.update(fields)
    redis_mgr.setex(task_key, _BACKTEST_TASK_TTL, json.dumps(data, ensure_ascii=False))


def _run_backtest_task(
    user_id: int,
    task_key: str,
    lock_key: str,
    strategy_type: StrategyType,
    start_date: str,
    end_date: str,
    initial_capital: float,
    params: StrategyParams,
) -> None:
    """后台线程执行回测，状态写 Redis 供前端轮询"""
    started_at = datetime.now()
    last_progress = -1

    def report_progress(done: int, total: int) -> None:
        """逐日回放占进度 5%~95%，余下留给取数与落库；每涨 3 个百分点写一次 Redis"""
        nonlocal last_progress
        percent = 5 + int(done / max(total, 1) * 90)
        if percent - last_progress < 3 and done < total:
            return
        last_progress = percent
        _update_backtest_task(
            task_key, status="running", progress=percent,
            progress_done=done, progress_total=total,
            elapsed_seconds=round((datetime.now() - started_at).total_seconds(), 1),
            updated_at=datetime.now().isoformat(),
        )

    _update_backtest_task(
        task_key, status="running", progress=1,
        elapsed_seconds=0, updated_at=datetime.now().isoformat(),
    )
    try:
        result_data = _execute_backtest(
            user_id, strategy_type, start_date, end_date, initial_capital, params,
            on_progress=report_progress,
        )
        _update_backtest_task(
            task_key, status="done", progress=100, bt_id=result_data["id"],
            elapsed_seconds=round((datetime.now() - started_at).total_seconds(), 1),
            finished_at=datetime.now().isoformat(), updated_at=datetime.now().isoformat(),
        )
    except HTTPException as e:
        logger.error(f"回测任务失败: {e.detail}")
        _update_backtest_task(
            task_key, status="failed", error=str(e.detail),
            finished_at=datetime.now().isoformat(), updated_at=datetime.now().isoformat(),
        )
    except Exception as e:
        logger.error(f"回测任务失败: {e}")
        _update_backtest_task(
            task_key, status="failed", error=str(e),
            finished_at=datetime.now().isoformat(), updated_at=datetime.now().isoformat(),
        )
    finally:
        # 任务结束后释放锁，相同参数可以立即重跑
        redis_mgr.delete(lock_key)


@app.post("/backtest/async")
async def submit_backtest(
    request: BacktestRequest,
    authorization: str | None = Header(None, alias="Authorization"),
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    """提交回测任务（异步执行，用 GET /backtest/task/{task_id} 轮询）

    相同参数在任务结束前重复提交会复用同一个 task_id，避免网络重发产生重复记录。
    """
    actor = _resolve_actor(authorization, x_internal_token)
    scope = user_scope(actor.user_id)
    params = _merge_backtest_params(actor.user_id, request)

    task_id = f"btt_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"
    task_key = f"{scope}:backtest_task:{task_id}"
    lock_key = f"{scope}:backtest_submit:{_backtest_fingerprint(request, params)}"
    now = datetime.now().isoformat()

    # 先写任务状态再抢锁：锁一旦可见，其指向的任务状态必然已就绪，
    # 重复提交读到锁时不会出现「锁已存在但状态还没写」的空窗。
    _update_backtest_task(
        task_key, task_id=task_id, status="queued",
        strategy_type=request.strategy_type.value,
        start_date=request.start_date, end_date=request.end_date,
        initial_capital=request.initial_capital,
        created_at=now, updated_at=now,
    )

    # SET NX 保证并发/重发的两次提交只有一个能创建任务
    claimed = True
    try:
        claimed = bool(redis_mgr.client.set(lock_key, task_id, nx=True, ex=_BACKTEST_LOCK_TTL))
    except Exception as e:
        logger.warning(f"回测提交锁不可用，降级为直接提交: {e}")

    if not claimed:
        existing_task = redis_mgr.get(lock_key)
        raw = redis_mgr.get(f"{scope}:backtest_task:{existing_task}") if existing_task else None
        redis_mgr.delete(task_key)  # 丢弃本次多写的任务状态
        if existing_task and raw:
            logger.info(f"回测重复提交，复用任务 {existing_task}")
            return {"code": 200, "data": {**json.loads(raw), "reused": True}}
        # 锁指向的任务状态已不存在（数据异常），宁可让用户重试也不重复计算
        redis_mgr.delete(lock_key)
        raise HTTPException(status_code=503, detail="回测提交冲突，请重试")

    try:
        _BACKTEST_EXECUTOR.submit(
            _run_backtest_task, actor.user_id, task_key, lock_key, request.strategy_type,
            request.start_date, request.end_date, request.initial_capital, params,
        )
    except Exception as e:
        logger.error(f"回测任务提交失败: {e}")
        redis_mgr.delete(lock_key)
        _update_backtest_task(task_key, status="failed", error=f"任务提交失败: {e}", updated_at=now)
        raise HTTPException(status_code=500, detail=f"回测任务提交失败: {e}")

    return {"code": 200, "data": {"task_id": task_id, "status": "queued", "reused": False}}


@app.get("/backtest/task/{task_id}")
def get_backtest_task(
    task_id: str,
    authorization: str | None = Header(None, alias="Authorization"),
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    """查询回测任务状态（账号隔离，他人 task_id 不可见）"""
    actor = _resolve_actor(authorization, x_internal_token)
    raw = redis_mgr.get(f"{user_scope(actor.user_id)}:backtest_task:{task_id}")
    if not raw:
        raise HTTPException(status_code=404, detail="回测任务不存在或已过期")
    return {"code": 200, "data": json.loads(raw)}


@app.post("/backtest")
async def run_backtest(
    request: BacktestRequest,
    authorization: str | None = Header(None, alias="Authorization"),
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    """运行策略回测 - 基于真实历史数据逐日回放（结果仅归当前账号）

    同步接口，供 scheduler / mcp-agent / ai-decision 等内部服务调用；
    浏览器侧走 /backtest/async + 轮询，避免长连接被手机网络切换中断。
    """
    actor = _resolve_actor(authorization, x_internal_token)
    try:
        params = _merge_backtest_params(actor.user_id, request)
        # 放到线程池执行，避免阻塞事件循环
        loop = asyncio.get_event_loop()
        result_data = await loop.run_in_executor(
            None,
            lambda: _execute_backtest(
                actor.user_id, request.strategy_type, request.start_date,
                request.end_date, request.initial_capital, params,
            ),
        )
        return {"code": 200, "data": result_data}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"回测失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# 历史 K 线按日期区间做进程内缓存：同一交易日内所有账号的批量计算
# 只打一次 InfluxDB，而不是每个账号每个策略各打两次（N×3 放大）
_HISTORY_CACHE: dict[tuple, tuple[float, dict]] = {}
_HISTORY_LOCK = threading.Lock()
_HISTORY_CACHE_TTL = 600
_HISTORY_CACHE_MAX = 4


def _load_sector_history_cache(sorted_dates, use_memo: bool = True) -> dict:
    """批量加载所有板块历史数据（2次InfluxDB查询），供回测/信号计算复用

    Returns:
        {sector_code: [rows按date升序, 合并K线(OHLCV)与资金流/估值字段], ...}
    """
    cache_key = (sorted_dates[0], sorted_dates[-1]) if sorted_dates else None
    now = time.monotonic()
    if use_memo and cache_key is not None:
        with _HISTORY_LOCK:
            hit = _HISTORY_CACHE.get(cache_key)
        if hit and now - hit[0] < _HISTORY_CACHE_TTL:
            return hit[1]

    sector_history_cache = {}
    try:
        from datetime import timedelta
        # 回溯 400 自然日 ≈ 270 个交易日，覆盖最长因子窗口（trend 60日均线、technical 35日等）
        hist_start = (datetime.strptime(sorted_dates[0], "%Y-%m-%d") - timedelta(days=400)).strftime("%Y-%m-%d")
        hist_end = sorted_dates[-1]
        all_kline = influx_query.query_all_sector_kline(hist_start, hist_end)
        all_flow = influx_query.query_daily_sectors(hist_start, hist_end)
        flow_by_sector = {}
        for date_key, sectors in all_flow.items():
            for s in sectors:
                code = s.get("sector_code", "")
                if code not in flow_by_sector:
                    flow_by_sector[code] = []
                flow_by_sector[code].append({"date": date_key, **s})
        all_codes = set(list(all_kline.keys()) + list(flow_by_sector.keys()))
        for code in all_codes:
            kline = all_kline.get(code, [])
            flow = flow_by_sector.get(code, [])
            if kline:
                flow_map = {f["date"]: f for f in flow}
                for k in kline:
                    f = flow_map.get(k["date"], {})
                    k.update({k2: v2 for k2, v2 in f.items() if k2 != "date" and v2})
                sector_history_cache[code] = kline
            elif flow:
                sector_history_cache[code] = flow
        for rows in sector_history_cache.values():
            rows.sort(key=lambda r: r.get("date", ""))
        logger.info(f"回测预加载历史: {len(sector_history_cache)}个板块, {hist_start}~{hist_end}, 2次查询")
        if use_memo and cache_key is not None and sector_history_cache:
            with _HISTORY_LOCK:
                _HISTORY_CACHE[cache_key] = (time.monotonic(), sector_history_cache)
                # 只保留最近若干个区间，避免长跑进程无限增长
                for stale_key in list(_HISTORY_CACHE)[:-_HISTORY_CACHE_MAX]:
                    _HISTORY_CACHE.pop(stale_key, None)
    except Exception as e:
        logger.warning(f"回测历史预加载失败: {e}")
    return sector_history_cache


def _safe_num(value, default=0.0) -> float:
    """安全转换为 float，兼容 None / 空字符串 / NaN / Inf"""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if v != v or v in (float("inf"), float("-inf")):
        return default
    return v


def _resolve_daily_prices(sector_data: list, last_close: dict) -> dict:
    """解析当日伪价格，供逐仓份额记账使用

    优先使用数据源的 index_close / open；缺失时用最近收盘价与涨跌幅合成，
    保证只有涨跌幅的数据源也能得到自洽的价格序列。

    Args:
        sector_data: 当日板块数据列表
        last_close: {sector_code: 最近一次收盘价}

    Returns:
        {sector_code: {"open": float, "close": float, "chg": float, "prev_close": float}}
    """
    px = {}
    for s in sector_data:
        code = s.get("sector_code")
        if not code:
            continue
        chg = _safe_num(s.get("index_change_pct", 0)) / 100.0
        close_p = _safe_num(s.get("index_close", 0))
        prev = _safe_num(last_close.get(code, 0))
        if close_p <= 0:
            base = prev if prev > 0 else 100.0
            close_p = base * (1 + chg)
        if close_p <= 0:
            continue
        if prev <= 0:
            prev = close_p / (1 + chg) if chg > -0.99 else close_p
            if prev <= 0:
                prev = close_p
        open_p = _safe_num(s.get("open", 0))
        if open_p <= 0:
            open_p = prev
        px[code] = {"open": open_p, "close": close_p, "chg": chg, "prev_close": prev}
    return px


def _summarize_nav_curve(nav_list: list, risk_free_rate: float = 0.02) -> dict | None:
    """对拼接后的完整净值曲线重算全区间指标（训练集 + 样本外）

    指标口径与 _run_backtest_core 内部保持一致：
    - 年化按 252 交易日；夏普按超额日收益 (mean * 252) / (std * sqrt(252))
    - 最大回撤按净值峰值回算；日胜率为日收益 > 0 的占比
    用于让寻优结果顶部指标与拼接后的完整曲线一致，而非仅反映训练集。
    """
    navs = [_safe_num(x.get("nav")) for x in (nav_list or [])]
    navs = [v for v in navs if v > 0]
    if len(navs) < 2:
        return None

    n = len(navs)
    first, last = navs[0], navs[-1]
    total_return = last / first - 1 if first > 0 else 0.0
    annual_return = ((1 + total_return) ** (TRADING_DAYS_PER_YEAR / n) - 1
                     if total_return > -1 else -1.0)

    peak, max_dd = navs[0], 0.0
    for v in navs:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd

    rets = np.diff(navs) / navs[:-1]
    rf_daily = (1 + _safe_num(risk_free_rate)) ** (1 / TRADING_DAYS_PER_YEAR) - 1
    std = float(np.std(rets))
    sharpe = 0.0
    if std > 0:
        sharpe = float((np.mean(rets - rf_daily) * TRADING_DAYS_PER_YEAR)
                       / (std * np.sqrt(TRADING_DAYS_PER_YEAR)))

    return {
        "initial_capital": round(first, 2),
        "final_capital": round(last, 2),
        "total_return": round(total_return, 6),
        "annual_return": round(annual_return, 6),
        "max_drawdown": round(max_dd, 6),
        "sharpe_ratio": round(sharpe, 4),
        "daily_win_rate": round(float(np.mean(rets > 0)), 4),
        "trading_days": n,
    }


def _run_backtest_core(daily_data, sorted_dates, strategy_type, params, initial_capital, return_full=False, sh_index_returns=None, history_cache=None, initial_bench_capital=None, on_progress=None):
    """回测核心逻辑（统一入口）

    成交模型（T+1 统一）：
        T 日收盘生成信号 → T+1 开盘按开盘价成交。
        - T+1 开盘买入的份额：当日按 open→close 计收益（用市值记账自动实现）
        - T+1 开盘卖出的份额：当日只计 prev_close→open 的隔夜跳空
        - T+1 未交易的持仓：按 prev_close→close 计全天收益
        所有风险事件（止损 / 紧急退出 / 熊市清仓 / 均线止盈）同样次日开盘执行，
        杜绝"用当日收盘数据按当日收盘价成交"的未来函数。

    记账方式：
        逐仓份额记账 positions = {code: {"shares", "avg_cost"}}，
        组合权益 = 现金 + Σ 份额 × 收盘价，权重随价格自然漂移；
        现金按日无风险利率计息，空仓日收益 = 无风险利率日收益。

    Args:
        sh_index_returns: 上证指数每日涨跌幅 {date_str: return_decimal}，为 None 时使用板块等权平均
        history_cache: 预加载的板块历史缓存 {sector_code: [rows...]}（按日期升序），
                      寻优时由外层构建一次并复用，避免每次试验重复查询InfluxDB

    Returns:
        dict: 回测结果，含 nav_curve（逐日净值）、position_changes（仓位调整明细）、daily_signals 等
    """
    if not sorted_dates or initial_capital <= 0:
        return _empty_backtest_result(strategy_type, initial_capital, return_full)

    # ============ 账户状态 ============
    cash = float(initial_capital)                # 现金账本（含利息，不允许为负）
    positions = {}                                # {sector_code: {"shares": float, "avg_cost": float}}
    last_close = {}                               # {sector_code: 最近一次收盘价}
    equity = float(initial_capital)               # 组合权益 = 现金 + 持仓市值

    daily_nav = []
    position_hold_counter = 0
    stop_loss_triggered = False
    stop_loss_cooldown = 0
    rebalance_cooldown = 0
    pending_rebalance = None   # 待执行调仓：{new_positions, signals_by_code, signal_day_chg, signal_date}
    pending_orders = []        # 待执行风险单：[{code, shares(None=全清), action, reason}]
    nav_curve = []
    daily_returns = []
    daily_signals_out = []
    position_changes = []      # 仓位调整明细
    total_commission = 0.0
    total_stamp_tax = 0.0
    total_slippage_cost = 0.0
    traded_amount_total = 0.0  # 累计成交额（买卖双边）
    trade_count_actual = 0
    trade_pnls = []            # 每笔平仓的已实现盈亏（含交易成本）
    # 动态市场状态追踪
    regime_history = []        # 最近市场状态 ["BULL"/"NEUTRAL"/"BEAR"]
    empty_days = 0             # 连续空仓天数
    bear_empty = False         # 处于市场BEAR引发的空仓（回补需恢复门控确认）
    # 多重止损追踪
    peak_capital = equity              # 权益峰值
    trailing_peak = equity             # 移动止损用的近期高点
    max_dd_from_initial = 0.0          # 从初始资金的最大回撤比例
    cumulative_benchmark_return = 0.0  # 累计基准收益率（用于相对止损）
    nav_history = []                   # 净值历史（用于均线止损/止盈）
    reference_capital = equity         # 止损重置后的参考资金（用于相对止损，避免清仓后旧亏损拖累）
    portfolio_snapshots = []           # 收盘持仓快照
    day_entered = {}                   # {sector_code: date} 各板块建仓日期（用于最少持有天数）
    take_profit_level = 0              # 当前止盈阶梯级别
    take_profit_base_shares = {}       # {sector_code: shares} 止盈开始时的原始份额

    rf_daily = (1 + _safe_num(params.risk_free_rate)) ** (1 / TRADING_DAYS_PER_YEAR) - 1
    # 基准净值起点：默认等于初始资金；样本外回测需显式传入训练集末的基准净值，
    # 否则拼接后基准曲线会在切分点跳变（策略净值连续但基准不连续）
    bench_nav = float(initial_bench_capital if initial_bench_capital is not None else initial_capital)
    raw_sectors = []
    px = {}                                       # 当日行情 {code: {open/close/chg/prev_close}}
    equity_open = float(initial_capital)          # 当日开盘前权益（按最近收盘价估值）
    day_position_detail = {}                      # 当日收盘持仓明细

    # ============ 内部工具函数（闭包共享当日行情与账户） ============

    def _open_price(code):
        v = px.get(code)
        if v and v["open"] > 0:
            return v["open"]
        return last_close.get(code, 0.0)

    def _position_value(code):
        """按开盘价估值持仓市值（调仓时点使用）"""
        pos = positions.get(code)
        if not pos:
            return 0.0
        return pos["shares"] * (_open_price(code) or last_close.get(code, 0.0) or pos["avg_cost"])

    def _sector_name(code):
        info = next((s for s in raw_sectors if s.get("sector_code") == code), None)
        if info:
            return info.get("sector_name", "") or code
        return sector_meta.get(code, {}).get("sector_name", "") or code

    def _mark_equity(price_key: str) -> float:
        """按指定价格口径（prev_close / open / close）计算组合权益"""
        total = cash
        for code, pos in positions.items():
            p = 0.0
            v = px.get(code)
            if v:
                p = v.get(price_key, 0.0)
            if p <= 0:
                p = last_close.get(code, 0.0)
            if p <= 0:
                p = pos["avg_cost"]
            total += pos["shares"] * p
        return total

    def _record_position_change(date, sector_code, sector_name, action, amount, cost, reason="", remaining_value=0.0):
        """记录仓位调整明细"""
        weight = (remaining_value / equity_open) if equity_open > 0 else 0.0
        position_changes.append({
            "date": date,
            "sector_code": sector_code,
            "sector_name": sector_name,
            "action": action,  # ADD / REDUCE / CLEAR / HOLD / STOP_LOSS / EMERGENCY_EXIT / BEAR_EXIT / TAKE_PROFIT
            "amount": round(amount, 2),
            "cost": round(cost, 2),
            "remaining_weight": round(weight, 4),
            "remaining_amount": round(remaining_value, 2),
            "reason": reason,
        })

    def _sell(sector_code, shares, action, reason="", sector_name=""):
        """按当日开盘价卖出指定份额，返回成交金额"""
        nonlocal cash, total_commission, total_stamp_tax, total_slippage_cost
        nonlocal trade_count_actual, traded_amount_total
        pos = positions.get(sector_code)
        if not pos or shares <= 0:
            return 0.0
        shares = min(shares, pos["shares"])
        price = _open_price(sector_code) or pos["avg_cost"]
        gross = shares * price
        cost_info = _calc_trade_cost(gross, params.commission_rate, params.stamp_tax_rate, params.slippage_rate, is_sell=True)
        fee = cost_info["total"]
        cash += gross - fee
        total_commission += cost_info["commission"]
        total_stamp_tax += cost_info["stamp_tax"]
        total_slippage_cost += cost_info["slippage"]
        trade_count_actual += 1
        traded_amount_total += gross
        trade_pnls.append((price - pos["avg_cost"]) * shares - fee)

        pos["shares"] -= shares
        remaining_shares = pos["shares"]
        remaining_value = 0.0
        if remaining_shares <= 1e-9:
            positions.pop(sector_code, None)
            day_entered.pop(sector_code, None)
            take_profit_base_shares.pop(sector_code, None)
            remaining_shares = 0.0
        else:
            remaining_value = remaining_shares * price
        _record_position_change(date, sector_code, sector_name or _sector_name(sector_code),
                                action, gross, fee, reason, remaining_value)
        return gross

    def _buy(sector_code, target_amount, action, reason="", sector_name=""):
        """按当日开盘价买入，金额受可用现金约束，返回实际成交金额"""
        nonlocal cash, total_commission, total_stamp_tax, total_slippage_cost
        nonlocal trade_count_actual, traded_amount_total
        price = _open_price(sector_code) or last_close.get(sector_code, 0.0)
        if price <= 0 or target_amount <= 0:
            return 0.0
        # 现金约束：买入金额 + 交易成本不得超过可用现金（佣金有5元下限，需迭代收敛）
        amount = min(target_amount, max(cash, 0.0))
        for _ in range(6):
            cost_info = _calc_trade_cost(amount, params.commission_rate, params.stamp_tax_rate, params.slippage_rate, is_sell=False)
            if amount + cost_info["total"] <= cash + 1e-9:
                break
            amount = max(0.0, amount - (amount + cost_info["total"] - cash))
        if amount <= 1e-6:
            return 0.0
        cost_info = _calc_trade_cost(amount, params.commission_rate, params.stamp_tax_rate, params.slippage_rate, is_sell=False)
        fee = cost_info["total"]
        cash -= amount + fee
        total_commission += cost_info["commission"]
        total_slippage_cost += cost_info["slippage"]
        trade_count_actual += 1
        traded_amount_total += amount

        add_shares = amount / price
        pos = positions.get(sector_code)
        if pos is None:
            pos = {"shares": 0.0, "avg_cost": price}
            positions[sector_code] = pos
        new_shares = pos["shares"] + add_shares
        pos["avg_cost"] = (pos["avg_cost"] * pos["shares"] + amount) / new_shares if new_shares > 0 else price
        pos["shares"] = new_shares

        _record_position_change(date, sector_code, sector_name or _sector_name(sector_code),
                                action, amount, fee, reason, new_shares * price)
        return amount

    def _reset_tracking(base_equity=None):
        """清仓后重置峰值追踪，避免新仓被旧峰值拖累立即再次触发止损"""
        nonlocal peak_capital, trailing_peak, max_dd_from_initial, cumulative_benchmark_return, reference_capital
        base = base_equity if base_equity and base_equity > 0 else equity
        peak_capital = base
        trailing_peak = base
        max_dd_from_initial = 0.0
        cumulative_benchmark_return = 0.0
        reference_capital = base
        nav_history.clear()

    def _record_portfolio_snapshot(date):
        """收盘后记录持仓快照（各板块权重、市值、当日涨跌、贡献）"""
        if not positions:
            return
        portfolio = []
        for code, pos in positions.items():
            price = (px.get(code) or {}).get("close", 0.0) or last_close.get(code, 0.0) or pos["avg_cost"]
            value = pos["shares"] * price
            weight = value / equity if equity > 0 else 0.0
            day_change = (px.get(code) or {}).get("chg", 0.0)
            portfolio.append({
                "sector_code": code,
                "sector_name": sector_meta.get(code, {}).get("sector_name", "") or code,
                "weight": round(weight, 4),
                "amount": round(value, 2),
                "day_change_pct": round(day_change * 100, 2),
                "contribution_pct": round(weight * day_change * 100, 4),
            })
        portfolio.sort(key=lambda x: x["weight"], reverse=True)
        portfolio_snapshots.append({
            "date": date,
            "portfolio": portfolio,
            "cash": round(cash, 2),
            "total_value": round(equity, 2),
        })

    # ============ 数据准备 ============
    if history_cache is None:
        sector_history_cache = _load_sector_history_cache(sorted_dates)
    else:
        sector_history_cache = history_cache
    hist_dates = {code: [r.get("date", "") for r in rows] for code, rows in sector_history_cache.items()}

    # 预构建板块元信息（名称/ETF），供每日持仓明细展示
    sector_meta: dict[str, dict] = {}
    for day_sectors in daily_data.values():
        for s in day_sectors:
            code = s.get("sector_code")
            if not code:
                continue
            m = sector_meta.get(code)
            if m is None:
                m = {"sector_name": s.get("sector_name", ""), "etf_code": s.get("etf_code"), "etf_name": s.get("etf_name")}
                sector_meta[code] = m
            elif not m.get("etf_code") and s.get("etf_code"):
                m["etf_code"] = s.get("etf_code")
                m["etf_name"] = s.get("etf_name")

    from bisect import bisect_right

    for i, date in enumerate(sorted_dates):
        raw_sectors = daily_data.get(date, [])
        px = _resolve_daily_prices(raw_sectors, last_close) if raw_sectors else {}
        traded_today = False
        day_position_detail = {}

        # 开盘前权益（按最近收盘价估值），作为当日收益与仓位的基准
        equity_open = _mark_equity("prev_close")

        # ========== 开盘：执行 T 日挂起、T+1 开盘价成交的订单 ==========
        if pending_orders:
            full_exit = False
            for order in pending_orders:
                code = order["code"]
                pos = positions.get(code)
                if not pos:
                    continue
                sell_shares = pos["shares"] if order["shares"] is None else min(order["shares"], pos["shares"])
                if sell_shares <= 0:
                    continue
                _sell(code, sell_shares, order["action"], order["reason"])
                traded_today = True
                if order["shares"] is None:
                    full_exit = True
            if full_exit:
                _reset_tracking(_mark_equity("open"))
                pending_rebalance = None
                take_profit_level = 0
                take_profit_base_shares.clear()
                day_entered.clear()
                position_hold_counter = 0
                if not positions:
                    logger.info(f"[{date}] 风险事件清仓完成，重置追踪基准 equity={equity_open:.0f}")
            elif not positions:
                take_profit_level = 0
                take_profit_base_shares.clear()
                position_hold_counter = 0
            pending_orders = []

        elif pending_rebalance is not None:
            pr = pending_rebalance
            signals_by_code = pr["signals_by_code"]
            signal_day_chg = pr.get("signal_day_chg", {})
            min_keep = params.min_score_keep if params.min_score_keep else 2.5
            max_total = params.max_position if params.max_position else 1.0

            old_codes = set(positions.keys())
            target_value = {c: equity_open * w for c, w in pr["new_positions"].items() if w > 0}
            new_total = sum(target_value.values())

            # 1) 继续持有判断：只使用信号日(T日)已经公开的评分与涨跌，避免未来函数
            kept_value = {}
            kept_info = {}
            for code in list(positions.keys()):
                if code in target_value:
                    continue
                sig = signals_by_code.get(code, {})
                score = _safe_num(sig.get("score", 0))
                day_chg = _safe_num(signal_day_chg.get(code, 0))
                if score >= min_keep and day_chg > 0:
                    kept_value[code] = _position_value(code)
                    kept_info[code] = (score, day_chg)

            kept_budget = max(0.0, equity_open * max_total - new_total)
            kept_sum = sum(kept_value.values())
            for code, val in kept_value.items():
                score, day_chg = kept_info[code]
                allow = val * (kept_budget / kept_sum) if kept_sum > kept_budget > 0 or (kept_sum > 0 and kept_budget <= 0) else val
                if allow < val - 1e-6:
                    price = _open_price(code)
                    if price > 0:
                        _sell(code, (val - allow) / price, "HOLD",
                              f"继续持有(缩仓): 评分{score:.2f}>=阈值{min_keep:.2f}, 缩至{max_total:.0%}仓位以内")
                        traded_today = True
                else:
                    _record_position_change(date, code, _sector_name(code), "HOLD", 0, 0,
                                            f"继续持有: 评分{score:.2f}>=阈值{min_keep:.2f}, 信号日涨{day_chg:.2%}",
                                            remaining_value=_position_value(code))
                day_entered[code] = i

            # 2) 清仓：旧有新无且未继续持有（按开盘价全卖，当日仅计隔夜跳空）
            for code in list(old_codes):
                if code in target_value or code in kept_value:
                    continue
                pos = positions.get(code)
                if not pos:
                    continue
                sig_reason = signals_by_code.get(code, {}).get("reason", "")
                _sell(code, pos["shares"], "CLEAR",
                      f"调仓清仓 {sig_reason}" if sig_reason else f"调仓清仓(T+1 {pr['signal_date']}→{date})")
                traded_today = True
                day_entered.pop(code, None)

            # 3) 共有标的调整到目标金额 + 新建仓（先卖后买，买入受现金约束）
            buy_orders = []
            for code, target in target_value.items():
                cur = _position_value(code)
                old_w = cur / equity_open if equity_open > 0 else 0.0
                new_w = target / equity_open if equity_open > 0 else 0.0
                diff = target - cur
                if diff < -1e-6:
                    price = _open_price(code)
                    if price > 0:
                        _sell(code, -diff / price, "REDUCE", f"减仓 {old_w:.2%} → {new_w:.2%} (T+1)")
                        traded_today = True
                elif diff > 1e-6:
                    buy_orders.append((code, diff, old_w, new_w, code in old_codes))

            for code, amount, old_w, new_w, is_add in buy_orders:
                reason = f"加仓 {old_w:.2%} → {new_w:.2%} (T+1)" if is_add else f"新建仓 权重{new_w:.2%} (T+1)"
                if _buy(code, amount, "ADD", reason) > 0:
                    traded_today = True
                    day_entered[code] = i

            # 4) 调仓后设置锁定期，避免频繁换手
            if positions:
                base_hold = params.hold_days
                total_sectors = len(raw_sectors)
                up_count = sum(1 for s in raw_sectors if _safe_num(s.get("index_change_pct", 0)) > 0)
                up_ratio = up_count / max(total_sectors, 1)
                avg_change_val = sum(_safe_num(s.get("index_change_pct", 0)) for s in raw_sectors) / max(total_sectors, 1)
                bull_thr = params.market_bull_threshold if params.market_bull_threshold is not None else 0.5
                bear_thr = params.market_bear_threshold if params.market_bear_threshold is not None else 0.4
                if up_ratio >= bull_thr and avg_change_val > 0:
                    market_regime_open = "BULL"
                elif up_ratio < bear_thr and avg_change_val < 0:
                    market_regime_open = "BEAR"
                else:
                    market_regime_open = "NEUTRAL"
                if market_regime_open == "BULL":
                    dynamic_hold = max(base_hold - 1, 1)
                elif market_regime_open == "BEAR":
                    dynamic_hold = base_hold + 1
                else:
                    dynamic_hold = base_hold
                position_hold_counter = dynamic_hold
                stop_loss_triggered = False
                rebalance_cooldown = params.cooldown_days if params.cooldown_days else 2
                empty_days = 0

            pending_rebalance = None

        # ========== 收盘：市值重估 + 现金计息 ==========
        for code, v in px.items():
            last_close[code] = v["close"]
        if rf_daily:
            cash += cash * rf_daily
        equity = _mark_equity("close")
        strategy_daily_return = (equity - equity_open) / equity_open if equity_open > 0 else 0.0

        daily_nav.append(equity)
        daily_returns.append(strategy_daily_return)

        if sh_index_returns and date in sh_index_returns:
            benchmark_return = _safe_num(sh_index_returns[date])
        elif raw_sectors:
            all_changes = [_safe_num(s.get("index_change_pct", 0)) / 100.0 for s in raw_sectors]
            benchmark_return = float(np.mean(all_changes)) if all_changes else 0.0
        else:
            benchmark_return = 0.0
        bench_nav *= (1 + benchmark_return)

        if equity > peak_capital:
            peak_capital = equity
        if equity > trailing_peak:
            trailing_peak = equity
        dd_from_initial = (reference_capital - equity) / reference_capital if reference_capital > 0 else 0.0
        if dd_from_initial > max_dd_from_initial:
            max_dd_from_initial = dd_from_initial
        cumulative_benchmark_return = (1 + cumulative_benchmark_return) * (1 + benchmark_return) - 1
        nav_history.append(equity)
        if len(nav_history) > 120:
            nav_history = nav_history[-120:]

        # ========== 多重止损检查（触发后次日开盘执行） ==========
        stop_loss_reason = None
        # 所有持仓都已持有一天以上才允许止损（新建仓当天不触发）
        min_hold_met = all(
            day_entered.get(code, -999) < i
            for code in positions
        ) if positions else False

        if positions and min_hold_met:
            logger.debug(f"[{date}] 止损检查: equity={equity:.0f} peak={peak_capital:.0f} trailing={trailing_peak:.0f} "
                         f"ref={reference_capital:.0f} dd_peak={(peak_capital - equity) / peak_capital if peak_capital > 0 else 0:.2%} "
                         f"rel_under={cumulative_benchmark_return - (equity - reference_capital) / reference_capital if reference_capital > 0 else 0:.2%}")

        if params.stop_loss_mode == "trend_break":
            # 趋势破位止损：仅在组合净值有效跌破长周期均线时清仓（宽松化止损，避免牛市低点踏空）
            if positions and min_hold_met and not stop_loss_triggered:
                win = min(len(nav_history), params.trend_ma_days)
                if win >= 20:
                    tma = sum(nav_history[-win:]) / win
                    if tma > 0 and (tma - equity) / tma >= params.ma_stop_loss:
                        stop_loss_reason = (
                            f"趋势破位止损: 当前{equity / 1e4:.2f}万跌破{params.trend_ma_days}日均线{tma / 1e4:.2f}万, "
                            f"偏离{(tma - equity) / tma:.2%} >= 阈值{params.ma_stop_loss:.0%}"
                        )
        else:
            # 2a: 固定回撤止损（从峰值回撤超阈值）
            if params.stop_loss and not stop_loss_triggered and peak_capital > 0 and positions and min_hold_met:
                drawdown_from_peak = (peak_capital - equity) / peak_capital
                if drawdown_from_peak >= params.stop_loss:
                    stop_loss_reason = (
                        f"固定回撤止损: 组合从峰值{peak_capital / 1e4:.2f}万回落至{equity / 1e4:.2f}万, "
                        f"回撤{drawdown_from_peak:.2%} >= 阈值{params.stop_loss:.0%}"
                    )

            # 2b: 移动止损 — 从近期高点回撤超阈值
            if not stop_loss_reason and params.trailing_stop_loss and not stop_loss_triggered and trailing_peak > 0 and positions and min_hold_met:
                trailing_dd = (trailing_peak - equity) / trailing_peak
                if trailing_dd >= params.trailing_stop_loss:
                    stop_loss_reason = (
                        f"移动止损: 近期高点{trailing_peak / 1e4:.2f}万回落至{equity / 1e4:.2f}万, "
                        f"回撤{trailing_dd:.2%} >= 阈值{params.trailing_stop_loss:.0%}"
                    )

            # 2c: 最大回撤止损 — 从参考资金累计亏损超阈值
            if not stop_loss_reason and params.max_drawdown_stop and not stop_loss_triggered and positions and min_hold_met:
                if max_dd_from_initial >= params.max_drawdown_stop:
                    stop_loss_reason = (
                        f"最大回撤止损: 从参考资金{reference_capital / 1e4:.2f}万累计亏损{max_dd_from_initial:.2%} "
                        f">= 阈值{params.max_drawdown_stop:.0%}, 当前{equity / 1e4:.2f}万"
                    )

            # 2d: 基准相对止损 — 落后大盘超阈值
            if not stop_loss_reason and params.benchmark_stop_loss and not stop_loss_triggered and positions and min_hold_met:
                relative_underperform = cumulative_benchmark_return - (equity - reference_capital) / reference_capital if reference_capital > 0 else 0
                if relative_underperform >= params.benchmark_stop_loss:
                    my_return = (equity - reference_capital) / reference_capital if reference_capital > 0 else 0
                    stop_loss_reason = (
                        f"基准相对止损: 策略收益{my_return:.2%}, 大盘收益{cumulative_benchmark_return:.2%}, "
                        f"落后{relative_underperform:.2%} >= 阈值{params.benchmark_stop_loss:.0%}"
                    )

            # 2e: 均线止损 — 净值跌破N日均线超阈值
            if not stop_loss_reason and params.ma_stop_loss and params.ma_stop_days and not stop_loss_triggered and positions and min_hold_met:
                window = min(len(nav_history), params.ma_stop_days)
                if window >= 10:
                    ma_val = sum(nav_history[-window:]) / window
                    if ma_val > 0 and (ma_val - equity) / ma_val >= params.ma_stop_loss:
                        stop_loss_reason = (
                            f"均线止损: 当前{equity / 1e4:.2f}万 < {window}日均线{ma_val / 1e4:.2f}万, "
                            f"偏离{(ma_val - equity) / ma_val:.2%} >= 阈值{params.ma_stop_loss:.0%}"
                        )

        if stop_loss_reason and positions:
            pending_orders = [{"code": c, "shares": None, "action": "STOP_LOSS", "reason": stop_loss_reason} for c in positions]
            pending_rebalance = None
            stop_loss_triggered = True
            stop_loss_cooldown = max(params.cooldown_days if params.cooldown_days else 2, 2)
            position_hold_counter = 0
            take_profit_level = 0
            take_profit_base_shares.clear()
            logger.warning(f"[{date}] 止损触发，次日开盘执行: {stop_loss_reason}")

        # 2f: 阶梯式均线止盈（可选） — NAV回落至均线上方阈值内时分批减仓
        if params.ma_take_profit_thresholds and params.ma_take_profit_ratios and not stop_loss_triggered and not stop_loss_reason and positions and min_hold_met and not params.trend_confirm:
            tp_window = min(len(nav_history), params.ma_take_profit_days) if params.ma_take_profit_days else 0
            if tp_window >= 10:
                tp_ma_val = sum(nav_history[-tp_window:]) / tp_window
                if tp_ma_val > 0 and equity > tp_ma_val:
                    deviation = (equity - tp_ma_val) / tp_ma_val
                    thresholds = params.ma_take_profit_thresholds
                    ratios = params.ma_take_profit_ratios
                    if take_profit_level == 0:
                        take_profit_base_shares = {c: p["shares"] for c, p in positions.items()}
                    if take_profit_level < len(thresholds) and deviation <= thresholds[take_profit_level]:
                        ratio = ratios[take_profit_level]
                        level_label = take_profit_level + 1
                        total_levels = len(thresholds)
                        orders = []
                        for code, pos in positions.items():
                            base_shares = take_profit_base_shares.get(code, 0.0)
                            if base_shares <= 0 or pos["shares"] <= 0:
                                continue
                            reduce_shares = min(base_shares * ratio, pos["shares"])
                            if reduce_shares <= 1e-9:
                                continue
                            orders.append({
                                "code": code,
                                "shares": reduce_shares,
                                "action": "TAKE_PROFIT",
                                "reason": (f"均线止盈{level_label}/{total_levels}: 偏离均线{deviation:.2%}<=阈值{thresholds[take_profit_level]:.0%}, "
                                           f"减仓{ratio:.0%}(基数{base_shares:.0f}份)"),
                            })
                        if orders:
                            pending_orders = orders
                            pending_rebalance = None
                            take_profit_level += 1
                            logger.info(f"[{date}] 均线止盈{level_label}/{total_levels}触发，次日开盘执行 {len(orders)}笔")

        # Step 3: 紧急退出检查（固定止损模式：单日跌幅超5%，次日开盘清仓）
        if positions and position_hold_counter > 0:
            if params.stop_loss_mode == "trend_break":
                # 趋势止损模式：持仓锁定期每日倒计时（不加紧急退出，避免与趋势止损重复触发）
                position_hold_counter -= 1
            else:
                emergency_exit = False
                trigger_sector = ""
                trigger_drop = 0.0
                for sector_code in positions:
                    info = next((s for s in raw_sectors if s.get("sector_code") == sector_code), None)
                    if info:
                        change = _safe_num(info.get("index_change_pct", 0))
                        if change <= -5.0:
                            emergency_exit = True
                            trigger_sector = info.get("sector_name", sector_code)
                            trigger_drop = change
                            break
                if emergency_exit:
                    reason = f"紧急退出: {trigger_sector}单日跌幅{trigger_drop:.2f}%>5%, 全部清仓"
                    pending_orders = [{"code": c, "shares": None, "action": "EMERGENCY_EXIT", "reason": reason} for c in positions]
                    pending_rebalance = None
                    take_profit_level = 0
                    take_profit_base_shares.clear()
                    position_hold_counter = 0
                    logger.warning(f"[{date}] {reason}，次日开盘执行")
                else:
                    position_hold_counter -= 1

        # Step 4: 更新止损冷静期
        if stop_loss_cooldown > 0:
            stop_loss_cooldown -= 1
            if stop_loss_cooldown <= 0:
                stop_loss_triggered = False

        # Step 5: 更新调仓冷却期
        if rebalance_cooldown > 0:
            rebalance_cooldown -= 1

        # Step 6: 收盘后计算市场状态 + 生成信号（T+1 开盘执行）
        day_signals = []
        market_regime = "NEUTRAL"
        _can_trade = (not stop_loss_triggered and not pending_orders
                      and (position_hold_counter <= 0 or take_profit_level > 0)
                      and stop_loss_cooldown <= 0 and rebalance_cooldown <= 0)
        if _can_trade:
            # 注入截至当日的板块历史（用局部副本，避免并发寻优时写入共享 daily_data）
            signal_sector_data = [dict(s) for s in raw_sectors]
            for s in signal_sector_data:
                code = s.get("sector_code")
                hd = hist_dates.get(code)
                if hd:
                    s["_history"] = sector_history_cache[code][:bisect_right(hd, date)]
            # 当前持仓权重（市值口径，随价格漂移）
            current_weights = {
                c: (p["shares"] * (last_close.get(c, 0) or p["avg_cost"])) / equity if equity > 0 else 0.0
                for c, p in positions.items()
            }
            quick_signals = scoring_model.calculate_daily_signals(
                sector_data=signal_sector_data,
                strategy_type=strategy_type,
                params=params,
                signal_date=date,
                current_positions=current_weights,
            )

            total_sectors = len(raw_sectors)
            up_count = sum(1 for s in raw_sectors if _safe_num(s.get("index_change_pct", 0)) > 0)
            up_ratio = up_count / max(total_sectors, 1)
            avg_change = sum(_safe_num(s.get("index_change_pct", 0)) for s in raw_sectors) / max(total_sectors, 1)

            bull_thr = params.market_bull_threshold if params.market_bull_threshold is not None else 0.5
            bear_thr = params.market_bear_threshold if params.market_bear_threshold is not None else 0.4

            if up_ratio >= bull_thr and avg_change > 0:
                market_regime = "BULL"
            elif up_ratio < bear_thr and avg_change < 0:
                market_regime = "BEAR"
            else:
                market_regime = "NEUTRAL"

            regime_history.append(market_regime)
            if len(regime_history) > 5:
                regime_history.pop(0)

            confirm_days = params.favorable_confirm_days if params.favorable_confirm_days is not None else 2
            confirmed_bear = len(regime_history) >= confirm_days and all(
                r == "BEAR" for r in regime_history[-confirm_days:]
            )
            confirmed_recover = (
                (len(regime_history) >= confirm_days and all(r != "BEAR" for r in regime_history[-confirm_days:]))
                or market_regime == "BULL"
            )

            max_empty = params.max_empty_days if params.max_empty_days is not None else 10
            force_entry = empty_days >= max_empty and market_regime != "BEAR"

            if confirmed_bear and not force_entry and params.allow_empty:
                if positions:
                    pending_orders = [{"code": c, "shares": None, "action": "BEAR_EXIT",
                                       "reason": f"市场BEAR空仓 上涨占比{up_ratio:.0%}"} for c in positions]
                    pending_rebalance = None
                    take_profit_level = 0
                    take_profit_base_shares.clear()
                    day_signals.append({"sector_code": "ALL", "sector_name": "全部", "direction": "SELL", "score": 0, "reason": f"市场BEAR空仓, 上涨占比{up_ratio:.0%}"})
                empty_days += 1
                bear_empty = True
            else:
                signals = quick_signals

                # ---- BEAR空仓回补门控：清仓后需连续N日非BEAR才允许重新建仓，
                #      避免弱反弹第一天即追高、在下跌中继被二次套牢（bear_reentry_days=0 维持原行为）
                reentry_days = getattr(params, "bear_reentry_days", 0) or 0
                if bear_empty and not force_entry and reentry_days > 0:
                    non_bear_days = 0
                    for _r in reversed(regime_history):
                        if _r == "BEAR":
                            break
                        non_bear_days += 1
                    if non_bear_days < reentry_days:
                        signals = []
                        day_signals.append({
                            "sector_code": "ALL", "sector_name": "全部", "direction": "SELL",
                            "score": 0,
                            "reason": f"BEAR空仓等待恢复确认: 当日{market_regime}, 连续非BEAR{non_bear_days}/{reentry_days}日",
                        })

                if force_entry and signals:
                    scaled = []
                    for sig in signals:
                        if sig.direction == SignalDirection.BUY:
                            scaled.append(TradeSignal(
                                signal_date=sig.signal_date, strategy_type=sig.strategy_type,
                                sector_code=sig.sector_code, sector_name=sig.sector_name,
                                direction=sig.direction, position_ratio=round(sig.position_ratio * 0.5, 4),
                                score=sig.score, reason=f"{sig.reason} [超时试探50%]",
                                rank=sig.rank, total_sectors=sig.total_sectors,
                            ))
                        else:
                            scaled.append(sig)
                    signals = scaled

                new_positions = {}
                buy_signals = [s for s in signals if s.direction.value == "BUY"]
                if buy_signals:
                    new_positions = {sig.sector_code: sig.position_ratio for sig in buy_signals}
                if new_positions:
                    bear_empty = False  # 成功生成新建仓信号，解除BEAR空仓状态

                signals_by_code = {}
                for sig in signals:
                    signals_by_code[sig.sector_code] = {"sector_name": sig.sector_name, "score": sig.score, "reason": sig.reason}

                for sig in signals:
                    day_signals.append({
                        "sector_code": sig.sector_code,
                        "sector_name": sig.sector_name,
                        "direction": sig.direction.value,
                        "score": round(sig.score, 2),
                        "reason": sig.reason,
                    })

                # T+1: 记录待执行调仓，次日开盘执行；同时保存信号日涨跌用于"继续持有"判断
                sell_codes = [s.sector_code for s in signals if s.direction.value == "SELL"]
                same_codes = set(new_positions.keys()) == set(positions.keys()) if new_positions and positions else False
                same_ratios = same_codes and all(
                    abs(new_positions.get(k, 0) - current_weights.get(k, 0)) < 0.01
                    for k in new_positions
                ) if same_codes else False
                if same_ratios and not sell_codes:
                    pass
                elif new_positions or sell_codes:
                    pending_rebalance = {
                        "new_positions": new_positions,
                        "signals_by_code": signals_by_code,
                        "signal_day_chg": {s.get("sector_code"): _safe_num(s.get("index_change_pct", 0)) / 100.0 for s in raw_sectors},
                        "signal_date": date,
                    }
                else:
                    if not positions:
                        empty_days += 1
                    else:
                        empty_days = 0

        # ========== 日终：记录持仓明细、快照与净值 ==========
        for code, pos in positions.items():
            price = (px.get(code) or {}).get("close", 0.0) or last_close.get(code, 0.0) or pos["avg_cost"]
            value = pos["shares"] * price
            _meta = sector_meta.get(code, {})
            day_position_detail[code] = {
                "weight": round(value / equity, 4) if equity > 0 else 0.0,
                "amount": round(value, 2),
                "sector_name": _meta.get("sector_name", "") or code,
                "etf_code": _meta.get("etf_code"),
                "etf_name": _meta.get("etf_name"),
            }

        daily_signals_out.append({
            "date": date,
            "signals": day_signals,
            # 当日状态：区分「空仓 / 持有不动 / 调仓」。
            # 无操作日 signals 为空，若前端不显示状态会误以为「信号不再生成」。
            "status": "EMPTY" if not positions else ("REBALANCE" if day_signals else "HOLD"),
            "strategy_return": round(strategy_daily_return * 100, 4),
            "benchmark_return": round(benchmark_return * 100, 4),
            "positions": day_position_detail,
            "total_position_value": round(sum(d["amount"] for d in day_position_detail.values()), 2),
            "cash": round(cash, 2),
            "total_asset": round(equity, 2),
        })

        if traded_today:
            _record_portfolio_snapshot(date)

        nav_curve.append({
            "date": date,
            "nav": round(equity, 2),
            "benchmark": round(float(bench_nav), 2),
            "stop_loss": stop_loss_triggered,
        })

        # 逐日回放是回测最耗时的环节，按每 5 个交易日汇报一次进度
        if on_progress is not None and (i % 5 == 0 or i == len(sorted_dates) - 1):
            on_progress(i + 1, len(sorted_dates))

    # ============ 计算回测指标 ============
    if initial_capital <= 0:
        return _empty_backtest_result(strategy_type, initial_capital, return_full)

    total_return = (equity / initial_capital) - 1
    trading_years = max(len(sorted_dates) / TRADING_DAYS_PER_YEAR, 0.01)
    annual_return = (1 + total_return) ** (1 / trading_years) - 1 if total_return > -1 else -1.0

    max_drawdown = 0.0
    if daily_nav:
        nav_array = np.array(daily_nav)
        peak = np.maximum.accumulate(nav_array)
        drawdown = (nav_array - peak) / np.where(peak > 0, peak, 1)
        max_drawdown = abs(float(drawdown.min())) if len(drawdown) > 0 else 0

    # 夏普：以无风险利率为基准计算超额收益（空仓日收益≈无风险利率，不会被零收益稀释波动）
    sharpe = 0.0
    daily_win_rate = 0.0
    max_consecutive_wins = 0
    max_consecutive_losses = 0
    if daily_returns:
        daily_arr = np.array(daily_returns)
        excess = daily_arr - rf_daily
        std = float(np.std(excess))
        # 波动低于 1e-6 视为无风险暴露（如全程空仓仅赚无风险利息），夏普不具备意义
        if std > 1e-6:
            sharpe = float((np.mean(excess) * TRADING_DAYS_PER_YEAR) / (std * np.sqrt(TRADING_DAYS_PER_YEAR)))
        daily_win_rate = float(np.mean(daily_arr > 0))
        cur_wins = cur_losses = 0
        for r in daily_arr:
            if r > 0:
                cur_wins += 1
                cur_losses = 0
            elif r < 0:
                cur_losses += 1
                cur_wins = 0
            else:
                cur_wins = cur_losses = 0
            max_consecutive_wins = max(max_consecutive_wins, cur_wins)
            max_consecutive_losses = max(max_consecutive_losses, cur_losses)

    # 交易级胜率与盈亏比（按每笔平仓的已实现盈亏，含交易成本）
    closed_trades = len(trade_pnls)
    win_rate = (sum(1 for p in trade_pnls if p > 0) / closed_trades) if closed_trades else 0.0
    gross_profit = sum(p for p in trade_pnls if p > 0)
    gross_loss = abs(sum(p for p in trade_pnls if p < 0))
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (round(gross_profit, 2) if gross_profit > 0 else 0.0)

    # 年化双边换手率 = 累计成交额 / 平均资产规模 / 年数
    avg_equity = float(np.mean(daily_nav)) if daily_nav else initial_capital
    turnover_rate = round(traded_amount_total / avg_equity / trading_years, 4) if avg_equity > 0 else 0.0

    empty_days_count = sum(1 for d in daily_signals_out if not d.get("positions"))
    empty_days_pct = round(empty_days_count / max(len(daily_signals_out), 1), 4)

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
        "final_capital": round(equity, 2),
        "total_return": round(float(total_return), 4),
        "annual_return": round(float(annual_return), 4),
        "max_drawdown": round(float(max_drawdown), 4),
        "sharpe_ratio": round(float(sharpe), 2),
        "win_rate": round(float(win_rate), 4),
        "daily_win_rate": round(float(daily_win_rate), 4),
        "trading_days": len(sorted_dates),
        "trade_count": max(1, trade_count_actual) if trade_count_actual > 0 else max(1, len(sorted_dates) // max(params.hold_days, 1)),
        "buy_count": buy_count,
        "sell_count": sell_count,
        "closed_trades": closed_trades,
        "total_commission": round(total_commission, 2),
        "total_stamp_tax": round(total_stamp_tax, 2),
        "total_slippage_cost": round(total_slippage_cost, 2),
        "total_trade_cost": round(total_commission + total_stamp_tax + total_slippage_cost, 2),
        "total_traded_amount": round(traded_amount_total, 2),
        "trade_count_actual": trade_count_actual,
        "turnover_rate": turnover_rate,
        "empty_days_pct": empty_days_pct,
        "profit_factor": profit_factor,
        "max_consecutive_wins": max_consecutive_wins,
        "max_consecutive_losses": max_consecutive_losses,
        "risk_free_rate": round(float(_safe_num(params.risk_free_rate)), 4),
        "params": {
            "top_n": params.top_n,
            "max_position": params.max_position,
            "hold_days": params.hold_days,
            "stop_loss": params.stop_loss,
            "capital_pct": params.capital_pct,
            "min_score_threshold": params.min_score_threshold,
            "score_gap_threshold": params.score_gap_threshold,
            "cooldown_days": params.cooldown_days,
            "cross_section_alpha": params.cross_section_alpha,
            "use_relative_score_gap": params.use_relative_score_gap,
            "relative_score_gap_ratio": params.relative_score_gap_ratio,
            "use_inverse_vol_weights": params.use_inverse_vol_weights,
            "risk_free_rate": params.risk_free_rate,
        },
    }

    if return_full:
        result["nav_curve"] = nav_curve
        result["daily_signals"] = daily_signals_out
        result["position_changes"] = position_changes
        result["portfolio_snapshots"] = portfolio_snapshots

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
        "daily_win_rate": 0.0,
        "trading_days": 0,
        "trade_count": 0,
        "buy_count": 0,
        "sell_count": 0,
        "closed_trades": 0,
        "total_commission": 0.0,
        "total_stamp_tax": 0.0,
        "total_slippage_cost": 0.0,
        "total_trade_cost": 0.0,
        "total_traded_amount": 0.0,
        "trade_count_actual": 0,
        "turnover_rate": 0.0,
        "empty_days_pct": 0.0,
        "profit_factor": 0.0,
        "max_consecutive_wins": 0,
        "max_consecutive_losses": 0,
        "risk_free_rate": 0.0,
        "params": {},
    }
    if return_full:
        result["nav_curve"] = []
        result["daily_signals"] = []
        result["position_changes"] = []
        result["portfolio_snapshots"] = []
    return result


@app.post("/factors/analyze")
def analyze_factors(request: FactorAnalyzeRequest):
    """因子分析 - 计算单个板块的所有因子得分"""
    try:
        sector_code = request.sector_code
        strategy_type_str = request.strategy_type
        date = request.date

        if not sector_code:
            raise HTTPException(status_code=400, detail="必须提供 sector_code")

        try:
            strategy_type = StrategyType(strategy_type_str)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"未知策略类型: {strategy_type_str}")

        # 查询板块数据（自动回退到最近有数据的日期）
        daily_data = None
        actual_date = date
        if date:
            daily_data = influx_query.query_daily_sectors(date, date)
            if not daily_data or date not in daily_data:
                daily_data = None

        if not daily_data:
            # 自动查找最近有数据的日期
            min_range, max_range = influx_query.get_available_date_range()
            if max_range:
                actual_date = max_range
                daily_data = influx_query.query_daily_sectors(actual_date, actual_date)

        if not daily_data or actual_date not in daily_data:
            raise HTTPException(status_code=404, detail="无可用数据，请先采集历史数据")

        sector_data = None
        for s in daily_data[actual_date]:
            if s.get("sector_code") == sector_code:
                sector_data = s
                break

        if not sector_data:
            raise HTTPException(status_code=404, detail=f"板块 {sector_code} 无数据")

        # 查询历史数据（用于技术指标计算）
        start_date = (datetime.strptime(actual_date, "%Y-%m-%d") - timedelta(days=60)).strftime("%Y-%m-%d")
        history_data = influx_query.query_sector_history(sector_code, start_date, actual_date)
        if history_data:
            sector_data["_history"] = history_data

        from .combiner import DEFAULT_WEIGHTS

        abs_score, _val_score, category_detail, engine_fallback, factor_results = scoring_model._calculate_composite_score(
            sector_data, strategy_type, StrategyParams(), history_data, None
        )

        weights = DEFAULT_WEIGHTS.get(strategy_type.value, DEFAULT_WEIGHTS["MODERATE"])

        factors = []
        if factor_results:
            for r in factor_results:
                factors.append({
                    "name": r.name,
                    "category": r.category.value,
                    "raw_value": r.raw_value,
                    "score": r.score,
                    "weight": r.weight,
                    "confidence": r.confidence,
                    "detail": r.detail,
                })

        return success_response(data={
            "sector_code": sector_code,
            "sector_name": sector_data.get("sector_name", ""),
            "date": actual_date,
            "strategy_type": strategy_type.value,
            "composite_score": abs_score,
            "abs_composite_score": abs_score,
            "rank_composite_score": None,
            "engine_fallback": engine_fallback,
            "factors": factors,
            "note": "单独分析仅计算绝对评分，批量排名页面会结合截面排名计算混合评分（0.65*绝对 + 0.35*截面）",
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"因子分析失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class FactorBatchRequest(BaseModel):
    """批量因子分析请求"""
    date: str = ""
    strategy_type: str = "MODERATE"
    sector_codes: list[str] = []


# 批量因子结果缓存：因子只依赖"交易日 + 策略类型 + 板块范围 + 当日数据本身"。
# 命中时省掉一次 60 天历史查询 + 90 个板块的因子计算（实测 1.5s -> 0.05s），
# 前端来回切页面不再重算。缓存键里带当日数据指纹，手动重采集或补采后自动失效。
_FACTOR_BATCH_CACHE: dict[tuple, dict] = {}
_FACTOR_BATCH_CACHE_MAX = 64
_FACTOR_BATCH_CACHE_LOCK = threading.Lock()


def _daily_data_fingerprint(sectors: list[dict]) -> str:
    """当日板块数据的指纹：任一板块任一标量字段变化都会改变结果

    只取标量字段（numpy 数值也算），跳过 _history 这类内部附加字段。
    """
    parts = []
    for s in sectors:
        fields = ",".join(
            f"{k}={s.get(k)}"
            for k in sorted(s)
            if not k.startswith("_")
            and not isinstance(s.get(k), (dict, list, tuple, type(None)))
        )
        parts.append(f"{s.get('sector_code')}[{fields}]")
    return hashlib.md5("|".join(sorted(parts)).encode()).hexdigest()


@app.post("/factors/batch")
def analyze_factors_batch(request_body: FactorBatchRequest):
    """批量因子分析 - 计算多个板块的因子得分并排名

    同步路由（非 async）：内部是 InfluxDB 查询 + numpy 计算的阻塞调用，
    放在 async 路由里会独占事件循环，前端并发发两个请求就要排队（实测 1.5s -> 3.0s）。
    """
    try:
        date = request_body.date
        strategy_type = StrategyType(request_body.strategy_type)

        # 查询数据（自动回退到最近有数据的日期）
        daily_data = None
        actual_date = date
        if date:
            daily_data = influx_query.query_daily_sectors(date, date)
            if not daily_data or date not in daily_data:
                daily_data = None

        if not daily_data:
            min_range, max_range = influx_query.get_available_date_range()
            if max_range:
                actual_date = max_range
                daily_data = influx_query.query_daily_sectors(actual_date, actual_date)

        if not daily_data or actual_date not in daily_data:
            raise HTTPException(status_code=404, detail="无可用数据")

        # 数据已取回（当日 90 条，约 0.05 秒），用它算指纹后查缓存
        cache_key = (
            actual_date,
            strategy_type.value,
            tuple(sorted(request_body.sector_codes)),
            _daily_data_fingerprint(daily_data[actual_date]),
        )
        with _FACTOR_BATCH_CACHE_LOCK:
            cached = _FACTOR_BATCH_CACHE.get(cache_key)
            if cached is not None:
                return success_response(data=cached)

        from .factors import FactorRegistry
        from .combiner import FactorCombiner, DEFAULT_WEIGHTS

        weights = DEFAULT_WEIGHTS.get(strategy_type.value, DEFAULT_WEIGHTS["MODERATE"])
        combiner = FactorCombiner()
        alpha = max(0.0, min(1.0, StrategyParams().cross_section_alpha))

        sectors = daily_data[actual_date]
        if request_body.sector_codes:
            sectors = [s for s in sectors if s.get("sector_code") in request_body.sector_codes]

        context = scoring_model._build_cross_section_context(sectors)
        all_fr: dict = {}
        abs_by_code: dict[str, float] = {}
        meta_by_code: dict[str, dict] = {}

        # 历史序列一次批量取回：逐板块查询是 90 板块 × 3 次 InfluxQL 往返（实测 6.2s），
        # 批量后只剩 3 次（资金流 + 北向资金 + K线），输出字段口径不变。
        hist_start = (datetime.strptime(actual_date, "%Y-%m-%d") - timedelta(days=60)).strftime("%Y-%m-%d")
        history_map = influx_query.query_all_sector_history_map(hist_start, actual_date)

        for sector in sectors:
            code = sector.get("sector_code")
            if not code:
                continue
            try:
                history_data = history_map.get(str(code)) or []
                if history_data:
                    sector["_history"] = history_data
                factor_results = FactorRegistry.calculate_all(sector, history_data, context)
                abs_score, _ = combiner.combine_weighted(factor_results, weights)
                all_fr[str(code)] = factor_results
                abs_by_code[str(code)] = abs_score
                meta_by_code[str(code)] = {
                    "sector_code": code,
                    "sector_name": sector.get("sector_name", ""),
                }
            except Exception:
                continue

        rank_by_code: dict[str, float] = {}
        if len(all_fr) >= 3:
            rank_by_code = combiner.combine_ranking(all_fr, weights)

        results = []
        for code, meta in meta_by_code.items():
            abs_s = abs_by_code[code]
            rk = rank_by_code.get(code, abs_s)
            final = round((1 - alpha) * abs_s + alpha * rk, 2) if rank_by_code else round(abs_s, 2)
            
            # 获取板块原始数据
            sector_data = next((s for s in sectors if s.get("sector_code") == code), {})
            
            # 计算类别得分（与combiner逻辑一致，按confidence加权）
            category_scores = {}
            for fr in all_fr.get(code, []):
                cat = fr.category.value if hasattr(fr, 'category') else 'unknown'
                if cat not in category_scores:
                    category_scores[cat] = {"score": 0, "weight_sum": 0}
                eff_w = fr.weight * max(fr.confidence, 0.0)
                category_scores[cat]["score"] += fr.score * eff_w
                category_scores[cat]["weight_sum"] += eff_w
            
            category_result = {}
            for cat, v in category_scores.items():
                if v["weight_sum"] > 1e-12:
                    category_result[cat] = round(v["score"] / v["weight_sum"], 2)
            
            results.append({
                **meta,
                "composite_score": final,
                "abs_composite_score": round(abs_s, 2),
                "rank_composite_score": round(rk, 2) if rank_by_code else None,
                "change_pct": round(sector_data.get("index_change_pct", 0), 2),
                "main_inflow": round(sector_data.get("main_net_inflow", 0) / 1e8, 2),
                "north_inflow": round(sector_data.get("north_net_inflow", 0) / 1e8, 2),
                "category_scores": category_result,
            })

        results.sort(key=lambda x: x["composite_score"], reverse=True)
        for i, r in enumerate(results):
            r["rank"] = i + 1

        payload = {"date": actual_date, "strategy_type": strategy_type.value, "rankings": results}
        with _FACTOR_BATCH_CACHE_LOCK:
            if len(_FACTOR_BATCH_CACHE) >= _FACTOR_BATCH_CACHE_MAX:
                _FACTOR_BATCH_CACHE.clear()
            _FACTOR_BATCH_CACHE[cache_key] = payload

        return success_response(data=payload)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"批量因子分析失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/factors/config")
def get_factor_config():
    """获取因子配置"""
    try:
        from .factors import FactorRegistry
        from .combiner import DEFAULT_WEIGHTS
        return success_response(data={
            "weights": {k: v.model_dump() for k, v in DEFAULT_WEIGHTS.items()},
            "factors": [
                {"name": f.name, "category": f.category.value, "default_weight": f.default_weight}
                for f in FactorRegistry.get_all().values()
            ],
        })
    except Exception as e:
        logger.error(f"获取因子配置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/backtest/history")
def get_backtest_history(
    strategy_type: StrategyType = None,
    authorization: str | None = Header(None, alias="Authorization"),
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    """获取当前账号的回测历史记录"""
    actor = _resolve_actor(authorization, x_internal_token)
    scope = user_scope(actor.user_id)
    try:
        results = []
        if strategy_type:
            keys = [f"{scope}:backtest_history:{strategy_type.value}"]
        else:
            keys = [f"{scope}:backtest_history:{st.value}" for st in StrategyType]

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
def get_backtest_detail(
    bt_id: str,
    authorization: str | None = Header(None, alias="Authorization"),
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    """获取当前账号的回测详情（他人 bt_id 不可见）"""
    actor = _resolve_actor(authorization, x_internal_token)
    raw = redis_mgr.get(f"{user_scope(actor.user_id)}:backtest:{bt_id}")
    if raw:
        return {"code": 200, "data": json.loads(raw)}
    raise HTTPException(status_code=404, detail="回测记录不存在")


@app.get("/data/availability")
def get_data_availability():
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
def get_cache_stats():
    """获取缓存统计信息"""
    try:
        info = redis_mgr.info("memory")
        keyspace = redis_mgr.info("keyspace")
        db_idx = settings.redis_db
        db_info = keyspace.get(f"db{db_idx}", {})
        total_keys = db_info.get("keys", 0) if isinstance(db_info, dict) else 0

        categories = {}
        # 用户数据统一挂在 user:{id}: 下，统计时用通配覆盖所有账号
        patterns = [
            ("backtest_result", "user:*:backtest:*"),
            ("backtest_history", "user:*:backtest_history:*"),
            ("signals", "user:*:signals:*"),
            ("strategy_configs", "user:*:strategy_configs"),
            ("market_regime", "user:*:market_regime:*"),
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
def clear_all_cache(x_admin_token: str = Header(default="")):
    """清空当前数据库的所有缓存（需要管理员令牌）"""
    admin_token = os.environ.get("ADMIN_TOKEN", "")
    if not admin_token:
        raise HTTPException(status_code=403, detail="管理员令牌未配置，拒绝操作")
    if x_admin_token != admin_token:
        raise HTTPException(status_code=401, detail="无效的管理员令牌")
    try:
        redis_mgr.flushdb()
        logger.info("缓存已全部清空")
        return {"code": 200, "message": "缓存已全部清空"}
    except Exception as e:
        logger.error(f"清空缓存失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/cache/expired")
def clear_expired_cache():
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
def get_database_status():
    """获取数据库状态信息"""
    try:
        # PostgreSQL状态
        pg_status = "unavailable"
        try:
            import psycopg2
            conn = psycopg2.connect(
                host=settings.postgres_host,
                database=settings.postgres_db,
                user=settings.postgres_user,
                password=settings.postgres_password,
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


# 个人偏好（按用户保存）：实时推送开关与订阅的策略档位
USER_SETTINGS_KEYS = {"ws_push_enabled", "ws_push_strategy_types"}
# 系统级参数（全局一份，仅管理员可改）：数据源、缓存天数、调度时间
SYSTEM_SETTINGS_KEYS = {
    "data_source",
    "data_source_config",
    "cache_ttl_days",
    "scheduler_enabled",
    "scheduler_times",
}
ALLOWED_SETTINGS_KEYS = USER_SETTINGS_KEYS | SYSTEM_SETTINGS_KEYS

SETTINGS_DEFAULTS = {
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
        "collect": "15:30",
        "calculate": "15:35",
        "north_bound": "16:00",
    },
}


def _user_settings_key(user_id: int, key: str) -> str:
    return f"{user_scope(user_id)}:settings:{key}"


def _parse_setting(raw):
    """解析历史遗留的非 JSON 格式（str(True) / str(123)）"""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        if raw == "True":
            return True
        if raw == "False":
            return False
        try:
            return int(raw)
        except (ValueError, TypeError):
            return raw


def _read_setting(redis_key: str):
    raw = redis_mgr.get(redis_key)
    return None if raw is None else _parse_setting(raw)


def _migrate_legacy_user_settings():
    """历史全局个人设置归并到管理员账号（幂等）

    改造前 ws_push_* 存在 settings:* 全局键里，多用户共用一份。这里把它们搬到
    user:1 下（管理员），并删除旧键，避免"全局设置"与新口径并存造成误读。
    """
    for key in USER_SETTINGS_KEYS:
        legacy_key = f"settings:{key}"
        legacy_value = redis_mgr.get(legacy_key)
        if legacy_value is None:
            continue
        target_key = _user_settings_key(ADMIN_USER_ID, key)
        if redis_mgr.get(target_key) is None:
            redis_mgr.set(target_key, legacy_value)
            logger.info(f"历史设置迁移到管理员账号: {legacy_key} -> {target_key}")
        redis_mgr.delete(legacy_key)


@app.get("/settings")
def get_system_settings(authorization: str | None = Header(None, alias="Authorization")):
    """获取设置：个人偏好取自当前用户，系统级参数全局共享"""
    user = _require_user(authorization)
    try:
        settings_map = dict(SETTINGS_DEFAULTS)
        for key in SYSTEM_SETTINGS_KEYS:
            value = _read_setting(f"settings:{key}")
            if value is not None:
                settings_map[key] = value
        for key in USER_SETTINGS_KEYS:
            value = _read_setting(_user_settings_key(user.user_id, key))
            if value is not None:
                settings_map[key] = value
        return {"code": 200, "data": settings_map}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取设置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/settings")
def update_system_settings(settings_body: dict, authorization: str | None = Header(None, alias="Authorization")):
    """更新设置：个人偏好写入当前用户，系统级参数仅管理员可改"""
    user = _require_user(authorization)
    invalid_keys = set(settings_body.keys()) - ALLOWED_SETTINGS_KEYS
    if invalid_keys:
        raise HTTPException(status_code=400, detail=f"不允许的设置项: {', '.join(invalid_keys)}")

    system_updates = set(settings_body.keys()) & SYSTEM_SETTINGS_KEYS
    if system_updates and not user.is_admin:
        raise HTTPException(
            status_code=403,
            detail=f"系统级设置仅管理员可修改: {', '.join(sorted(system_updates))}",
        )

    try:
        updated = {}
        for key, value in settings_body.items():
            redis_key = _user_settings_key(user.user_id, key) if key in USER_SETTINGS_KEYS else f"settings:{key}"
            redis_mgr.set(redis_key, json.dumps(value, ensure_ascii=False))
            updated[key] = value
        logger.info(f"设置已更新: user={user.user_id}, keys={list(updated.keys())}")
        return {"code": 200, "message": "设置已更新", "data": updated}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新设置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/data/replay/dates")
def get_replay_dates(start_date: str = None, end_date: str = None):
    """获取可用于回放的交易日列表"""
    try:
        dates = influx_query.get_trading_dates()
        if start_date:
            dates = [d for d in dates if d >= start_date]
        if end_date:
            dates = [d for d in dates if d <= end_date]
        return {"code": 200, "data": dates}
    except Exception as e:
        logger.error(f"获取回放日期列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/data/replay/sectors")
def get_replay_sectors():
    """获取所有可用的板块列表"""
    try:
        sectors = influx_query.get_sector_list()
        return {"code": 200, "data": sectors}
    except Exception as e:
        logger.error(f"获取板块列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/data/replay/sector/{sector_code}")
def get_replay_sector_history(sector_code: str, start_date: str = None, end_date: str = None):
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
def get_replay_day_data(date: str, sector_code: str = None):
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


@app.get("/data/replay/heatmap")
def get_replay_heatmap(days: int = 5):
    """板块资金流热力图：一次范围查询后在服务端按板块聚合

    前端原来逐日拉 /data/replay/day/{date}（5/10/20 个串行请求，每个 0.1~0.34s），
    这里一次 InfluxQL 取回区间数据，聚合口径与前端保持一致：
    每个板块在所有出现过的交易日上取算术平均，缺失字段按 0 计入。
    """
    try:
        days = max(1, min(int(days), 60))
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        daily_data = influx_query.query_daily_sectors(start_date, end_date)
        dates = sorted(daily_data.keys())

        acc: dict[str, dict] = {}
        for date in dates:
            for sector in daily_data[date]:
                name = sector.get("sector_name") or sector.get("sector_code") or ""
                if not name:
                    continue
                item = acc.setdefault(name, {"inflow_sum": 0.0, "pct_sum": 0.0, "count": 0})
                item["inflow_sum"] += float(sector.get("main_net_inflow") or 0.0)
                item["pct_sum"] += float(sector.get("index_change_pct") or 0.0)
                item["count"] += 1

        sectors = [
            {
                "sector_name": name,
                "main_net_inflow": v["inflow_sum"] / v["count"] if v["count"] else 0.0,
                "index_change_pct": v["pct_sum"] / v["count"] if v["count"] else 0.0,
                "days": v["count"],
            }
            for name, v in acc.items()
        ]
        sectors.sort(key=lambda x: x["main_net_inflow"], reverse=True)
        return {"code": 200, "data": {"dates": dates, "days": days, "sectors": sectors}}
    except Exception as e:
        logger.error(f"获取热力图数据失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# 全局叠加回测进度状态（与寻优同构：后台线程执行，请求立即返回）
_overlay_progress = {"active": False, "completed": 0, "total": 1, "error": None}
# 最近一次完成的叠加回测完整结果（前端轮询拉取）
_overlay_result: dict | None = None

# 全局寻优进度状态
_optimization_progress = {
    "active": False,
    "completed": 0,
    "total": 0,
    "best_return": 0.0,
    "best_sharpe": 0.0,
}# 最近一次寻优的完整结果（完成后写入，供前端轮询拉取）
_optimization_result: dict = None


def _run_optimization(daily_data, sorted_dates, strategy_type, initial_capital, n_trials, sh_index_returns=None, n_jobs=1, oos_dates=None):
    """执行 Optuna 优化（支持并行 + 进度日志 + 样本外验证）

    优化目标为夏普比率（已扣无风险利率、空仓期按无风险利率计息）。
    不再使用 总收益/最大回撤：该比值在回撤趋零时会被无限放大，会系统性地
    选出"仓位极小、几乎不交易"的无效参数。

    Args:
        n_jobs: 并行数。1=串行可复现，>1=并行但结果不可复现
        oos_dates: 样本外交易日列表；非空时先在剩余区间寻优，再在该区间做样本外验证
    """
    global _optimization_result
    import optuna
    import threading
    optuna.logging.set_verbosity(optuna.logging.WARNING)

    if n_jobs > 1:
        logger.warning(f"并行模式(n_jobs={n_jobs})下结果不可复现，如需复现请设 n_jobs=1")
    n_jobs = min(n_jobs, n_trials)

    # 训练/样本外切分：样本外区间不参与寻优，仅用于验证参数泛化能力
    oos_set = set(oos_dates or [])
    train_dates = [d for d in sorted_dates if d not in oos_set] if oos_set else list(sorted_dates)
    if len(train_dates) < 10:
        # 训练区间过短时退化为全样本寻优（接口层默认仅在 >=60 个交易日时切分）
        train_dates = list(sorted_dates)
        oos_set = set()

    progress_lock = threading.Lock()
    _optimization_progress.update({
        "active": True, "completed": 0, "total": n_trials + (1 if oos_set else 0),
        "best_return": 0.0, "best_sharpe": 0.0,
    })

    try:
        # 预加载板块历史一次，全部试验复用（避免每次回测重复查询InfluxDB）
        history_cache = _load_sector_history_cache(train_dates)

        def objective(trial):
            params_dict = _suggest_params(trial, strategy_type)
            params = StrategyParams(**params_dict)
            result = _run_backtest_core(daily_data, train_dates, strategy_type, params, initial_capital,
                                        sh_index_returns=sh_index_returns, history_cache=history_cache)
            sharpe = result["sharpe_ratio"]
            # 惩罚无效解：样本内交易笔数过少时夏普不具备统计意义
            score = sharpe if result["trade_count_actual"] >= 3 else sharpe - 10.0

            # 缓存回测结果到 trial user attributes，避免后续重算
            trial.set_user_attr("total_return", result["total_return"])
            trial.set_user_attr("annual_return", result["annual_return"])
            trial.set_user_attr("max_drawdown", result["max_drawdown"])
            trial.set_user_attr("sharpe_ratio", sharpe)
            trial.set_user_attr("win_rate", result["win_rate"])
            trial.set_user_attr("turnover_rate", result["turnover_rate"])
            trial.set_user_attr("profit_factor", result["profit_factor"])
            trial.set_user_attr("trade_count", result["trade_count_actual"])
            trial.set_user_attr("params", params_dict)

            with progress_lock:
                _optimization_progress["completed"] += 1
                if result["total_return"] > _optimization_progress["best_return"]:
                    _optimization_progress["best_return"] = result["total_return"]
                if sharpe > _optimization_progress["best_sharpe"]:
                    _optimization_progress["best_sharpe"] = sharpe

            return score

        study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=42))
        study.optimize(objective, n_trials=n_trials, n_jobs=n_jobs, show_progress_bar=False)

        # 从缓存的 trial attributes 读取结果（不重跑回测）
        all_results = []
        for trial in study.trials:
            if trial.state == optuna.trial.TrialState.COMPLETE and trial.user_attrs:
                all_results.append({
                    "params": trial.user_attrs.get("params", {}),
                    "total_return": trial.user_attrs.get("total_return", 0),
                    "trial": trial.number,
                    "annual_return": trial.user_attrs.get("annual_return", 0),
                    "max_drawdown": trial.user_attrs.get("max_drawdown", 0),
                    "sharpe_ratio": trial.user_attrs.get("sharpe_ratio", 0),
                    "win_rate": trial.user_attrs.get("win_rate", 0),
                    "turnover_rate": trial.user_attrs.get("turnover_rate", 0),
                    "profit_factor": trial.user_attrs.get("profit_factor", 0),
                    "trade_count": trial.user_attrs.get("trade_count", 0),
                    "objective_score": round(trial.value, 4) if trial.value else 0,
                })

        all_results.sort(key=lambda x: x["sharpe_ratio"], reverse=True)

        best_params_dict = _suggest_params(study.best_trial, strategy_type)
        best_params = StrategyParams(**best_params_dict)
        final_result = _run_backtest_core(daily_data, train_dates, strategy_type, best_params, initial_capital,
                                          return_full=True, sh_index_returns=sh_index_returns, history_cache=history_cache)

        # 样本外验证：用训练得到的最优参数在未参与寻优的区间回测（历史预热仅取自该区间之前）
        oos_result = None
        if oos_set:
            oos_sorted = sorted(oos_set)
            oos_history = _load_sector_history_cache(oos_sorted)
            # 样本外必须以「训练集结束时的权益」为初始资金：若同样按 100 万起算，
            # 与训练集拼接后收益曲线会在切分点处跳变（不连续）。
            oos_capital = final_result.get("final_capital") or initial_capital
            # 基准净值同样继承训练集末的值：否则策略曲线连续、基准曲线却在切分点跳变
            train_nav = final_result.get("nav_curve") or []
            oos_bench_start = train_nav[-1].get("benchmark") if train_nav else None
            logger.info(f"样本外初始资金={oos_capital:.2f}, 基准起点={oos_bench_start}")
            oos_result = _run_backtest_core(daily_data, oos_sorted, strategy_type, best_params, oos_capital,
                                            return_full=True, sh_index_returns=sh_index_returns, history_cache=oos_history,
                                            initial_bench_capital=oos_bench_start)
            with progress_lock:
                _optimization_progress["completed"] += 1
            logger.info(f"样本外验证 {oos_sorted[0]}~{oos_sorted[-1]}: 收益={oos_result['total_return']*100:.2f}%, "
                        f"回撤={oos_result['max_drawdown']*100:.2f}%, 夏普={oos_result['sharpe_ratio']}")

        logger.info(f"自动寻优完成: {len(all_results)} 次有效试验({n_jobs}线程并行), "
                    f"样本内收益={final_result['total_return']*100:.2f}%, 夏普={final_result['sharpe_ratio']}")

        # 全区间汇总：训练集 + 样本外拼接后重算指标，使顶部指标与完整曲线口径一致。
        # （此前顶部指标取自训练集 best_result，与拼接曲线末端的资金对不上）
        combined_summary = None
        if oos_result:
            combined_nav = (final_result.get("nav_curve") or []) + (oos_result.get("nav_curve") or [])
            combined_summary = _summarize_nav_curve(
                combined_nav, getattr(best_params, "risk_free_rate", 0.02))
            if combined_summary:
                combined_summary["trade_count_actual"] = (
                    final_result.get("trade_count_actual", 0)
                    + oos_result.get("trade_count_actual", 0))
                logger.info(
                    f"全区间汇总: {len(combined_nav)} 日, "
                    f"总收益={combined_summary['total_return'] * 100:.2f}%, "
                    f"回撤={combined_summary['max_drawdown'] * 100:.2f}%, "
                    f"夏普={combined_summary['sharpe_ratio']}")

        result_payload = {
            "combined_summary": combined_summary,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "strategy_type": strategy_type.value if hasattr(strategy_type, "value") else str(strategy_type),
            "n_trials": n_trials,
            "best_params": best_params_dict,
            "best_result": final_result,
            "all_results": all_results,
            "out_of_sample": oos_result,
            "train_range": [train_dates[0], train_dates[-1]] if train_dates else [],
            "oos_range": [sorted(oos_set)[0], sorted(oos_set)[-1]] if oos_set else [],
        }
        _optimization_result = result_payload
        # 追加历史摘要（最新在前），仅保留最近 20 次；完整结果另存归档供「查看详情」
        opt_id = result_payload["created_at"]
        _optimization_history.insert(0, {
            "id": opt_id,
            "created_at": opt_id,
            "strategy_type": result_payload["strategy_type"],
            "n_trials": n_trials,
            "trial_count": len(all_results),
            "sharpe_ratio": final_result.get("sharpe_ratio", 0),
            "total_return": final_result.get("total_return", 0),
            "max_drawdown": final_result.get("max_drawdown", 0),
            "train_range": result_payload["train_range"],
        })
        _optimization_archive[opt_id] = result_payload
        # 淘汰超出 20 条的旧记录时同步清归档，避免内存无限增长
        for old in _optimization_history[20:]:
            _optimization_archive.pop(old.get("id"), None)
        del _optimization_history[20:]
        return {"code": 200, "data": result_payload}
    finally:
        # 任何异常都必须复位，否则后续寻优会被 active 标志永久阻塞
        _optimization_progress["active"] = False


# 历史寻优记录摘要（最新在前，最多 20 条），供前端按时间倒序展示
_optimization_history: list = []
# 历史记录对应的完整结果归档，按 id（created_at）索引，供「查看详情」拉取
_optimization_archive: dict = {}


@app.get("/data/replay/strategy-optimize/history")
def get_optimize_history():
    """获取历史寻优记录（最新在前，按完成时间倒序）"""
    return {"code": 200, "data": list(_optimization_history)}


@app.get("/data/replay/strategy-optimize/history/{opt_id}")
def get_optimize_history_detail(opt_id: str):
    """获取某次历史寻优的完整结果，供点击历史记录查看详情"""
    result = _optimization_archive.get(opt_id)
    if not result:
        raise HTTPException(status_code=404, detail="该寻优记录已过期或不存在")
    return {"code": 200, "data": result}


@app.get("/data/replay/optimize-progress")
def get_optimize_progress():
    """获取当前寻优进度"""
    return {"code": 200, "data": dict(_optimization_progress)}


@app.get("/data/replay/strategy-optimize/result")
def get_optimize_result():
    """获取最近一次完成的寻优结果"""
    global _optimization_result
    if _optimization_progress["active"]:
        return {"code": 200, "data": {"status": "running", "result": None}}
    return {"code": 200, "data": {"status": "done", "result": _optimization_result}}


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
        n_jobs = request_body.get("n_jobs", 1)  # 默认串行可复现

        if not start_date or not end_date:
            raise HTTPException(status_code=400, detail="必须提供 start_date 和 end_date")

        try:
            strategy_type = StrategyType(strategy_type_str)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"未知策略类型: {strategy_type_str}")

        daily_data = influx_query.query_daily_sectors(start_date, end_date)
        if not daily_data:
            raise HTTPException(status_code=404, detail="该时间范围内无历史数据")

        # 已有寻优任务进行中则拒绝重复启动
        if _optimization_progress["active"]:
            raise HTTPException(status_code=409, detail="已有寻优任务运行中，请稍候")

        sorted_dates = sorted(daily_data.keys())

        # 留出后 30% 作为样本外区间（不参与寻优），避免在同一段数据上选参数又报收益
        oos_dates = None
        if request_body.get("walk_forward", True) and len(sorted_dates) >= 60:
            split = int(len(sorted_dates) * 0.7)
            oos_dates = sorted_dates[split:]
            logger.info(f"自动寻优: {len(sorted_dates)} 个交易日, 最多 {n_trials} 次试验, "
                        f"样本外 {oos_dates[0]}~{oos_dates[-1]} ({len(oos_dates)}天)")
        else:
            logger.info(f"自动寻优: {len(sorted_dates)} 个交易日, 最多 {n_trials} 次试验")

        loop = asyncio.get_event_loop()

        # 获取上证指数数据作为基准
        sh_returns = await loop.run_in_executor(
            None,
            lambda: influx_query.query_sh_index_returns(sorted_dates[0], sorted_dates[-1]),
        )

        # 后台线程执行寻优（可能远超HTTP超时），请求立即返回，前端轮询进度后拉取结果
        global _optimization_result
        _optimization_result = None
        loop.run_in_executor(
            None,
            lambda: _run_optimization(daily_data, sorted_dates, strategy_type, initial_capital, n_trials,
                                      sh_index_returns=sh_returns, n_jobs=n_jobs, oos_dates=oos_dates),
        )
        return {"code": 200, "data": {"accepted": True, "message": "寻优已启动，请通过进度接口查询"}}
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
        min_score = trial.suggest_float("min_score_threshold", 0.5, 2.5, step=0.5)
        return {
            **base,
            "top_n": trial.suggest_int("top_n", 1, 3),
            "max_position": 1.0,
            "hold_days": trial.suggest_int("hold_days", 3, 6),
            "capital_pct": trial.suggest_float("capital_pct", 0.5, 1.0, step=0.1),
            "stop_loss": trial.suggest_float("stop_loss", 0.05, 0.12, step=0.01),
            "min_score_threshold": min_score,
            "score_gap_threshold": trial.suggest_float("score_gap_threshold", 0.5, 2.0, step=0.5),
            "cooldown_days": trial.suggest_int("cooldown_days", 1, 6),
            "market_bear_threshold": trial.suggest_float("market_bear_threshold", 0.30, 0.45, step=0.05),
            "favorable_confirm_days": trial.suggest_int("favorable_confirm_days", 1, 2),
            "min_score_keep": min(min_score + 0.5, 2.5),
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


def _run_overlay_task(daily_data, sorted_dates, strategy_type, params, initial_capital, sh_returns):
    """后台执行叠加回测，结果写入全局 _overlay_result。
    与寻优同构：HTTP 请求立即返回，计算在线程池进行，前端轮询进度/结果。
    """
    global _overlay_result
    try:
        result_data = _run_backtest_core(
            daily_data, sorted_dates, strategy_type, params, initial_capital,
            return_full=True, sh_index_returns=sh_returns,
        )
        nav_curve = result_data.pop("nav_curve", [])
        daily_signals = result_data.pop("daily_signals", [])
        position_changes = result_data.pop("position_changes", [])
        portfolio_snapshots = result_data.pop("portfolio_snapshots", [])
        _overlay_result = {
            "summary": result_data,
            "nav_curve": nav_curve,
            "daily_signals": daily_signals,
            "position_changes": position_changes,
            "portfolio_snapshots": portfolio_snapshots,
        }
        _overlay_progress.update({"active": False, "completed": 1, "total": 1, "error": None})
        logger.info(f"策略叠加回测完成: {len(sorted_dates)} 个交易日")
    except Exception as e:
        logger.error(f"后台策略叠加回测失败: {e}")
        _overlay_result = None
        _overlay_progress.update({"active": False, "completed": 0, "total": 1, "error": str(e)})


@app.get("/data/replay/strategy-overlay/progress")
def get_overlay_progress():
    """叠加回测进度（后台任务模式）"""
    return {"code": 200, "data": dict(_overlay_progress)}


@app.get("/data/replay/strategy-overlay/result")
def get_overlay_result():
    """最近一次完成的叠加回测完整结果"""
    if _overlay_progress["active"]:
        return {"code": 200, "data": {"status": "running", "result": None, "error": None}}
    if _overlay_progress.get("error"):
        return {"code": 200, "data": {"status": "failed", "result": None, "error": _overlay_progress["error"]}}
    return {"code": 200, "data": {"status": "done", "result": _overlay_result, "error": None}}


@app.post("/data/replay/strategy-overlay")
async def replay_strategy_overlay(
    request_body: dict,
    authorization: str | None = Header(None, alias="Authorization"),
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    """数据回放 - 策略叠加：启动后台任务，立即返回；前端轮询进度后拉取结果。
    与寻优同构，计算不依赖前端连接——切页/刷新都不会中断回测。
    """
    global _overlay_result
    actor = _resolve_actor(authorization, x_internal_token)
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

        config = _user_configs(actor.user_id).get(strategy_type)
        if not config:
            raise HTTPException(status_code=400, detail="未知策略类型")
        params = StrategyParams(**params_override) if params_override else config.params

        daily_data = influx_query.query_daily_sectors(start_date, end_date)
        if not daily_data:
            raise HTTPException(status_code=404, detail="该时间范围内无历史数据")

        if _overlay_progress["active"]:
            raise HTTPException(status_code=409, detail="已有叠加回测运行中，请稍候")

        sorted_dates = sorted(daily_data.keys())
        loop = asyncio.get_event_loop()
        sh_returns = await loop.run_in_executor(
            None,
            lambda: influx_query.query_sh_index_returns(sorted_dates[0], sorted_dates[-1]),
        )

        _overlay_result = None
        _overlay_progress.update({"active": True, "completed": 0, "total": 1, "error": None})
        loop.run_in_executor(
            None,
            lambda: _run_overlay_task(daily_data, sorted_dates, strategy_type, params, initial_capital, sh_returns),
        )
        return {"code": 200, "data": {"accepted": True, "message": "叠加回测已启动，请通过进度接口查询"}}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"启动策略叠加回测失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 策略工坊 ====================
# 用户自定义策略全部按 JWT 的 userId 归属；公开策略只读，复制才进入自己的账户。


def _workshop_strategy(user_id: int, strategy_id: int) -> dict:
    strategy = workshop.get_strategy(user_id, strategy_id)
    if not strategy:
        raise HTTPException(status_code=404, detail="策略不存在")
    return strategy


@app.post("/workshop/strategies")
async def workshop_create_strategy(
    payload: workshop.StrategyPayload,
    authorization: str | None = Header(None, alias="Authorization"),
):
    user = _require_user(authorization)
    try:
        return {"code": 200, "data": workshop.create_strategy(user.user_id, payload)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/workshop/strategies")
async def workshop_list_strategies(
    scope: str = "mine",
    authorization: str | None = Header(None, alias="Authorization"),
):
    user = _require_user(authorization)
    if scope not in {"mine", "public"}:
        raise HTTPException(status_code=400, detail="scope 仅支持 mine/public")
    return {"code": 200, "data": workshop.list_strategies(user.user_id, scope)}


@app.get("/workshop/strategies/{strategy_id}")
async def workshop_get_strategy(
    strategy_id: int,
    authorization: str | None = Header(None, alias="Authorization"),
):
    user = _require_user(authorization)
    strategy = workshop.get_strategy(user.user_id, strategy_id)
    if not strategy:
        strategy = workshop.get_strategy(user.user_id, strategy_id, public_only=True)
    if not strategy:
        raise HTTPException(status_code=404, detail="策略不存在")
    return {"code": 200, "data": strategy}


@app.put("/workshop/strategies/{strategy_id}")
async def workshop_update_strategy(
    strategy_id: int,
    payload: workshop.StrategyPayload,
    change_note: str = "",
    authorization: str | None = Header(None, alias="Authorization"),
):
    user = _require_user(authorization)
    try:
        updated = workshop.update_strategy(user.user_id, strategy_id, payload, change_note)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not updated:
        raise HTTPException(status_code=404, detail="策略不存在")
    return {"code": 200, "data": updated}


@app.delete("/workshop/strategies/{strategy_id}")
async def workshop_delete_strategy(
    strategy_id: int,
    authorization: str | None = Header(None, alias="Authorization"),
):
    user = _require_user(authorization)
    if not workshop.delete_strategy(user.user_id, strategy_id):
        raise HTTPException(status_code=404, detail="策略不存在")
    return {"code": 200, "message": "策略已删除"}


@app.get("/workshop/strategies/{strategy_id}/versions")
async def workshop_versions(
    strategy_id: int,
    authorization: str | None = Header(None, alias="Authorization"),
):
    user = _require_user(authorization)
    _workshop_strategy(user.user_id, strategy_id)
    return {"code": 200, "data": workshop.list_versions(user.user_id, strategy_id)}


@app.post("/workshop/strategies/{strategy_id}/fork")
async def workshop_fork_strategy(
    strategy_id: int,
    authorization: str | None = Header(None, alias="Authorization"),
):
    user = _require_user(authorization)
    try:
        copied = workshop.fork_strategy(user.user_id, strategy_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not copied:
        raise HTTPException(status_code=404, detail="公开策略不存在")
    return {"code": 200, "data": copied}


@app.post("/workshop/strategies/{strategy_id}/apply")
async def workshop_apply_strategy(
    strategy_id: int,
    request: workshop.ApplyRequest,
    authorization: str | None = Header(None, alias="Authorization"),
):
    """运行策略：simulation=历史回测；live=当日计算（沿用 signal.generated 链路）"""
    user = _require_user(authorization)
    if request.mode not in {"simulation", "live"}:
        raise HTTPException(status_code=400, detail="mode 仅支持 simulation/live")
    strategy = _workshop_strategy(user.user_id, strategy_id)
    started_at = datetime.now()
    try:
        if request.mode == "simulation":
            end_date = request.end_date or started_at.strftime("%Y-%m-%d")
            start_date = request.start_date or (started_at - timedelta(days=120)).strftime("%Y-%m-%d")
            backtest_request = BacktestRequest(
                strategy_type=StrategyType(strategy["scenario"]),
                start_date=start_date, end_date=end_date,
                initial_capital=request.initial_capital,
                params=workshop.params_from_strategy(strategy),
            )
            params = _merge_backtest_params(user.user_id, backtest_request)
            loop = asyncio.get_event_loop()
            raw = await loop.run_in_executor(
                None,
                lambda: _execute_backtest(
                    user.user_id, backtest_request.strategy_type, start_date, end_date,
                    request.initial_capital, params,
                ),
            )
            nav = raw.get("nav_curve") or []
            step = max(1, len(nav) // 120)
            result = {
                "start_date": start_date, "end_date": end_date,
                "initial_capital": request.initial_capital,
                "total_return": raw.get("total_return"), "annual_return": raw.get("annual_return"),
                "max_drawdown": raw.get("max_drawdown"), "sharpe_ratio": raw.get("sharpe_ratio"),
                "win_rate": raw.get("win_rate"), "trade_count": raw.get("trade_count"),
                "nav_curve": nav[::step],
                "note": "回测按风控参数逐日回放；触发条件与执行动作在实盘信号层生效",
            }
        else:
            response = await _calculate_for_user(
                user.user_id, StrategyType(strategy["scenario"]), allow_stale=True, force=True,
            )
            signals = response.get("data") or []
            # 信号本身不带板块行情/估值指标，按 sector_code 注入当日快照，
            # 使「强势动量/资金流入/低估值」等算法条件能在信号层真实匹配
            try:
                snapshot = await asyncio.to_thread(
                    _load_sector_snapshot, response.get("signal_date"), False
                ) or []
                sectors_by_code = {row.get("sector_code"): row for row in snapshot}
                for sig in signals:
                    row = sectors_by_code.get(sig.get("sector_code")) or {}
                    for field in workshop.SNAPSHOT_FIELDS:
                        if field in row:
                            sig[field] = row[field]
            except Exception as e:
                logger.warning(f"策略工坊注入板块指标失败，相关条件将不匹配: {e}")
            accepted, stats = workshop.apply_rules(signals, strategy)
            result = {
                "signal_date": response.get("signal_date"),
                "market_regime": response.get("market_regime"),
                "position_status": response.get("position_status"),
                "stats": stats, "signals": accepted,
                "note": "采纳信号沿用既有 signal.generated 链路；工坊规则仅过滤/调整本次生成的信号",
            }
        run = workshop.save_run(user.user_id, strategy_id, request.mode, "success", result,
                                started_at=started_at.strftime("%Y-%m-%d %H:%M:%S"))
        return {"code": 200, "data": {"run": run, "result": result}}
    except Exception as e:
        logger.error(f"策略工坊运行失败: strategy={strategy_id}, {e}")
        workshop.save_run(user.user_id, strategy_id, request.mode, "failed", error=str(e),
                          started_at=started_at.strftime("%Y-%m-%d %H:%M:%S"))
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/workshop/runs")
async def workshop_list_runs(
    strategy_id: int | None = None,
    limit: int = 50,
    authorization: str | None = Header(None, alias="Authorization"),
):
    user = _require_user(authorization)
    return {"code": 200, "data": workshop.list_runs(user.user_id, strategy_id, min(limit, 100))}


@app.get("/workshop/runs/{run_id}")
async def workshop_get_run(
    run_id: int,
    authorization: str | None = Header(None, alias="Authorization"),
):
    user = _require_user(authorization)
    run = workshop.get_run(user.user_id, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    return {"code": 200, "data": run}


@app.post("/workshop/strategies/{strategy_id}/like")
async def workshop_like_strategy(
    strategy_id: int,
    authorization: str | None = Header(None, alias="Authorization"),
):
    """点赞公开策略：同一账号只计一次（数据库唯一约束兜底）"""
    user = _require_user(authorization)
    if not workshop.get_strategy(user.user_id, strategy_id, public_only=True):
        raise HTTPException(status_code=404, detail="公开策略不存在")
    return {"code": 200, "data": workshop.like_strategy(user.user_id, strategy_id)}


@app.delete("/workshop/strategies/{strategy_id}/like")
async def workshop_unlike_strategy(
    strategy_id: int,
    authorization: str | None = Header(None, alias="Authorization"),
):
    user = _require_user(authorization)
    if not workshop.get_strategy(user.user_id, strategy_id, public_only=True):
        raise HTTPException(status_code=404, detail="公开策略不存在")
    return {"code": 200, "data": workshop.unlike_strategy(user.user_id, strategy_id)}


@app.get("/workshop/algorithms/builtin")
async def workshop_builtin_algorithms(
    authorization: str | None = Header(None, alias="Authorization"),
):
    """系统内置算法：一键插入触发条件，字段与后端白名单保持一致"""
    _require_user(authorization)
    return {"code": 200, "data": workshop.BUILTIN_ALGORITHMS}


@app.get("/workshop/algorithms")
async def workshop_list_algorithms(
    authorization: str | None = Header(None, alias="Authorization"),
):
    user = _require_user(authorization)
    return {"code": 200, "data": workshop.list_algorithms(user.user_id)}


@app.post("/workshop/algorithms")
async def workshop_create_algorithm(
    payload: workshop.AlgorithmPayload,
    authorization: str | None = Header(None, alias="Authorization"),
):
    user = _require_user(authorization)
    try:
        return {"code": 200, "data": workshop.create_algorithm(user.user_id, payload)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.put("/workshop/algorithms/{algorithm_id}")
async def workshop_update_algorithm(
    algorithm_id: int,
    payload: workshop.AlgorithmPayload,
    authorization: str | None = Header(None, alias="Authorization"),
):
    user = _require_user(authorization)
    try:
        updated = workshop.update_algorithm(user.user_id, algorithm_id, payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not updated:
        raise HTTPException(status_code=404, detail="算法不存在")
    return {"code": 200, "data": updated}


@app.delete("/workshop/algorithms/{algorithm_id}")
async def workshop_delete_algorithm(
    algorithm_id: int,
    authorization: str | None = Header(None, alias="Authorization"),
):
    user = _require_user(authorization)
    if not workshop.delete_algorithm(user.user_id, algorithm_id):
        raise HTTPException(status_code=404, detail="算法不存在")
    return {"code": 200, "message": "算法已删除"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.service_port)
