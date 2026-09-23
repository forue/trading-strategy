"""任务调度中心 - FastAPI主应用 + APScheduler定时任务"""
import asyncio
import httpx
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.redis import RedisJobStore
from apscheduler.jobstores.base import JobLookupError
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED, EVENT_JOB_MISSED
from loguru import logger

from .config import settings

# Redis 去重客户端（db=0，与 auth 服务共享 keyspace）
import redis.asyncio as aioredis
_redis_dedup: aioredis.Redis | None = None


async def _get_redis_dedup() -> aioredis.Redis | None:
    global _redis_dedup
    if _redis_dedup is not None:
        try:
            await _redis_dedup.ping()
            return _redis_dedup
        except Exception:
            _redis_dedup = None
    try:
        _redis_dedup = aioredis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            password=settings.redis_password or None,
            db=0,
            decode_responses=True,
        )
        await _redis_dedup.ping()
        return _redis_dedup
    except Exception:
        return None


async def _check_and_mark_executed(key: str, ttl: int = 86400) -> bool:
    """检查 Redis 去重标记，首次调用返回 True 并设置标记"""
    r = await _get_redis_dedup()
    if r is None:
        return True  # Redis 不可用时放行
    # SET NX: 仅当 key 不存在时设置，返回 True 表示首次
    result = await r.set(key, "1", nx=True, ex=ttl)
    if result:
        logger.info(f"Redis 去重标记已设置: {key} (TTL={ttl}s)")
        return True
    logger.info(f"Redis 去重命中，跳过重复执行: {key}")
    return False


async def _is_executed(key: str) -> bool:
    """仅查询去重标记是否存在，不做占位写入。

    与 _check_and_mark_executed 的区别：查询类判断（"今日是否已完成"）必须用本方法，
    否则未真正完成时会被提前预置成"已完成"，导致后续定时/手动触发被误判跳过。
    """
    r = await _get_redis_dedup()
    if r is None:
        return False
    try:
        return bool(await r.exists(key))
    except Exception as e:
        logger.warning(f"读取去重标记失败 {key}: {e}")
        return False


async def _clear_executed(key: str) -> None:
    """撤销去重标记：用于任务未真正完成（如数据未就绪）时释放占位"""
    r = await _get_redis_dedup()
    if r is None:
        return
    try:
        await r.delete(key)
        logger.info(f"Redis 去重标记已撤销: {key}")
    except Exception as e:
        logger.warning(f"撤销去重标记失败 {key}: {e}")


async def _mark_collecting(date_str: str, ttl: int = 900) -> bool:
    """标记"当日采集进行中"，返回 True 表示本次成功占位"""
    r = await _get_redis_dedup()
    if r is None:
        return True
    try:
        return bool(await r.set(f"collecting:{date_str}", "1", nx=True, ex=ttl))
    except Exception as e:
        logger.warning(f"设置采集中标记失败: {e}")
        return True


async def _is_collecting(date_str: str) -> bool:
    """判断当日是否有采集任务正在进行"""
    r = await _get_redis_dedup()
    if r is None:
        return False
    try:
        return bool(await r.exists(f"collecting:{date_str}"))
    except Exception as e:
        logger.warning(f"读取采集中标记失败: {e}")
        return False


async def _clear_collecting(date_str: str) -> None:
    """清除"当日采集进行中"标记"""
    r = await _get_redis_dedup()
    if r is None:
        return
    try:
        await r.delete(f"collecting:{date_str}")
    except Exception as e:
        logger.warning(f"清除采集中标记失败: {e}")


def _is_weekend() -> bool:
    """简单判断今天是否为周末（精确的节假日判断由下游服务负责）"""
    return datetime.now().weekday() >= 5


