"""任务调度中心 - FastAPI主应用 + APScheduler定时任务"""
import httpx
from datetime import datetime
from fastapi import FastAPI, HTTPException
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from .config import settings

app = FastAPI(title="任务调度中心", version="1.0.0")
scheduler = AsyncIOScheduler()


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
            # 采集成功后立即触发策略计算，不等待固定5分钟延迟
            if result.get("code") == 200:
                logger.info(">>> 数据采集完成，立即触发策略计算")
                await _trigger_strategy_calculation(client)
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


def setup_scheduler():
    """配置定时任务"""
    # 每个交易日15:00采集数据（仅限交易日）
    scheduler.add_job(
        job_collect_data, CronTrigger(day_of_week="mon-fri", hour=15, minute=0),
        id="collect_data", name="板块资金流数据采集", replace_existing=True,
        misfire_grace_time=300,  # 5分钟容错时间
    )
    # 数据采集后5分钟计算策略（仅限交易日）
    scheduler.add_job(
        job_calculate_strategy, CronTrigger(day_of_week="mon-fri", hour=15, minute=5),
        id="calculate_strategy", name="三档轮动策略计算", replace_existing=True,
        misfire_grace_time=300,
    )
    # 16:00采集北向资金（仅限交易日）
    scheduler.add_job(
        job_collect_north_bound, CronTrigger(day_of_week="mon-fri", hour=16, minute=0),
        id="collect_north_bound", name="北向资金数据采集", replace_existing=True,
        misfire_grace_time=300,
    )
    logger.info("定时任务配置完成 - 仅限交易日执行")


@app.on_event("startup")
async def startup():
    setup_scheduler()
    scheduler.start()
    logger.info("任务调度中心启动")


@app.on_event("shutdown")
async def shutdown():
    scheduler.shutdown()
    logger.info("任务调度中心关闭")


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
    await job_collect_data()
    return {"code": 200, "message": "数据采集已触发"}


@app.post("/trigger/strategy")
async def trigger_strategy():
    """手动触发策略计算"""
    async with httpx.AsyncClient(timeout=120) as client:
        await _trigger_strategy_calculation(client)
    return {"code": 200, "message": "策略计算已触发"}


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
        })
    return {"code": 200, "data": jobs}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.service_port)
