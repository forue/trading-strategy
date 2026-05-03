"""Agent 基类"""
from abc import ABC, abstractmethod
from typing import Optional
from pydantic import BaseModel


class AgentResponse(BaseModel):
    """Agent 响应"""
    content: str
    agent_name: str
    tools_called: list[str] = []
    metadata: dict = {}


class BaseAgent(ABC):
    """Agent 基类"""

    name: str = "base"
    description: str = ""
    system_prompt: str = ""

    @abstractmethod
    async def run(self, user_message: str, context: dict = None) -> AgentResponse:
        """执行任务"""
        pass

    def _build_messages(self, user_message: str, context: dict = None) -> list[dict]:
        """构建消息列表"""
        messages = [{"role": "system", "content": self.system_prompt}]
        if context and context.get("history"):
            messages.extend(context["history"])
        messages.append({"role": "user", "content": user_message})
        return messages