async def _is_non_trade_day() -> bool:
    """通过数据采集器交易日历判断今天是否为非交易日。
    同时检查周末（快速路径，避免无意义 HTTP 调用）。
    返回 True 表示非交易日，应跳过定时任务。

    交易日历不可用或返回数据异常时，回退到周末判断。
    """
    if _is_weekend():
        return True
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{settings.data_collector_url}/trade-dates?days=30")
            if resp.status_code == 200:
                trade_dates = resp.json().get("data", [])
                # 交易日历异常（空列表或数据过少），回退到周末判断
                if not trade_dates or len(trade_dates) < 3:
                    logger.warning("交易日历数据异常（空或过少），回退到周末判断")
                    return _is_weekend()
                today = datetime.now().strftime("%Y%m%d")
                if today in trade_dates:
                    return False
                # 缓存中没找到今天，检查是否覆盖了当前月份
                # 如果缓存完全没有当前月份的日期 → 缓存不可信，回退周末
                today_month = today[:6]
                has_current_month = any(d.startswith(today_month) for d in trade_dates)
                if not has_current_month:
                    logger.warning(f"交易日历缺少 {today_month} 月份数据，回退到周末判断")
                    return _is_weekend()
                return True  # 覆盖了当前月份但没有今天 → 确认为非交易日
    except Exception:
        logger.warning("交易日历接口调用失败，回退到周末判断")
    return _is_weekend()


# 采集/计算时点：同花顺行业汇总接口在收盘后仍需数分钟完成当日结算，
# 15:00 整点采集会落库未定盘数据（实测 90 个板块中 81 个涨跌幅、82 个净流入
# 在盘后仍会变动），因此推迟到 15:30；备用计算任务顺延到 15:35。
COLLECT_HOUR, COLLECT_MINUTE = 15, 30
CALCULATE_HOUR, CALCULATE_MINUTE = 15, 35


async def job_collect_data():
    """定时任务：数据采集（每个交易日15:30执行），采集成功后立即触发策略计算，失败最多重试3次

    采集期间会打上"采集中"标记：备用触发任务据此让行，避免两者并发导致策略
    在入库完成前读到 T-1 数据。
    """
    if await _is_non_trade_day():
        logger.info(">>> 今日非交易日，跳过数据采集")
        return

    today = datetime.now().strftime("%Y-%m-%d")
    if not await _mark_collecting(today):
        logger.info(">>> 已有采集任务进行中，跳过本次采集")
        return

    logger.info(">>> 定时任务触发: 数据采集")
    try:
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=60) as client:
                    resp = await client.post(f"{settings.data_collector_url}/collect/sector-flow")
                    result = resp.json()
                    logger.info(f"数据采集结果: {result}")
                    if result.get("code") == 200:
                        logger.info(">>> 数据采集完成，立即触发策略计算")
                        calculated = await _trigger_strategy_calculation(client)
                        if calculated:
                            await _check_and_mark_executed(f"signal:calculated:{today}")
                            # 先刷新板块K线再回填：回填要用 T+1 开盘价，行情不新会全部落空
                            await _trigger_kline_refresh(client)
                            await _trigger_outcome_backfill(client)
                        else:
                            # 数据虽已采集但策略侧判定未就绪：不标记完成，保留重试机会
                            logger.error(">>> 策略计算因数据未就绪未完成，不标记今日已计算")
                        return
                    else:
                        logger.warning(f"数据采集返回非200(尝试{attempt+1}/3): {result}")
            except Exception as e:
                logger.warning(f"数据采集任务失败(尝试{attempt+1}/3): {e}")

            if attempt < 2:
                wait = 60 * (attempt + 1)  # 60s, 120s
                logger.info(f"等待{wait}秒后重试数据采集")
                await asyncio.sleep(wait)

        logger.error("数据采集任务最终失败(已重试3次)")
    finally:
        await _clear_collecting(today)


