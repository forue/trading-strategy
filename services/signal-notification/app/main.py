"""信号通知服务 - FastAPI主应用 (WebSocket + RabbitMQ消费 + 外部推送通道)"""
import sys
import os
import json
import asyncio
import threading
from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, HTTPException
from loguru import logger

# 添加共享库路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from .config import settings
from .ws_manager import ws_manager
from .notify_channels import notify_manager
from shared import RabbitMQManager, RedisManager

# 配置日志
logger.remove()
logger.add(sys.stderr, level=settings.log_level)

app = FastAPI(title="信号通知服务", version="1.2.0")

# 初始化连接管理器
rmq = RabbitMQManager()
redis_mgr = RedisManager()

# 主事件循环引用（供 RabbitMQ 消费线程使用）
_main_loop: asyncio.AbstractEventLoop = None

# 推送配置在 Redis 中的 key
NOTIFY_CONFIG_KEY = "notify_channels_config"


@app.on_event("startup")
async def startup_event():
    """应用启动事件 - 初始化连接和加载配置"""
    global _main_loop
    _main_loop = asyncio.get_event_loop()
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
    _load_notify_config()
    # 连接建立后启动 RabbitMQ 消费者
    mq_thread = threading.Thread(target=start_rabbitmq_consumer, daemon=True)
    mq_thread.start()
    logger.info("信号通知服务启动完成")


