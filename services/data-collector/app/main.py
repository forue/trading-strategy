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
    return {"status": "healthy", "service": "data-collector", "timestamp": datetime.now().isoformat()}


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
async def collect_history(days: int = 30):
    """采集历史数据（当日汇总 + K线历史填充）"""
    try:
        # 先采集当日汇总
        results = data_collector.collect_sector_history(days)
        # 再用K线数据填充历史
        kline_results = data_collector.collect_sector_history_via_kline(days)
        total = len(results) + len(kline_results)
        return success_response(data={"count": total}, message="采集历史数据完成")
    except Exception as e:
        logger.error(f"历史数据采集失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/collect/north-bound")
async def collect_north_bound():
    """采集北向资金数据"""
    try:
        results = data_collector.collect_north_bound_flow()
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
    """获取交易日历"""
    try:
        trade_dates = data_collector.get_trade_dates(days)
        if trade_dates is None:
            return success_response(data=[])
        # 只返回最近N天
        recent = trade_dates[-days:] if len(trade_dates) > days else trade_dates
        return success_response(data=recent)
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.service_port)