async def _trigger_strategy_calculation(client: httpx.AsyncClient, allow_stale: bool = False) -> bool:
    """触发三种策略的轮动信号计算

    Returns:
        True 表示至少一个策略在"当日数据就绪"的前提下完成计算；
        全部因数据未就绪而跳过时返回 False，调用方不应标记为已执行。
    """
    calculated = False
    for strategy in ["AGGRESSIVE", "MODERATE", "CONSERVATIVE"]:
        try:
            resp = await client.post(
                f"{settings.strategy_url}/calculate?strategy_type={strategy}"
                f"&allow_stale={'true' if allow_stale else 'false'}"
            )
            payload = resp.json()
            logger.info(f"策略计算结果 [{strategy}]: {payload.get('message')}")
            if payload.get("data_ready"):
                calculated = True
        except Exception as e:
            logger.error(f"策略计算失败 [{strategy}]: {e}")
    return calculated


async def _trigger_outcome_backfill(client: httpx.AsyncClient) -> None:
    """触发信号收益回填：为已走完 1/3/5/10 交易日持有期的历史信号结算胜负

    复盘页面的命中率/净收益依赖该回填结果，失败不影响主链路。
    """
    try:
        resp = await client.post(f"{settings.strategy_url}/signals/backfill")
        payload = resp.json()
        logger.info(f"信号收益回填: {payload.get('message')} {payload.get('data')}")
    except Exception as e:
        logger.error(f"信号收益回填失败: {e}")


# 板块K线刷新窗口（自然日）：覆盖最近约 10 个交易日，既能写入当日 OHLC，
# 也能把此前数据源未就绪而缺失的开盘价补齐
KLINE_REFRESH_DAYS = 15


async def _trigger_kline_refresh(client: httpx.AsyncClient) -> None:
    """刷新最近若干交易日的板块K线（sector_kline）

    复盘按"T+1 开盘价买入"结算，开盘价只能取自 sector_kline 的真实 OHLC；
    该测量不随资金流采集更新，若不刷新，新信号的 T+1 开盘价会持续取不到，
    回填结果全部落空。窗口取 15 个自然日以具备追赶能力。
    """
    today = datetime.now()
    start = (today - timedelta(days=KLINE_REFRESH_DAYS)).strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")
    try:
        resp = await client.post(
            f"{settings.data_collector_url}/collect/kline",
            params={"start_date": start, "end_date": end},
            timeout=180,
        )
        payload = resp.json()
        count = (payload.get("data") or {}).get("count")
        logger.info(f"板块K线刷新({start}~{end}): {payload.get('message')} 共 {count} 条")
    except Exception as e:
        logger.error(f"板块K线刷新失败: {e}")


async def job_calculate_strategy():
    """定时任务：策略计算（作为采集链路的备用触发，正常由采集任务链式触发）"""
    if await _is_non_trade_day():
        logger.info(">>> 今日非交易日，跳过策略计算")
        return
    today = datetime.now().strftime("%Y-%m-%d")
    # 采集进行中时一律让行：采集完成后会链式触发计算，
    # 此处并发执行会让策略读到入库前的旧数据
    if await _is_collecting(today):
        logger.info(">>> 数据采集进行中，跳过备用触发")
        return
    if not await _check_and_mark_executed(f"signal:calculated:{today}"):
        logger.info(">>> 今日策略已计算，跳过备用触发")
        return
    logger.info(">>> 定时任务触发: 策略计算")
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            calculated = await _trigger_strategy_calculation(client)
            if calculated:
                await _trigger_kline_refresh(client)
                await _trigger_outcome_backfill(client)
            if not calculated:
                # 数据尚未入库：撤销占位，交由后续采集链路重新触发
                await _clear_executed(f"signal:calculated:{today}")
                logger.warning(">>> 当日数据未就绪，已撤销执行标记，等待采集链路触发")
    except Exception as e:
        logger.error(f"策略计算任务失败: {e}")


async def job_collect_north_bound():
    """【已暂停】北向资金采集任务

    沪深港通自 2024-08-19 起停止披露北向资金成交净买额，采集结果恒为 0，
    指标已无分析价值（详见 collector.collect_north_bound_flow 注释）。
    因此不再注册到调度器、也不在启动时调用；保留实现以便数据源恢复后快速重启。
    """
    if await _is_non_trade_day():
        logger.info(">>> 今日非交易日，跳过北向资金采集")
        return
    logger.info(">>> 定时任务触发: 北向资金采集")
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(f"{settings.data_collector_url}/collect/north-bound")
            logger.info(f"北向资金采集结果: {resp.json()}")
    except Exception as e:
        logger.error(f"北向资金采集任务失败: {e}")


