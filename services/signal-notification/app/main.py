"""信号通知服务 - FastAPI主应用 (WebSocket + RabbitMQ消费 + 外部推送通道)"""
import sys
import os
import json
import asyncio
import threading
from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, HTTPException, Header
from loguru import logger

# 添加共享库路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from .config import settings
from .ws_manager import ws_manager
from .notify_channels import NotifyChannelManager
from shared import (
    ADMIN_USER_ID,
    AuthError,
    RabbitMQManager,
    RedisManager,
    get_current_user,
    set_jwt_secret,
    user_scope,
)

# 配置日志
logger.remove()
logger.add(sys.stderr, level=settings.log_level)

app = FastAPI(title="信号通知服务", version="1.2.0")

# 初始化连接管理器
rmq = RabbitMQManager()
redis_mgr = RedisManager()
_mq_thread = None

# 主事件循环引用（供 RabbitMQ 消费线程使用）
_main_loop: asyncio.AbstractEventLoop = None

# 推送配置按用户隔离：user:{id}:notify_config
# 另外用集合登记配置过通道的用户，供信号分发时遍历（信号全局计算，但每人推自己的通道）
NOTIFY_USERS_KEY = "notify:users"

# 与 auth 服务共用密钥，本地验签识别当前用户
set_jwt_secret(settings.jwt_secret)


def _notify_config_key(user_id: int) -> str:
    return f"{user_scope(user_id)}:notify_config"


def _ws_pref_key(user_id, key: str) -> str:
    """实时推送偏好由 strategy 服务写入，两个服务同为 redis db 1，可直接读"""
    return f"{user_scope(int(user_id))}:settings:{key}"


def _require_user(authorization: str | None):
    try:
        return get_current_user(authorization)
    except AuthError as e:
        raise HTTPException(status_code=401, detail=str(e))


def _resolve_user_id(
    authorization: str | None, internal_token: str | None = None,
) -> int:
    """确定信号数据归属账号

    浏览器带 JWT；ai-decision 等内部服务带共享密钥。两者皆无时保持旧行为
    （视为管理员），但一旦配置了 INTERNAL_TOKEN 就拒绝匿名请求。
    """
    if settings.internal_token and internal_token and internal_token == settings.internal_token:
        return ADMIN_USER_ID
    if authorization:
        return int(_require_user(authorization).user_id)
    if settings.internal_token:
        raise HTTPException(status_code=401, detail="缺少访问凭证")
    return ADMIN_USER_ID


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
    _migrate_legacy_notify_config()
    # 连接建立后启动 RabbitMQ 消费者
    global _mq_thread
    _mq_thread = threading.Thread(target=start_rabbitmq_consumer, daemon=True)
    _mq_thread.start()
    # AI解读结果消费者（合并AI分析后推送）
    threading.Thread(target=start_ai_consumer, daemon=True).start()
    # 待推送超时兜底
    threading.Thread(target=start_pending_watchdog, daemon=True).start()
    logger.info("信号通知服务启动完成")


