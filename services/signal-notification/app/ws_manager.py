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
        """发送个人消息"""
        websocket = self.active_connections.get(user_id)
        if websocket:
            try:
                import json
                await websocket.send_json(message)
            except Exception as e:
                logger.error(f"发送消息失败: user={user_id}, error={e}")
                self.disconnect(user_id)

    async def broadcast_signal(self, signal: dict, strategy_type: str = None):
        """广播单个信号（兼容旧调用，内部转为批量）"""
        return await self.broadcast_signals([signal], strategy_type)

    async def broadcast_signals(self, signals: list, strategy_type: str = None):
        """批量广播信号给订阅了该策略的用户（一次WebSocket消息含该策略全部信号）"""
        sent_count = 0
        message = {
            "type": "signals",
            "strategy_type": strategy_type,
            "signals": signals,
            "count": len(signals),
        }
        for user_id, subscriptions in self.user_subscriptions.items():
            if strategy_type is None or not subscriptions or strategy_type in subscriptions:
                await self.send_personal_message(message, user_id)
                sent_count += 1
        logger.info(f"信号广播完成: strategy={strategy_type}, 信号{len(signals)}条, 发送{sent_count}个客户端")
        return sent_count

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