def _job_error_listener(event):
    """任务异常监听：记录并可在未来扩展告警通知"""
    if event.exception:
        logger.error(
            f"定时任务异常: job_id={event.job_id}, "
            f"scheduled_run_time={event.scheduled_run_time}, "
            f"exception={event.exception}"
        )


# 每日任务 job_id → 协程函数映射，供 misfire 补偿执行使用
_RECOVERABLE_JOBS: dict[str, object] = {}


def _job_missed_listener(event):
    """任务错过触发（misfire）监听：告警并尝试当日内补偿执行

    宿主休眠会让容器单调时钟停滞，唤醒后 APScheduler 判定任务已超过
    misfire_grace_time 而静默丢弃（只发 EVENT_JOB_MISSED，不会执行）。
    这里把该事件提升为错误日志，并在"仍是当天"时立即补跑，实现自愈。
    """
    logger.error(
        f"定时任务错过触发(misfire): job_id={event.job_id}, "
        f"scheduled_run_time={event.scheduled_run_time}"
    )
    try:
        asyncio.create_task(_recover_missed_job(event.job_id, event.scheduled_run_time))
    except RuntimeError as e:
        logger.error(f"无法调度 misfire 补偿任务: {e}")


async def _recover_missed_job(job_id: str, scheduled_run_time) -> None:
    """补偿执行被 misfire 丢弃的当日任务；跨日任务不补跑，避免重复采集历史数据"""
    job_func = _RECOVERABLE_JOBS.get(job_id)
    if job_func is None:
        return
    run_date = getattr(scheduled_run_time, "date", lambda: None)()
    if run_date != datetime.now().date():
        logger.warning(
            f"错过任务 {job_id} 的原定时间为 {scheduled_run_time}（非当日），不补跑"
        )
        return
    logger.warning(f">>> 补偿执行错过任务: {job_id} (原定 {scheduled_run_time})")
    try:
        await job_func()
    except Exception as e:
        logger.error(f"补偿执行错过任务 {job_id} 失败: {e}")


WATCHDOG_INTERVAL_SECONDS = 300
_last_watchdog_tick: datetime | None = None


async def _scheduler_watchdog():
    """定时器漂移看门狗：宿主休眠唤醒后容器单调时钟滞后于墙钟，
    会让 APScheduler 的等待时长被拉长、任务越过 misfire 窗口被丢弃。
    看门狗以 5 分钟间隔运行，若两次触发间距远超预期即判定发生时钟漂移并告警。
    """
    global _last_watchdog_tick
    now = datetime.now()
    if _last_watchdog_tick is not None:
        gap = (now - _last_watchdog_tick).total_seconds()
        if gap > WATCHDOG_INTERVAL_SECONDS * 3:
            logger.error(
                f"检测到调度器时钟漂移: 看门狗实际间隔 {gap:.0f}s，"
                f"预期 {WATCHDOG_INTERVAL_SECONDS}s，宿主休眠导致定时器停滞"
            )
    _last_watchdog_tick = now


def _build_job_store() -> dict:
    """构建 Redis 持久化 job store，失败时回退到内存存储"""
    try:
        redis_password = settings.redis_password if settings.redis_password else None
        store = RedisJobStore(
            host=settings.redis_host,
            port=settings.redis_port,
            password=redis_password,
            db=2,
        )
        logger.info(f"使用 RedisJobStore (host={settings.redis_host}:{settings.redis_port})")
        return {"default": store}
    except Exception as e:
        logger.warning(f"RedisJobStore 初始化失败，回退到 MemoryJobStore: {e}")
        return {"default": None}


