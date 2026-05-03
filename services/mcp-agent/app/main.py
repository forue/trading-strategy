"""MCP 金融 Agent 服务 - FastAPI 主应用

支持两种访问方式：
1. MCP 协议 (SSE) - 供 MCP 客户端使用
2. REST API - 供前端和第三方调用
"""
import sys
import os
import json
from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse, Response
from pydantic import BaseModel
from loguru import logger
from mcp.server.sse import SseServerTransport
from starlette.routing import Route, Mount

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from .config import settings
from .tools.market import MarketTools
from .tools.strategy import StrategyTools
from .tools.signal import SignalTools
from .tools.data import DataTools
from .agents.router import AgentRouter
from .server import MCPServer
from shared import success_response, error_response

logger.remove()
logger.add(sys.stderr, level=settings.log_level)

# 初始化工具
market_tools = MarketTools(settings.strategy_url, settings.data_collector_url)
strategy_tools = StrategyTools(settings.strategy_url)
signal_tools = SignalTools(settings.signal_url, settings.strategy_url)
data_tools = DataTools(settings.data_collector_url, settings.strategy_url)

# 初始化 Agent 路由器
agent_router = AgentRouter(market_tools, strategy_tools, signal_tools, data_tools)

# 初始化 MCP Server
mcp_server = MCPServer(market_tools, strategy_tools, signal_tools, data_tools)

# MCP SSE 传输
sse_transport = SseServerTransport("/mcp/messages")


async def handle_mcp_sse(request: Request):
    """MCP SSE 连接处理"""
    async with sse_transport.connect_sse(
        request.scope, request.receive, request._send
    ) as streams:
        await mcp_server.server.run(
            streams[0],
            streams[1],
            mcp_server.server.create_initialization_options(),
        )
    return Response()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("MCP 金融 Agent 服务启动")
    yield
    logger.info("MCP 金融 Agent 服务关闭")


# 创建 FastAPI 应用
app = FastAPI(title="MCP 金融 Agent 服务", version="1.0.0", lifespan=lifespan)

# 注册 MCP 路由
app.router.routes.append(Route("/mcp/sse", endpoint=handle_mcp_sse))
app.router.routes.append(Mount("/mcp/messages", app=sse_transport.handle_post_message))


# ============================================================
# REST API 端点
# ============================================================

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "mcp-agent", "timestamp": datetime.now().isoformat()}


class ChatRequest(BaseModel):
    message: str
    conversation_id: str = ""
    agent: str = "auto"


@app.post("/api/mcp/chat")
async def chat(request: ChatRequest):
    """Agent 对话"""
    try:
        response = await agent_router.route(
            user_message=request.message,
            agent_name=request.agent if request.agent != "auto" else None,
        )
        return success_response(data={
            "reply": response.content,
            "agent_used": response.agent_name,
            "tools_called": response.tools_called,
            "conversation_id": request.conversation_id or f"conv_{datetime.now().strftime('%Y%m%d%H%M%S')}",
        })
    except Exception as e:
        logger.error(f"Agent 对话失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/mcp/tools")
async def list_tools():
    """列出所有可用 MCP 工具"""
    tools = mcp_server._get_all_tools()
    return success_response(data=[
        {
            "name": t.name,
            "description": t.description,
            "parameters": t.inputSchema,
        }
        for t in tools
    ])


@app.get("/api/mcp/agents")
async def list_agents():
    """列出所有 Agent"""
    return success_response(data=agent_router.get_agent_info())


class ToolCallRequest(BaseModel):
    tool: str
    arguments: dict = {}


@app.post("/api/mcp/call")
async def call_tool(request: ToolCallRequest):
    """直接调用 MCP 工具"""
    try:
        result = await mcp_server._dispatch_tool(request.tool, request.arguments)
        return success_response(data=result)
    except Exception as e:
        logger.error(f"工具调用失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.service_port)
