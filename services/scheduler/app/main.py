"""任务调度中心 - FastAPI主应用 + APScheduler定时任务"""
import asyncio
import httpx
from contextlib import asynccontextmanager
from datetime import datetime
from fastapi import FastAPI, HTTPException
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.redis import RedisJobStore
from apscheduler.triggers.cron import CronTrigger
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED
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


def _is_weekend() -> bool:
    """简单判断今天是否为周末（精确的节假日判断由下游服务负责）"""
    return datetime.now().weekday() >= 5


async def job_collect_data():
    """定时任务：数据采集（每个交易日15:00执行），采集成功后立即触发策略计算"""
    if _is_weekend():
        logger.info(">>> 今日为周末，跳过数据采集（节假日由下游服务判断）")
        return
    logger.info(">>> 定时任务触发: 数据采集")
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(f"{settings.data_collector_url}/collect/sector-flow")
            result = resp.json()
            logger.info(f"数据采集结果: {result}")
            if result.get("code") == 200:
                logger.info(">>> 数据采集完成，立即触发策略计算")
                await _trigger_strategy_calculation(client)
                # 采集+计算成功后设置去重标记
                today = datetime.now().strftime("%Y-%m-%d")
                await _check_and_mark_executed(f"signal:calculated:{today}")
    except Exception as e:
        logger.error(f"数据采集任务失败: {e}")


async def _trigger_strategy_calculation(client: httpx.AsyncClient):
    """触发三种策略的轮动信号计算"""
    for strategy in ["AGGRESSIVE", "MODERATE", "CONSERVATIVE"]:
        try:
            resp = await client.post(
                f"{settings.strategy_url}/calculate?strategy_type={strategy}"
            )
            logger.info(f"策略计算结果 [{strategy}]: {resp.json()}")
        except Exception as e:
            logger.error(f"策略计算失败 [{strategy}]: {e}")


async def job_calculate_strategy():
    """定时任务：策略计算（作为采集链路的备用触发，正常由采集任务链式触发）"""
    if _is_weekend():
        logger.info(">>> 今日为周末，跳过策略计算（节假日由下游服务判断）")
        return
    today = datetime.now().strftime("%Y-%m-%d")
    if not await _check_and_mark_executed(f"signal:calculated:{today}"):
        logger.info(">>> 今日策略已计算，跳过备用触发")
        return
    logger.info(">>> 定时任务触发: 策略计算")
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            await _trigger_strategy_calculation(client)
    except Exception as e:
        logger.error(f"策略计算任务失败: {e}")


async def job_collect_north_bound():
    """定时任务：北向资金采集（每个交易日16:00执行）"""
    if _is_weekend():
        logger.info(">>> 今日为周末，跳过北向资金采集（节假日由下游服务判断）")
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


def setup_scheduler():
    """配置定时任务（持久化到 Redis，重启后任务不丢失）"""
    job_stores = _build_job_store()
    scheduler.configure(jobstores=job_stores)

    misfire_grace = 3600  # 1小时容错，避免重启后重复执行历史任务

    scheduler.add_job(
        job_collect_data, CronTrigger(day_of_week="mon-fri", hour=15, minute=0),
        id="collect_data", name="板块资金流数据采集", replace_existing=True,
        misfire_grace_time=misfire_grace, max_instances=1,
    )
    scheduler.add_job(
        job_calculate_strategy, CronTrigger(day_of_week="mon-fri", hour=15, minute=5),
        id="calculate_strategy", name="三档轮动策略计算", replace_existing=True,
        misfire_grace_time=misfire_grace, max_instances=1,
    )
    scheduler.add_job(
        job_collect_north_bound, CronTrigger(day_of_week="mon-fri", hour=16, minute=0),
        id="collect_north_bound", name="北向资金数据采集", replace_existing=True,
        misfire_grace_time=misfire_grace, max_instances=1,
    )

    scheduler.add_listener(_job_error_listener, EVENT_JOB_ERROR)

    logger.info("定时任务配置完成 - 仅限交易日执行 (misfire_grace=3600s, max_instances=1)")


async def _run_startup_jobs():
    """启动时执行所有任务（不阻塞启动流程）

    job_collect_data 内部已链式触发策略计算，无需再单独调用 job_calculate_strategy，
    避免重复推送。启动前检查 Redis 去重标记，若今日已执行则跳过。
    """
    today = datetime.now().strftime("%Y-%m-%d")
    if not await _check_and_mark_executed(f"signal:calculated:{today}"):
        logger.info(">>> 今日策略已计算，跳过启动任务")
        return
    logger.info(">>> 启动时执行: 数据采集")
    await job_collect_data()
    logger.info(">>> 启动时执行: 北向资金采集")
    await job_collect_north_bound()


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
    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run": str(job.next_run_time) if job.next_run_time else None,
        })
    return {
        "status": "healthy",
        "service": "scheduler",
        "jobs": jobs,
        "timestamp": datetime.now().isoformat(),
    }


@app.post("/trigger/collect")
async def trigger_collect():
    """手动触发数据采集（后续自动链式触发策略计算）"""
    today = datetime.now().strftime("%Y-%m-%d")
    if not await _check_and_mark_executed(f"signal:calculated:{today}"):
        return {"code": 200, "message": "今日策略已计算，跳过重复触发"}
    await job_collect_data()
    return {"code": 200, "message": "数据采集已触发"}


@app.post("/trigger/strategy")
async def trigger_strategy():
    """手动触发策略计算"""
    today = datetime.now().strftime("%Y-%m-%d")
    if not await _check_and_mark_executed(f"signal:calculated:{today}"):
        return {"code": 200, "message": "今日策略已计算，跳过重复触发"}
    results = []
    async with httpx.AsyncClient(timeout=120) as client:
        for strategy in ["AGGRESSIVE", "MODERATE", "CONSERVATIVE"]:
            try:
                resp = await client.post(
                    f"{settings.strategy_url}/calculate?strategy_type={strategy}"
                )
                data = resp.json()
                signal_count = len(data.get("data", []))
                results.append({
                    "strategy": strategy,
                    "signal_count": signal_count,
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
    return {
        "code": 200,
        "message": f"策略计算完成，共生成 {total_signals} 条信号",
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