def _purge_legacy_job(job_stores: dict, job_id: str, label: str) -> None:
    """从持久化 jobstore 中彻底删除已下线的历史任务

    注意：scheduler.remove_job() 在 scheduler.start() 之前只会操作内存中的待注册任务，
    不会触及 RedisJobStore；任务会在 start() 时被重新加载并继续按原计划触发。
    因此这里直接删除 jobstore 中的记录，start() 时自然不会再恢复该任务。
    """
    store = job_stores.get("default")
    if store is None:
        return
    try:
        store.remove_job(job_id)
        logger.info(f"已从持久化存储中移除历史任务: {job_id}（{label}）")
    except JobLookupError:
        pass
    except Exception as e:
        logger.warning(f"清理历史任务 {job_id} 失败: {e}")


def setup_scheduler():
    """配置定时任务（持久化到 Redis，重启后任务不丢失）"""
    _RECOVERABLE_JOBS.update({
        "collect_data": job_collect_data,
        "calculate_strategy": job_calculate_strategy,
    })

    job_stores = _build_job_store()
    scheduler.configure(jobstores=job_stores)

    misfire_grace = 14400  # 4小时容错，覆盖维护窗口，同时避免重启后重复执行历史任务

    scheduler.add_job(
        job_collect_data, CronTrigger(day_of_week="mon-fri", hour=COLLECT_HOUR, minute=COLLECT_MINUTE),
        id="collect_data", name="板块资金流数据采集", replace_existing=True,
        misfire_grace_time=misfire_grace, max_instances=1,
    )
    scheduler.add_job(
        job_calculate_strategy, CronTrigger(day_of_week="mon-fri", hour=CALCULATE_HOUR, minute=CALCULATE_MINUTE),
        id="calculate_strategy", name="三档轮动策略计算", replace_existing=True,
        misfire_grace_time=misfire_grace, max_instances=1,
    )
    # 北向资金采集已暂停（数据源停止披露）
    _purge_legacy_job(job_stores, "collect_north_bound", "北向资金采集（功能已暂停）")
    # 看门狗：misfire_grace 放大到 24 小时，保证宿主休眠唤醒后必定被触发，
    # 从而能第一时间记录时钟漂移
    scheduler.add_job(
        _scheduler_watchdog, IntervalTrigger(seconds=WATCHDOG_INTERVAL_SECONDS),
        id="scheduler_watchdog", name="调度器时钟漂移看门狗", replace_existing=True,
        misfire_grace_time=86400, max_instances=1,
    )

    scheduler.add_listener(_job_error_listener, EVENT_JOB_ERROR)
    scheduler.add_listener(_job_missed_listener, EVENT_JOB_MISSED)

    logger.info(
        f"定时任务配置完成 - 仅限交易日执行 "
        f"(misfire_grace={misfire_grace}s, max_instances=1, watchdog={WATCHDOG_INTERVAL_SECONDS}s)"
    )


async def _run_startup_jobs():
    """启动时执行所有任务（不阻塞启动流程）

    job_collect_data 内部已链式触发策略计算，无需再单独调用 job_calculate_strategy，
    避免重复推送。启动前检查 Redis 去重标记，若今日已执行则跳过。

    未到采集时点时**不补跑采集**：此时行情未收盘或数据源未完成结算，补跑会把未定盘
    数据（甚至上一交易日快照）写成当日数据并固化当日信号，交由当天定时任务执行即可。
    """
    today = datetime.now().strftime("%Y-%m-%d")
    if await _is_executed(f"signal:calculated:{today}"):
        logger.info(">>> 今日策略已计算，跳过启动任务")
    else:
        now = datetime.now()
        if (now.hour, now.minute) < (COLLECT_HOUR, COLLECT_MINUTE):
            logger.info(
                f">>> 未到采集时点({COLLECT_HOUR:02d}:{COLLECT_MINUTE:02d})，"
                f"启动任务跳过数据采集，等待定时任务执行"
            )
        else:
            logger.info(">>> 启动时执行: 数据采集")
            await job_collect_data()

    # 信号收益回填与采集时点无关：每次启动补跑一次，把已走完持有期的信号结算掉
    async with httpx.AsyncClient(timeout=120) as client:
        await _trigger_kline_refresh(client)
        await _trigger_outcome_backfill(client)