@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭事件"""
    rmq.close()
    redis_mgr.close()


def _load_notify_config():
    """从 Redis 加载推送通道配置，覆盖环境变量默认值"""
    try:
        raw = redis_mgr.get(NOTIFY_CONFIG_KEY)
        if raw:
            config = json.loads(raw)
            notify_manager.load_config(config)
            logger.info("从Redis加载推送通道配置成功")
            return
    except Exception as e:
        logger.warning(f"从Redis加载推送通道配置失败: {e}")

    # 使用环境变量作为初始配置
    notify_manager.load_config({
        "dingtalk": {
            "enabled": settings.dingtalk_enabled,
            "webhook_url": settings.dingtalk_webhook_url,
            "secret": settings.dingtalk_secret,
        },
        "wecom": {
            "enabled": settings.wecom_enabled,
            "webhook_url": settings.wecom_webhook_url,
        },
    })


def _save_notify_config_to_redis(config: dict):
    """将推送通道配置持久化到 Redis"""
    try:
        redis_mgr.set(NOTIFY_CONFIG_KEY, json.dumps(config, ensure_ascii=False))
        logger.info("推送通道配置已保存到Redis")
    except Exception as e:
        logger.error(f"保存推送通道配置到Redis失败: {e}")


def start_rabbitmq_consumer():
    """启动RabbitMQ消费者，监听策略信号"""
    def callback(ch, method, properties, body):
        try:
            message = json.loads(body)
            event = message.get("event", "")
            logger.info(f"收到消息: {event}, routing_key={method.routing_key}")

            if event == "signals_generated":
                signals = message.get("signals", [])
                strategy_type = message.get("strategy_type", "")
                signal_date = message.get("signal_date", datetime.now().strftime("%Y-%m-%d"))

                # 1. 通过WebSocket广播信号（在主事件循环上执行）
                if _main_loop and not _main_loop.is_closed():
                    for signal in signals:
                        future = asyncio.run_coroutine_threadsafe(
                            ws_manager.broadcast_signal(signal, strategy_type), _main_loop
                        )
                        try:
                            future.result(timeout=5)
                        except Exception as e:
                            logger.error(f"WebSocket广播失败: {e}")

                # 2. 外部推送通道（钉钉、企业微信）
                try:
                    if _main_loop and not _main_loop.is_closed():
                        future = asyncio.run_coroutine_threadsafe(
                            notify_manager.push_signal(signals, strategy_type, signal_date), _main_loop
                        )
                        future.result(timeout=10)
                except Exception as e:
                    logger.error(f"外部推送失败: {e}")

                # 3. 缓存信号到Redis
                redis_mgr.setex(
                    f"signals:{strategy_type}:{signal_date}",
                    86400 * 7,
                    json.dumps(signals, ensure_ascii=False),
                )
                logger.info(f"信号处理完成: {len(signals)}条, strategy={strategy_type}")

        except Exception as e:
            logger.error(f"消息处理失败: {e}")

    try:
        rmq.consume(
            queue="signal_notification",
            callback=callback,
            routing_key="signal.#",
        )
    except Exception as e:
        logger.error(f"RabbitMQ消费者启动失败: {e}")


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "signal-notification",
        "ws_connections": ws_manager.connection_count,
        "notify_channels": {
            "dingtalk": notify_manager.dingtalk.enabled,
            "wecom": notify_manager.wecom.enabled,
        },
        "timestamp": datetime.now().isoformat(),
    }


@app.websocket("/ws/signals")
async def websocket_signals(websocket: WebSocket, token: str = Query(None)):
    """WebSocket信号推送端点"""
    user_id = token or f"anonymous_{id(websocket)}"
    await ws_manager.connect(websocket, user_id)
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            msg_type = msg.get("type", "")

            if msg_type == "subscribe":
                strategy_type = msg.get("strategy_type", "")
                if strategy_type:
                    ws_manager.subscribe(user_id, strategy_type)
                    await websocket.send_json({"type": "subscribed", "strategy_type": strategy_type})

            elif msg_type == "unsubscribe":
                strategy_type = msg.get("strategy_type", "")
                if strategy_type:
                    ws_manager.unsubscribe(user_id, strategy_type)
                    await websocket.send_json({"type": "unsubscribed", "strategy_type": strategy_type})

            elif msg_type == "ping":
                await websocket.send_json({"type": "pong", "timestamp": datetime.now().isoformat()})

    except WebSocketDisconnect:
        ws_manager.disconnect(user_id)


# ==================== 推送通道配置 API ====================

@app.get("/signals/notify/config")
async def get_notify_config():
    """获取推送通道配置"""
    config = notify_manager.get_config()
    # 隐藏 webhook_url 的敏感部分
    masked_config = {}
    for channel, cfg in config.items():
        masked_cfg = {**cfg}
        if cfg.get("webhook_url"):
            url = cfg["webhook_url"]
            if len(url) > 45:
                masked_cfg["webhook_url_display"] = url[:30] + "..." + url[-10:]
            else:
                masked_cfg["webhook_url_display"] = url[:15] + "..."
        else:
            masked_cfg["webhook_url_display"] = ""
        masked_config[channel] = masked_cfg
    return {"code": 200, "data": masked_config}


@app.put("/signals/notify/config")
async def update_notify_config(config_body: dict):
    """更新推送通道配置"""
    try:
        current = notify_manager.get_config()
        for channel in ["dingtalk", "wecom"]:
            if channel in config_body:
                for key, value in config_body[channel].items():
                    if key in current[channel]:
                        current[channel][key] = value

        notify_manager.load_config(current)
        _save_notify_config_to_redis(current)

        return {"code": 200, "message": "推送通道配置已更新", "data": notify_manager.get_config()}
    except Exception as e:
        logger.error(f"更新推送通道配置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/signals/notify/test/{channel}")
async def test_notify_channel(channel: str, strategy_type: str = "MODERATE"):
    """测试推送通道"""
    if channel not in ("dingtalk", "wecom"):
        raise HTTPException(status_code=400, detail="不支持的通道类型，可选: dingtalk, wecom")

    test_signals = [
        {
            "signal_date": datetime.now().strftime("%Y-%m-%d"),
            "strategy_type": strategy_type,
            "sector_code": "SW801780",
            "sector_name": "银行",
            "etf_code": "512800",
            "etf_name": "银行ETF",
            "direction": "BUY",
            "position_ratio": 0.3,
            "score": 7.5,
            "reason": f"【测试消息】{strategy_type}策略: 银行板块资金流入排名靠前",
        },
        {
            "signal_date": datetime.now().strftime("%Y-%m-%d"),
            "strategy_type": strategy_type,
            "sector_code": "SW801040",
            "sector_name": "钢铁",
            "etf_code": "562300",
            "etf_name": "钢铁ETF",
            "direction": "SELL",
            "position_ratio": 0,
            "score": 2.1,
            "reason": "【测试消息】钢铁板块资金流出，评分低于阈值",
        },
    ]

    try:
        if channel == "dingtalk":
            if not notify_manager.dingtalk.enabled:
                raise HTTPException(status_code=400, detail="钉钉推送未启用")
            await notify_manager.dingtalk.send(test_signals, strategy_type, datetime.now().strftime("%Y-%m-%d"), is_test=True)
        elif channel == "wecom":
            if not notify_manager.wecom.enabled:
                raise HTTPException(status_code=400, detail="企业微信推送未启用")
            await notify_manager.wecom.send(test_signals, strategy_type, datetime.now().strftime("%Y-%m-%d"), is_test=True)

        return {"code": 200, "message": f"{channel} 测试消息已发送"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"测试推送失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 信号查询 API ====================

@app.get("/signals/today")
async def get_today_signals(strategy_type: str):
    """获取今日信号（REST接口）"""
    today = datetime.now().strftime("%Y-%m-%d")
    cached = redis_mgr.get(f"signals:{strategy_type}:{today}")
    if cached:
        return {"code": 200, "data": json.loads(cached)}
    return {"code": 200, "data": []}


@app.get("/signals/history")
async def get_signal_history(strategy_type: str, start_date: str, end_date: str):
    """获取历史信号"""
    from datetime import timedelta
    signals = []
    current = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    while current <= end:
        date_str = current.strftime("%Y-%m-%d")
        cached = redis_mgr.get(f"signals:{strategy_type}:{date_str}")
        if cached:
            signals.extend(json.loads(cached))
        current += timedelta(days=1)
    return {"code": 200, "data": signals}


@app.get("/signals/calendar")
async def get_signal_calendar(strategy_type: str, month: str):
    """获取信号日历数据"""
    import calendar
    start = f"{month}-01"
    year, m = month.split("-")
    last_day = calendar.monthrange(int(year), int(m))[1]
    end = f"{month}-{last_day:02d}"
    return await get_signal_history(strategy_type, start, end)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.service_port)
