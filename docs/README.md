# A股轮动策略交易系统 - 设计文档索引

> 版本: v1.2 | 更新日期: 2026-05-05

---

## 文档列表

| 序号 | 文档 | 说明 |
|------|------|------|
| 01 | [总览设计文档](01-overview.md) | 项目背景、架构设计、技术选型、数据库设计、安全设计、部署架构 |
| 02 | [前端模块设计文档](02-frontend.md) | Vue3项目结构、路由设计、API层、状态管理、页面设计、样式规范 |
| 03 | [认证中心设计文档](03-auth-service.md) | JWT认证、用户管理、Token安全机制、Spring Security配置 |
| 04 | [数据采集服务设计文档](04-data-collector.md) | AkShare数据源、InfluxDB时序存储、板块资金流模型、容错降级 |
| 05 | [策略引擎设计文档](05-strategy-engine.md) | 多因子+截面混合评分、三档轮动、调仓参数、信号与回测流程 |
| 06 | [信号通知服务设计文档](06-signal-notification.md) | WebSocket通信协议、RabbitMQ消费、连接管理、多渠道推送扩展 |
| 07 | [资金管理服务设计文档](07-fund-management.md) | 持仓管理、净值计算、收益归因、交易成本模型、实盘对接扩展 |
| 08 | [任务调度中心设计文档](08-scheduler.md) | APScheduler配置、Cron任务、执行流程、手动触发、盘中模式扩展 |
| 09 | [AI 决策服务设计文档](09-ai-decision.md) | LLM适配器、ReAct Agent、MCP工具调用、流式输出、提供商管理 |
| 10 | [因子引擎设计文档](10-factor-engine.md) | FactorRegistry、置信度加权合成、截面上下文、API 与 `DEFAULT_WEIGHTS` |
| 11 | [因子算法参考](11-factor-algorithms.md) | RSI/MACD/布林带/KDJ/动量/情绪/估值/轮动（含持续性截面定义） |
| 12 | [MCP Agent 设计文档](12-mcp-agent.md) | MCP协议、SSE传输、金融Agent、工具定义与注册 |

---

## 阅读建议

### 快速了解系统
→ 先读 [01-总览设计文档](01-overview.md)

### 前端开发
→ 读 [02-前端模块设计文档](02-frontend.md)

### 后端服务开发
- 认证相关 → [03-认证中心设计文档](03-auth-service.md)
- 策略算法 → [05-策略引擎设计文档](05-strategy-engine.md) ⭐ 核心
- 数据采集 → [04-数据采集服务设计文档](04-data-collector.md)
- 信号推送 → [06-信号通知服务设计文档](06-signal-notification.md)
- 资金管理 → [07-资金管理服务设计文档](07-fund-management.md)
- 定时任务 → [08-任务调度中心设计文档](08-scheduler.md)
- AI 决策 → [09-AI 决策服务设计文档](09-ai-decision.md) ⭐ 新增
- 因子分析 → [10-因子引擎设计文档](10-factor-engine.md) + [11-因子算法参考](11-factor-algorithms.md)
- MCP Agent → [12-MCP Agent 设计文档](12-mcp-agent.md)