# ---- FastAPI 应用 ----

# 全局 scheduler 实例（在 lifespan 中配置 job stores）
scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_scheduler()
    scheduler.start()
    logger.info("任务调度中心启动")
    # 启动后异步执行一次初始任务（不阻塞启动）
    asyncio.create_task(_run_startup_jobs())
    yield
    scheduler.shutdown()
    logger.info("任务调度中心关闭")


app = FastAPI(title="任务调度中心", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health_check():
    is_running = scheduler.running
    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run": str(job.next_run_time) if job.next_run_time else None,
        })
    status = "healthy" if is_running else "degraded"
    return {
        "status": status,
        "scheduler_running": is_running,
        "service": "scheduler",
        "jobs": jobs,
        "timestamp": datetime.now().isoformat(),
    }


@app.post("/trigger/collect")
async def trigger_collect():
    """手动触发数据采集（后续自动链式触发策略计算）"""
    today = datetime.now().strftime("%Y-%m-%d")
    if await _is_executed(f"signal:calculated:{today}"):
        return {"code": 200, "message": "今日策略已计算，跳过重复触发"}
    await job_collect_data()
    return {"code": 200, "message": "数据采集已触发"}


@app.post("/trigger/strategy")
async def trigger_strategy(allow_stale: bool = True, force: bool = False):
    """手动触发策略计算

    Args:
        allow_stale: 当日无板块数据（含周末/节假日）时，回退到最近有数据的交易日，
            并以该交易日作为信号日期。手动触发默认开启。
        force: 忽略"今日已计算"去重标记强制重算；回退场景下一并强制覆盖历史信号
    """
    today = datetime.now().strftime("%Y-%m-%d")
    if not force and await _is_executed(f"signal:calculated:{today}"):
        return {"code": 200, "message": "今日策略已计算，跳过重复触发（force=true 可强制重算）"}
    results = []
    async with httpx.AsyncClient(timeout=120) as client:
        for strategy in ["AGGRESSIVE", "MODERATE", "CONSERVATIVE"]:
            try:
                resp = await client.post(
                    f"{settings.strategy_url}/calculate?strategy_type={strategy}"
                    f"&allow_stale={'true' if allow_stale else 'false'}"
                    f"&force={'true' if force else 'false'}"
                )
                data = resp.json()
                signal_count = len(data.get("data", []))
                results.append({
                    "strategy": strategy,
                    "signal_count": signal_count,
                    "signal_date": data.get("signal_date", ""),
                    "data_ready": data.get("data_ready", False),
                    "stale": data.get("stale", False),
                    "message": data.get("message", ""),
                })
                logger.info(f"策略计算结果 [{strategy}]: {signal_count} 条信号")
            except Exception as e:
                results.append({
                    "strategy": strategy,
                    "signal_count": 0,
                    "error": str(e),
                })
                logger.error(f"策略计算失败 [{strategy}]: {e}")

    total_signals = sum(r.get("signal_count", 0) for r in results)
    ready_dates = sorted({r.get("signal_date", "") for r in results if r.get("data_ready")})
    return {
        "code": 200,
        "message": f"策略计算完成，共生成 {total_signals} 条信号"
                   + (f"（信号日期: {', '.join(d for d in ready_dates if d)}）" if ready_dates else ""),
        "data": results,
    }


@app.post("/trigger/all")
async def trigger_all():
    """手动触发全流程"""
    await job_collect_data()
    return {"code": 200, "message": "全流程已触发"}


@app.get("/jobs")
async def get_jobs():
    """获取所有定时任务"""
    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run": str(job.next_run_time) if job.next_run_time else None,
            "trigger": str(job.trigger),
            "max_instances": job.max_instances,
            "misfire_grace_time": job.misfire_grace_time,
        })
    return {"code": 200, "data": jobs}


