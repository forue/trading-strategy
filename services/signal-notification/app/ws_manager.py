"""信号通知服务 - WebSocket连接管理器"""
from fastapi import WebSocket
from typing import Dict, Set
from loguru import logger


class ConnectionManager:
    """WebSocket连接管理器"""

    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.user_subscriptions: Dict[str, Set[str]] = {}  # user_id -> {strategy_types}

    async def connect(self, websocket: WebSocket, user_id: str):
        """建立WebSocket连接"""
        await websocket.accept()
        self.active_connections[user_id] = websocket
        self.user_subscriptions.setdefault(user_id, set())
        logger.info(f"WebSocket连接建立: user={user_id}, 当前连接数={len(self.active_connections)}")

    def disconnect(self, user_id: str):
        """断开WebSocket连接"""
        self.active_connections.pop(user_id, None)
        self.user_subscriptions.pop(user_id, None)
        logger.info(f"WebSocket连接断开: user={user_id}, 当前连接数={len(self.active_connections)}")

    async def send_personal_message(self, message: dict, user_id: str):
        """发送个人消息（5秒超时，避免慢客户端阻塞广播）"""
        websocket = self.active_connections.get(user_id)
        if websocket:
            try:
                import asyncio
                await asyncio.wait_for(websocket.send_json(message), timeout=5)
            except asyncio.TimeoutError:
                logger.warning(f"WebSocket 发送超时(5s)，断开: user={user_id}")
                self.disconnect(user_id)
            except Exception as e:
                logger.error(f"发送消息失败: user={user_id}, error={e}")
                self.disconnect(user_id)

    async def broadcast_signal(self, signal: dict, strategy_type: str = None):
        """广播单个信号（兼容旧调用，内部转为批量）"""
        return await self.broadcast_signals([signal], strategy_type)

    async def broadcast_signals(self, signals: list, strategy_type: str = None, prefs: dict = None):
        """批量广播信号给订阅了该策略的用户（一次WebSocket消息含该策略全部信号）

        prefs: {user_id: {"enabled": bool, "types": set}} 由调用方按用户的
        实时推送偏好加载；关闭推送或不在订阅档位内的用户不下发。
        """
        sent_count = 0
        message = {
            "type": "signals",
            "strategy_type": strategy_type,
            "signals": signals,
            "count": len(signals),
        }
        for user_id, subscriptions in list(self.user_subscriptions.items()):
            pref = (prefs or {}).get(str(user_id))
            if pref is not None:
                if not pref.get("enabled", True):
                    continue
                types = pref.get("types") or set()
                if strategy_type and types and strategy_type not in types:
                    continue
            if strategy_type is None or not subscriptions or strategy_type in subscriptions:
                await self.send_personal_message(message, user_id)
                sent_count += 1
        logger.info(f"信号广播完成: strategy={strategy_type}, 信号{len(signals)}条, 发送{sent_count}个客户端")
        return sent_count

    async def send_signals_to_user(
        self, signals: list, strategy_type: str, user_id, prefs: dict | None = None,
    ) -> bool:
        """只把信号下发给指定用户

        信号已按账号隔离计算，甲账号的信号不能广播给乙账号；是否下发仍尊重
        该用户自己的实时推送开关与订阅档位。
        """
        pref = (prefs or {}).get(str(user_id))
        if pref is not None:
            if not pref.get("enabled", True):
                return False
            types = pref.get("types") or set()
            if strategy_type and types and strategy_type not in types:
                return False
        await self.send_personal_message({
            "type": "signals",
            "strategy_type": strategy_type,
            "signals": signals,
            "count": len(signals),
        }, str(user_id))
        return True

    def subscribe(self, user_id: str, strategy_type: str):
        """用户订阅策略信号"""
        self.user_subscriptions.setdefault(user_id, set()).add(strategy_type)

    def unsubscribe(self, user_id: str, strategy_type: str):
        """用户取消订阅"""
        subs = self.user_subscriptions.get(user_id)
        if subs:
            subs.discard(strategy_type)

    @property
    def connection_count(self) -> int:
        return len(self.active_connections)


# 全局实例
ws_manager = ConnectionManager()
