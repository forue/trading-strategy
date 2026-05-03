"""AI 决策服务 - 对话管理器

负责对话历史的持久化、恢复、导出。
支持 thinking 内容和流式消息更新。
"""
import json
import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel
from loguru import logger


class ChatMessage(BaseModel):
    """单条消息"""
    role: str              # user / assistant
    content: str
    thinking: str = ""     # 思考过程
    model: str = ""
    tokens_used: int = 0
    timestamp: str = ""


class Conversation(BaseModel):
    """对话会话"""
    id: str
    title: str
    provider: str = ""
    model: str = ""
    messages: list[ChatMessage] = []
    created_at: str = ""
    updated_at: str = ""
    message_count: int = 0


class ChatManager:
    """对话管理器"""

    CONV_LIST_KEY = "ai:conversations"
    CONV_PREFIX = "ai:conv:"
    CONV_TTL = 30 * 86400

    def __init__(self, redis_client):
        self.redis = redis_client

    def create_conversation(self, title: str = "", provider: str = "", model: str = "") -> Conversation:
        conv_id = f"conv_{uuid.uuid4().hex[:12]}"
        now = datetime.now().isoformat()
        conv = Conversation(
            id=conv_id,
            title=title or f"对话 {now[:16]}",
            provider=provider,
            model=model,
            messages=[],
            created_at=now,
            updated_at=now,
            message_count=0,
        )
        self._save(conv)
        self.redis.zadd(self.CONV_LIST_KEY, {conv_id: datetime.now().timestamp()})
        return conv

    def get_conversation(self, conv_id: str) -> Optional[Conversation]:
        raw = self.redis.get(f"{self.CONV_PREFIX}{conv_id}")
        if raw:
            return Conversation.model_validate_json(raw)
        return None

    def list_conversations(self, limit: int = 50) -> list[Conversation]:
        conv_ids = self.redis.zrevrange(self.CONV_LIST_KEY, 0, limit - 1)
        conversations = []
        for conv_id in conv_ids:
            if isinstance(conv_id, bytes):
                conv_id = conv_id.decode()
            conv = self.get_conversation(conv_id)
            if conv:
                conversations.append(conv)
        return conversations

    def add_message(self, conv_id: str, message: ChatMessage) -> bool:
        conv = self.get_conversation(conv_id)
        if not conv:
            return False

        if not message.timestamp:
            message.timestamp = datetime.now().isoformat()

        conv.messages.append(message)
        conv.message_count = len(conv.messages)
        conv.updated_at = datetime.now().isoformat()

        if conv.title.startswith("对话 ") and message.role == "user":
            conv.title = message.content[:30] + ("..." if len(message.content) > 30 else "")

        self._save(conv)
        self.redis.zadd(self.CONV_LIST_KEY, {conv_id: datetime.now().timestamp()})
        return True

    def update_last_message(self, conv_id: str, content: str = None, thinking: str = None, tokens_used: int = None) -> bool:
        """更新最后一条消息（用于流式输出完成后更新）"""
        conv = self.get_conversation(conv_id)
        if not conv or not conv.messages:
            return False

        msg = conv.messages[-1]
        if content is not None:
            msg.content = content
        if thinking is not None:
            msg.thinking = thinking
        if tokens_used is not None:
            msg.tokens_used = tokens_used

        conv.updated_at = datetime.now().isoformat()
        self._save(conv)
        return True

    def delete_conversation(self, conv_id: str) -> bool:
        self.redis.delete(f"{self.CONV_PREFIX}{conv_id}")
        self.redis.zrem(self.CONV_LIST_KEY, conv_id)
        return True

    def export_conversation(self, conv_id: str, fmt: str = "markdown") -> Optional[str]:
        conv = self.get_conversation(conv_id)
        if not conv:
            return None
        if fmt == "markdown":
            return self._to_markdown(conv)
        elif fmt == "json":
            return self._to_json(conv)
        elif fmt == "text":
            return self._to_text(conv)
        return None

    def _save(self, conv: Conversation):
        self.redis.setex(f"{self.CONV_PREFIX}{conv.id}", self.CONV_TTL, conv.model_dump_json())

    def _to_markdown(self, conv: Conversation) -> str:
        lines = [
            f"# {conv.title}", "",
            f"- 创建时间: {conv.created_at[:19]}",
            f"- 模型: {conv.provider}/{conv.model}",
            f"- 消息数: {conv.message_count}", "", "---", "",
        ]
        for msg in conv.messages:
            role = "**用户**" if msg.role == "user" else "**AI 助手**"
            lines.append(f"## {role}")
            lines.append("")
            if msg.thinking:
                lines.append(f"<details><summary>思考过程</summary>\n\n{msg.thinking}\n\n</details>\n")
            lines.append(msg.content)
            lines.append("")
            if msg.model:
                lines.append(f"*模型: {msg.model} | Tokens: {msg.tokens_used}*")
                lines.append("")
        lines.extend(["---", f"*导出时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*"])
        return "\n".join(lines)

    def _to_json(self, conv: Conversation) -> str:
        return conv.model_dump_json(indent=2)

    def _to_text(self, conv: Conversation) -> str:
        lines = [conv.title, "=" * 40, ""]
        for msg in conv.messages:
            role = "用户" if msg.role == "user" else "AI"
            lines.append(f"[{role}] {msg.content}")
            lines.append("")
        return "\n".join(lines)
