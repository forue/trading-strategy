"""数据采集服务 - FastAPI主应用"""
import pika
import json
from datetime import datetime
from fastapi import FastAPI, HTTPException
from loguru import logger

from .config import settings
from .collector import data_collector
from .influx_client import influx_manager

app = FastAPI(title="数据采集服务", version="1.0.0")


def publish_message(routing_key: str, message: dict):
    """发送消息到RabbitMQ"""
    try:
        connection = pika.BlockingConnection(
            pika.ConnectionParameters(
                host=settings.rabbitmq_host,
                port=settings.rabbitmq_port,
                credentials=pika.PlainCredentials(settings.rabbitmq_user, settings.rabbitmq_password),
            )
        )
        channel = connection.channel()
        channel.exchange_declare(exchange="rotation", exchange_type="topic", durable=True)
        channel.basic_publish(
            exchange="rotation",
            routing_key=routing_key,
            body=json.dumps(message, ensure_ascii=False),
        )
        connection.close()
    except Exception as e:
        logger.error(f"RabbitMQ消息发送失败: {e}")


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "data-collector", "timestamp": datetime.now().isoformat()}


@app.post("/collect/sector-flow")
async def collect_sector_flow(trade_date: str = None):
    """触发板块资金流数据采集"""
    try:
        results = data_collector.collect_sector_capital_flow(trade_date)
        # 通知策略引擎数据已更新
        publish_message("data.updated.sector_flow", {
            "event": "sector_flow_updated",
            "trade_date": trade_date or datetime.now().strftime("%Y-%m-%d"),
            "count": len(results),
            "timestamp": datetime.now().isoformat(),
        })
        return {"code": 200, "message": "采集完成", "data": {"count": len(results)}}
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
        return {"code": 200, "message": f"采集历史数据完成", "data": {"count": total}}
    except Exception as e:
        logger.error(f"历史数据采集失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/collect/north-bound")
async def collect_north_bound():
    """采集北向资金数据"""
    try:
        results = data_collector.collect_north_bound_flow()
        return {"code": 200, "message": "北向资金数据采集完成", "data": {"count": len(results)}}
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
        return {"code": 200, "message": f"K线数据采集完成", "data": {"count": len(results)}}
    except Exception as e:
        logger.error(f"K线数据采集失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/trade-dates")
async def get_trade_dates(days: int = 365):
    """获取交易日历"""
    try:
        trade_dates = data_collector.get_trade_dates(days)
        if trade_dates is None:
            return {"code": 200, "data": []}
        # 只返回最近N天
        recent = trade_dates[-days:] if len(trade_dates) > days else trade_dates
        return {"code": 200, "data": recent}
    except Exception as e:
        logger.error(f"获取交易日历失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/query/sector-data")
async def query_sector_data(sector_code: str, start_date: str, end_date: str):
    """查询板块历史数据"""
    try:
        data = influx_manager.query_sector_data(sector_code, start_date, end_date)
        return {"code": 200, "data": data}
    except Exception as e:
        logger.error(f"数据查询失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/query/all-sectors")
async def query_all_sectors(start_date: str, end_date: str):
    """查询所有板块数据"""
    try:
        data = influx_manager.query_all_sectors_data(start_date, end_date)
        return {"code": 200, "data": data}
    except Exception as e:
        logger.error(f"数据查询失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/sectors")
async def get_sectors():
    """获取板块名称列表（同花顺）"""
    try:
        sectors = data_collector.get_sector_names()
        return {"code": 200, "data": sectors}
    except Exception as e:
        logger.error(f"获取板块列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.service_port)