@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭事件"""
    rmq.close()
    redis_mgr.close()


def _empty_config() -> dict:
    return {
        "dingtalk": {"enabled": False, "webhook_url": "", "secret": ""},
        "wecom": {"enabled": False, "webhook_url": ""},
    }


def _env_default_config() -> dict:
    """环境变量里的通道配置，只作为管理员账号的初始值，不覆盖任何个人配置"""
    return {
        "dingtalk": {
            "enabled": settings.dingtalk_enabled,
            "webhook_url": settings.dingtalk_webhook_url,
            "secret": settings.dingtalk_secret,
        },
        "wecom": {
            "enabled": settings.wecom_enabled,
            "webhook_url": settings.wecom_webhook_url,
        },
    }


def _load_notify_config(user_id: int) -> dict:
    """读取指定用户的推送通道配置；无个人配置时为未启用状态"""
    try:
        raw = redis_mgr.get(_notify_config_key(user_id))
        if raw:
            saved = json.loads(raw)
            config = _empty_config()
            for channel, cfg in config.items():
                cfg.update(saved.get(channel) or {})
            return config
    except Exception as e:
        logger.warning(f"读取推送通道配置失败(user={user_id}): {e}")
    return _env_default_config() if user_id == ADMIN_USER_ID else _empty_config()


def _save_notify_config_to_redis(user_id: int, config: dict):
    """将推送通道配置持久化到用户的 Redis 键，并登记到分发表"""
    try:
        redis_mgr.set(_notify_config_key(user_id), json.dumps(config, ensure_ascii=False))
        redis_mgr.client.sadd(NOTIFY_USERS_KEY, user_id)
        logger.info(f"推送通道配置已保存: user={user_id}")
    except Exception as e:
        logger.error(f"保存推送通道配置失败(user={user_id}): {e}")


def _configured_user_ids() -> list[int]:
    """所有配置过推送通道的用户"""
    try:
        return sorted(int(uid) for uid in redis_mgr.client.smembers(NOTIFY_USERS_KEY))
    except Exception as e:
        logger.warning(f"读取推送用户索引失败: {e}")
        return []


def _migrate_legacy_notify_config():
    """历史全局推送配置归并到管理员账号（幂等）

    改造前所有用户共用一份 notify_channels_config，这里搬到 user:1 下并删除旧键，
    避免全局 webhook 继续被当作系统通道使用。
    """
    legacy_key = "notify_channels_config"
    try:
        raw = redis_mgr.get(legacy_key)
        if not raw:
            return
        target_key = _notify_config_key(ADMIN_USER_ID)
        if redis_mgr.get(target_key) is None:
            redis_mgr.set(target_key, raw)
            logger.info("历史推送通道配置已迁移到管理员账号")
        redis_mgr.client.sadd(NOTIFY_USERS_KEY, ADMIN_USER_ID)
        redis_mgr.delete(legacy_key)
    except Exception as e:
        logger.warning(f"迁移历史推送通道配置失败: {e}")


# 等待 AI 解读的待推送消息：{f"{strategy}:{date}": {payload, created_at}}
_pending_push: dict[str, dict] = {}
_pending_lock = threading.Lock()


def _pending_key(strategy_type: str, signal_date: str, user_id=None) -> str:
    """待推送暂存键：同一策略同一天不同账号的信号必须分开暂存"""
    prefix = f"{int(user_id)}:" if user_id is not None else ""
    return f"{prefix}{strategy_type}:{signal_date}"


def _parse_setting(raw):
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw


def _load_ws_prefs(user_ids) -> dict:
    """读取每个已连接用户的实时推送偏好

    偏好由 strategy 服务的 /settings 写入 user:{id}:settings:*，两个服务同为 db 1。
    默认（未设置）为开启且全档位，与历史行为一致。
    """
    prefs = {}
    for uid in user_ids:
        try:
            enabled_raw = redis_mgr.get(_ws_pref_key(uid, "ws_push_enabled"))
            types_raw = redis_mgr.get(_ws_pref_key(uid, "ws_push_strategy_types"))
        except Exception:
            enabled_raw = types_raw = None

        enabled = True if enabled_raw is None else _parse_setting(enabled_raw) is not False
        types = set()
        if types_raw:
            parsed = _parse_setting(types_raw)
            if isinstance(parsed, list):
                types = set(parsed)
        prefs[str(uid)] = {"enabled": enabled, "types": types}
    return prefs


def _broadcast_and_cache(signals: list, strategy_type: str, signal_date: str, user_id):
    """把信号缓存到该账号名下，并只推给该账号的在线连接

    信号按账号各自的参数计算，不再广播给所有人：否则乙账号会看到甲账号
    参数算出来的板块与仓位。
    """
    if _main_loop and not _main_loop.is_closed():
        prefs = _load_ws_prefs([str(user_id)])
        future = asyncio.run_coroutine_threadsafe(
            ws_manager.send_signals_to_user(signals, strategy_type, user_id, prefs),
            _main_loop,
        )
        try:
            future.result(timeout=5)
        except Exception as e:
            logger.error(f"WebSocket下发失败(user={user_id}): {e}")

    redis_mgr.setex(
        _signal_cache_key(user_id, strategy_type, signal_date),
        86400 * 7,
        json.dumps(signals, ensure_ascii=False),
    )


def _signal_cache_key(user_id, strategy_type: str, signal_date: str) -> str:
    """信号缓存键（与 strategy 服务保持同一套 user:{id}: 前缀）"""
    return f"user:{int(user_id)}:signals:{strategy_type}:{signal_date}"


def _do_push(
    signals: list, strategy_type: str, signal_date: str,
    user_id, ai_analyses: list = None,
):
    """只向该账号自己的推送通道发外部通知"""
    config = _load_notify_config(user_id)
    if not (config["dingtalk"]["enabled"] or config["wecom"]["enabled"]):
        logger.info(f"账号未启用推送通道，跳过外部推送: user={user_id}, {strategy_type}")
        return

    manager = NotifyChannelManager()
    manager.load_config(config)

    async def _push_one():
        return await manager.push_signal(
            signals, strategy_type, signal_date, ai_analyses=ai_analyses,
        )

    try:
        if _main_loop and not _main_loop.is_closed():
            future = asyncio.run_coroutine_threadsafe(_push_one(), _main_loop)
            future.result(timeout=60)
        logger.info(f"外部推送完成: user={user_id}, strategy={strategy_type}")
    except Exception as e:
        logger.error(f"外部推送失败(user={user_id}): {e}")


def _has_trade_signal(signals: list) -> bool:
    return any(s.get("direction") in ("BUY", "SELL") for s in signals or [])


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
                # 旧消息可能没有 user_id（改造前的全局信号），归到管理员账号
                user_id = int(message.get("user_id") or ADMIN_USER_ID)

                # 1. 缓存 + 只下发该账号的在线连接（不等待AI，保证前端及时可见）
                _broadcast_and_cache(signals, strategy_type, signal_date, user_id)

                # 2. 外部推送：有买卖信号且开启AI推送时，等待AI解读合并后再推送
                if settings.ai_push_enabled and _has_trade_signal(signals):
                    with _pending_lock:
                        _pending_push[_pending_key(strategy_type, signal_date, user_id)] = {
                            "signals": signals,
                            "strategy_type": strategy_type,
                            "signal_date": signal_date,
                            "user_id": user_id,
                            "created_at": datetime.now().timestamp(),
                        }
                    logger.info(
                        f"信号已暂存，等待AI解读后合并推送 "
                        f"(最多等待{settings.ai_push_wait_seconds}s): user={user_id}, "
                        f"{strategy_type} {signal_date}"
                    )
                elif not _has_trade_signal(signals):
                    # 空仓/清仓（无买卖信号）：仅缓存与下发，不推送外部渠道。
                    # "今日无信号"属于可从前端直接获知的状态，推送只会造成打扰
                    logger.info(
                        f"无买卖信号，跳过外部推送: user={user_id}, {strategy_type} {signal_date}"
                    )
                else:
                    _do_push(signals, strategy_type, signal_date, user_id)
                    logger.info(
                        f"信号处理完成: user={user_id}, {len(signals)}条, strategy={strategy_type}"
                    )

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


def start_ai_consumer():
    """启动AI解读结果消费者：收到解读后与暂存的信号合并推送"""
    def callback(ch, method, properties, body):
        try:
            message = json.loads(body)
            if message.get("event") != "signal_analyzed":
                return

            strategy_type = message.get("strategy_type", "")
            signal_date = message.get("signal_date", "")
            analyses = message.get("analyses", [])
            user_id = int(message.get("user_id") or ADMIN_USER_ID)
            key = _pending_key(strategy_type, signal_date, user_id)

            with _pending_lock:
                pending = _pending_push.pop(key, None)

            if not pending:
                logger.debug(f"无待推送信号与AI解读匹配: {key}")
                return

            logger.info(f"收到AI解读，合并推送: {key} ({len(analyses)}条解读)")
            _do_push(
                pending["signals"], strategy_type, signal_date, user_id,
                ai_analyses=analyses,
            )
        except Exception as e:
            logger.error(f"AI解读消息处理失败: {e}")

    try:
        rmq.consume(
            queue="signal_notification_ai",
            callback=callback,
            routing_key="ai.#",
        )
    except Exception as e:
        logger.error(f"AI解读消费者启动失败: {e}")


def start_pending_watchdog():
    """超时兜底：AI解读迟迟未到时，降级为不含AI分析的推送，避免信号被无限期推迟"""
    import time as _time

    while True:
        _time.sleep(15)
        try:
            now = datetime.now().timestamp()
            expired = []
            with _pending_lock:
                for key, item in list(_pending_push.items()):
                    if now - item["created_at"] >= settings.ai_push_wait_seconds:
                        expired.append(_pending_push.pop(key))
            for item in expired:
                logger.warning(
                    f"等待AI解读超时({settings.ai_push_wait_seconds}s)，降级推送: "
                    f"user={item.get('user_id')}, {item['strategy_type']} {item['signal_date']}"
                )
                _do_push(
                    item["signals"], item["strategy_type"], item["signal_date"],
                    int(item.get("user_id") or ADMIN_USER_ID),
                )
        except Exception as e:
            logger.error(f"待推送超时检查失败: {e}")


@app.get("/health")
async def health_check():
    checks = {}
    # RabbitMQ consumer thread
    mq_alive = _mq_thread is not None and _mq_thread.is_alive()
    checks["mq_consumer"] = {"status": "pass" if mq_alive else "fail"}
    # RabbitMQ connection
    try:
        rmq_ok = rmq._connection and rmq._connection.is_open
        checks["rabbitmq"] = {"status": "pass" if rmq_ok else "fail"}
    except Exception as e:
        checks["rabbitmq"] = {"status": "fail", "message": str(e)}
    # Redis
    try:
        redis_mgr._client.ping()
        checks["redis"] = {"status": "pass"}
    except Exception as e:
        checks["redis"] = {"status": "fail", "message": str(e)}

    all_ok = all(c.get("status") == "pass" for c in checks.values())
    return {
        "status": "healthy" if all_ok else "degraded",
        "service": "signal-notification",
        "ws_connections": ws_manager.connection_count,
        "notify_channels": {
            "configured_users": len(_configured_user_ids()),
        },
        "checks": checks,
        "timestamp": datetime.now().isoformat(),
    }


@app.websocket("/ws/signals")
async def websocket_signals(websocket: WebSocket, token: str = Query(None)):
    """WebSocket信号推送端点：token 解析出真实用户，实时推送偏好按用户生效"""
    try:
        if not token:
            raise AuthError("缺少 token")
        user = get_current_user(f"Bearer {token}")
    except AuthError as e:
        logger.warning(f"WebSocket 鉴权失败: {e}")
        await websocket.close(code=1008)
        return

    user_id = str(user.user_id)
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
async def get_notify_config(authorization: str | None = Header(None, alias="Authorization")):
    """获取当前用户的推送通道配置"""
    user = _require_user(authorization)
    config = _load_notify_config(user.user_id)
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
async def update_notify_config(config_body: dict, authorization: str | None = Header(None, alias="Authorization")):
    """更新当前用户的推送通道配置"""
    user = _require_user(authorization)
    try:
        current = _load_notify_config(user.user_id)
        for channel in ["dingtalk", "wecom"]:
            if channel in config_body:
                for key, value in config_body[channel].items():
                    if key in current[channel]:
                        current[channel][key] = value

        _save_notify_config_to_redis(user.user_id, current)

        return {"code": 200, "message": "推送通道配置已更新", "data": current}
    except Exception as e:
        logger.error(f"更新推送通道配置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/signals/notify/test/{channel}")
async def test_notify_channel(
    channel: str,
    strategy_type: str = "MODERATE",
    authorization: str | None = Header(None, alias="Authorization"),
):
    """用当前用户自己的通道配置发送测试消息"""
    user = _require_user(authorization)
    if channel not in ("dingtalk", "wecom"):
        raise HTTPException(status_code=400, detail="不支持的通道类型，可选: dingtalk, wecom")

    notify_manager = NotifyChannelManager()
    notify_manager.load_config(_load_notify_config(user.user_id))

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
async def get_today_signals(
    strategy_type: str,
    authorization: str | None = Header(None, alias="Authorization"),
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    """获取当前账号的今日信号（REST接口）"""
    user_id = _resolve_user_id(authorization, x_internal_token)
    today = datetime.now().strftime("%Y-%m-%d")
    cached = redis_mgr.get(_signal_cache_key(user_id, strategy_type, today))
    if cached:
        return {"code": 200, "data": json.loads(cached)}
    return {"code": 200, "data": []}


@app.get("/signals/history")
async def get_signal_history(
    strategy_type: str,
    start_date: str,
    end_date: str,
    authorization: str | None = Header(None, alias="Authorization"),
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    """获取当前账号的历史信号"""
    from datetime import timedelta
    user_id = _resolve_user_id(authorization, x_internal_token)
    signals = []
    current = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    while current <= end:
        date_str = current.strftime("%Y-%m-%d")
        cached = redis_mgr.get(_signal_cache_key(user_id, strategy_type, date_str))
        if cached:
            signals.extend(json.loads(cached))
        current += timedelta(days=1)
    return {"code": 200, "data": signals}


@app.get("/signals/calendar")
async def get_signal_calendar(strategy_type: str, month: str):
    """获取信号日历数据

    除真实信号外，还需为"已计算但空仓"的日期输出空仓标记
    （direction=EMPTY / is_empty_position=True），供前端日历用独立颜色区分
    "空仓"与"未计算/无数据"。

    注意：已计算但空仓的日期，信号缓存是空列表 "[]"（键存在）而非不存在，
    因此不能用 `if cached:` 判断"是否有信号"，否则空仓标记会被短路而永远不输出。
    """
    import calendar
    from datetime import timedelta

    year, m = month.split("-")
    last_day = calendar.monthrange(int(year), int(m))[1]

    signals: list = []
    current = datetime(int(year), int(m), 1)
    for _ in range(last_day):
        date_str = current.strftime("%Y-%m-%d")
        current += timedelta(days=1)

        key = f"signals:{strategy_type}:{date_str}"
        cached = redis_mgr.get(key)
        day_signals: list = []
        if cached:
            try:
                day_signals = json.loads(cached) or []
            except (json.JSONDecodeError, TypeError):
                day_signals = []
        if day_signals:
            for sig in day_signals:
                sig["signal_date"] = date_str
            signals.extend(day_signals)
            continue

        raw_status = redis_mgr.get(f"{key}:status")
        if cached is None and not raw_status:
            # 既无信号缓存也无状态缓存 → 未计算/无数据，不输出标记
            continue

        status = {}
        if raw_status:
            try:
                status = json.loads(raw_status) or {}
            except (json.JSONDecodeError, TypeError):
                status = {}
        if status.get("position_status", "EMPTY") != "EMPTY":
            continue

        signals.append({
            "signal_date": date_str,
            "strategy_type": strategy_type,
            "sector_code": "",
            "sector_name": "空仓",
            "direction": "EMPTY",
            "position_ratio": 0.0,
            "score": 0.0,
            "reason": status.get("empty_reason") or "当日空仓，无持仓信号",
            "is_empty_position": True,
            "market_regime": status.get("market_regime", ""),
        })
    return {"code": 200, "data": signals}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.service_port)