@app.get("/logs")
async def get_logs(service: str = "", lines: int = 100, level: str = ""):
    """获取服务日志（通过 Docker Unix socket 读取）"""
    import httpx
    import re

    SERVICE_CONTAINER_MAP = {
        "backend-strategy": "rotation-strategy",
        "backend-data-collector": "rotation-data-collector",
        "backend-signal": "rotation-signal",
        "backend-ai-decision": "rotation-ai-decision",
        "backend-scheduler": "rotation-scheduler",
        "backend-auth": "rotation-auth",
        "backend-fund": "rotation-fund",
    }
    # 反向映射: 容器名 → compose服务名
    CONTAINER_TO_SVC = {v: k for k, v in SERVICE_CONTAINER_MAP.items()}

    # loguru 日志格式: "TIME | LEVEL | MODULE:FUNCTION:LINE - MESSAGE"
    LOG_PATTERN = re.compile(
        r'^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d+)\s*\|\s*(\w+)\s*\|\s*(.+)$'
    )

    transport = httpx.HTTPTransport(uds="/var/run/docker.sock")

    def _read_logs(container_name: str, tail: int, level_filter: str) -> list[dict]:
        try:
            with httpx.Client(transport=transport, timeout=10.0) as client:
                resp = client.get("http://localhost/containers/json?all=true")
                resp.raise_for_status()
                containers = resp.json()
                container_id = None
                for c in containers:
                    names = c.get("Names", [])
                    if any(f"/{container_name}" in n for n in names):
                        container_id = c["Id"]
                        break
                if not container_id:
                    return []

                resp = client.get(
                    f"http://localhost/containers/{container_id}/logs",
                    params={"stdout": "1", "stderr": "1", "tail": str(tail)},
                )
                resp.raise_for_status()
                raw = resp.content
                entries = []
                i = 0
                while i + 8 <= len(raw):
                    stream_type = raw[i]
                    payload_len = 0
                    for j in range(4):
                        payload_len = (payload_len << 8) | raw[i + 4 + j]
                    i += 8
                    if i + payload_len > len(raw):
                        break
                    payload = raw[i:i + payload_len].decode("utf-8", errors="replace")
                    i += payload_len
                    for line in payload.split('\n'):
                        line = line.strip()
                        if not line:
                            continue
                        # 解析 loguru 格式
                        m = LOG_PATTERN.match(line)
                        if m:
                            log_time, log_level, rest = m.groups()
                            # rest 格式: "module:function:line - message"
                            parts = rest.split(" - ", 1)
                            msg = parts[1] if len(parts) > 1 else rest
                        else:
                            log_time = ""
                            log_level = "stderr" if stream_type == 2 else "info"
                            msg = line
                        # 等级过滤
                        if level_filter and log_level.upper() != level_filter.upper():
                            continue
                        entries.append({
                            "time": log_time,
                            "level": log_level.lower(),
                            "service": CONTAINER_TO_SVC.get(container_name, container_name),
                            "message": msg,
                        })
                return entries
        except Exception as e:
            logger.warning(f"读取容器 {container_name} 日志失败: {e}")
            return []

    try:
        if service and service in SERVICE_CONTAINER_MAP:
            container = SERVICE_CONTAINER_MAP[service]
            entries = _read_logs(container, lines, level)
            entries.reverse()
            return {"code": 200, "data": entries}
        else:
            all_entries = []
            for svc, container_name in SERVICE_CONTAINER_MAP.items():
                all_entries.extend(_read_logs(container_name, lines, level))
            # 按时间戳排序（无时间戳的排最后）
            all_entries.sort(
                key=lambda x: x.get("time", "z") or "z",
                reverse=True,
            )
            return {"code": 200, "data": all_entries[:200]}
    except Exception as e:
        logger.error(f"获取日志失败: {e}")
        return {"code": 500, "data": [], "message": str(e)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.service_port)
