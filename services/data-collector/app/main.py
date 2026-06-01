"""数据采集服务 - FastAPI主应用"""
import sys
import os
from datetime import datetime
from fastapi import FastAPI, HTTPException
from loguru import logger

# 添加共享库路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from .config import settings
from .collector import data_collector
from .influx_client import influx_manager
from shared import RabbitMQManager, success_response, error_response

# 配置日志
logger.remove()
logger.add(sys.stderr, level=settings.log_level)

app = FastAPI(title="数据采集服务", version="1.1.0")

# 初始化 RabbitMQ 连接管理器
rmq = RabbitMQManager()


@app.on_event("startup")
async def startup():
    """应用启动事件"""
    rmq.connect(
        host=settings.rabbitmq_host,
        port=settings.rabbitmq_port,
        user=settings.rabbitmq_user,
        password=settings.rabbitmq_password,
    )


@app.on_event("shutdown")
async def shutdown():
    """应用关闭事件"""
    rmq.close()


@app.get("/health")
async def health_check():
    checks = {}
    # InfluxDB
    try:
        from .influx_client import influx_manager
        h = influx_manager.client.health()
        checks["influxdb"] = {"status": h.status}
    except Exception as e:
        checks["influxdb"] = {"status": "fail", "message": str(e)}
    # RabbitMQ
    try:
        rmq_ok = rmq._connection and rmq._connection.is_open
        checks["rabbitmq"] = {"status": "pass" if rmq_ok else "fail"}
    except Exception as e:
        checks["rabbitmq"] = {"status": "fail", "message": str(e)}

    all_ok = all(c.get("status") in ("pass", "pass") for c in checks.values())
    return {
        "status": "healthy" if all_ok else "degraded",
        "service": "data-collector",
        "checks": checks,
        "timestamp": datetime.now().isoformat(),
    }


@app.post("/collect/sector-flow")
async def collect_sector_flow(trade_date: str = None):
    """触发板块资金流数据采集"""
    try:
        results = data_collector.collect_sector_capital_flow(trade_date)
        # 通知策略引擎数据已更新
        rmq.publish("data.updated.sector_flow", {
            "event": "sector_flow_updated",
            "trade_date": trade_date or datetime.now().strftime("%Y-%m-%d"),
            "count": len(results),
            "timestamp": datetime.now().isoformat(),
        })
        return success_response(data={"count": len(results)}, message="采集完成")
    except Exception as e:
        logger.error(f"数据采集失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/collect/history")
async def collect_history(days: int = 30, date: str = None):
    """采集历史数据（当日汇总 + K线历史填充）

    Args:
        days: K线回溯天数
        date: 指定采集日期 YYYY-MM-DD，不传则默认今天
    """
    try:
        # 先采集指定日期汇总（或当日）
        results = data_collector.collect_sector_history(days, trade_date=date)
        # 再用K线数据填充历史
        kline_results = data_collector.collect_sector_history_via_kline(days)
        total = len(results) + len(kline_results)
        return success_response(data={"count": total}, message="采集历史数据完成")
    except Exception as e:
        logger.error(f"历史数据采集失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/collect/backfill-fund-flow")
async def backfill_fund_flow(start_date: str = "20240101", end_date: str = None):
    """回填历史板块资金流数据（使用 stock_sector_fund_flow_hist 接口）"""
    try:
        count = data_collector.backfill_sector_fund_flow_hist(start_date, end_date)
        return success_response(data={"count": count}, message=f"资金流回填完成，写入 {count} 条记录")
    except Exception as e:
        logger.error(f"资金流回填失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/collect/north-bound")
async def collect_north_bound(date: str = None):
    """采集北向资金数据

    Args:
        date: 指定采集日期 YYYY-MM-DD，不传则默认今天（非交易日自动回退）
    """
    try:
        results = data_collector.collect_north_bound_flow(trade_date=date)
        return success_response(data={"count": len(results)}, message="北向资金数据采集完成")
    except Exception as e:
        logger.error(f"北向资金数据采集失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/collect/kline")
async def collect_kline(sector_name: str = None, start_date: str = None, end_date: str = None):
    """采集板块K线数据

    Args:
        sector_name: 板块名称，不传则采集所有板块
        start_date: 开始日期 YYYYMMDD，默认 20240101
        end_date: 结束日期 YYYYMMDD，默认今天
    """
    try:
        if sector_name:
            results = data_collector.collect_sector_kline(sector_name, start_date, end_date)
            if results:
                influx_manager.write_sector_kline(results)
        else:
            results = data_collector.collect_all_sectors_kline(start_date, end_date)
        return success_response(data={"count": len(results)}, message="K线数据采集完成")
    except Exception as e:
        logger.error(f"K线数据采集失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/trade-dates")
async def get_trade_dates(days: int = 365):
    """获取交易日历（以今天为基准，返回最近 N 个交易日）"""
    try:
        trade_dates = data_collector.get_trade_dates(days)
        if trade_dates is None:
            return success_response(data=[])
        today = datetime.now().strftime("%Y%m%d")
        # 取今天及之前最近N个交易日（跳过未来日期）
        past = [d for d in trade_dates if d <= today][-days:]
        return success_response(data=past)
    except Exception as e:
        logger.error(f"获取交易日历失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/query/sector-data")
async def query_sector_data(sector_code: str, start_date: str, end_date: str):
    """查询板块历史数据"""
    try:
        data = influx_manager.query_sector_data(sector_code, start_date, end_date)
        return success_response(data=data)
    except Exception as e:
        logger.error(f"数据查询失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/query/all-sectors")
async def query_all_sectors(start_date: str, end_date: str):
    """查询所有板块数据"""
    try:
        data = influx_manager.query_all_sectors_data(start_date, end_date)
        return success_response(data=data)
    except Exception as e:
        logger.error(f"数据查询失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/sectors")
async def get_sectors():
    """获取板块名称列表（同花顺）"""
    try:
        sectors = data_collector.get_sector_names()
        return success_response(data=sectors)
    except Exception as e:
        logger.error(f"获取板块列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/data/cleanup")
async def cleanup_data(measurement: str, start_date: str, end_date: str):
    """删除指定测量中某时间范围的数据（用于清理错误数据）

    Args:
        measurement: InfluxDB 测量名 (sector_capital_flow, sector_kline, north_bound_flow)
        start_date: 开始日期 YYYYMMDD
        end_date: 结束日期 YYYYMMDD
    """
    try:
        influx_manager.delete_by_date_range(measurement, start_date, end_date)
        return success_response(message=f"已删除 {measurement} {start_date}~{end_date} 的数据")
    except Exception as e:
        logger.error(f"数据清理失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.service_port)
