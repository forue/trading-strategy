# 未完成功能实现指导文档

> 版本: v1.1 | 更新日期: 2026-09-21 | 更新: 第 1 项「北向资金采集」已实现后下线（数据源停止披露），本节转为状态说明
>
> 历史版本: v1.0 (2026-05-03)

---

## 概述

本文档记录 3 个功能模块的实现方案与最终状态，按优先级排序。第 1 项已实现后下线（保留作历史记录），第 3 项已完成，仅第 2 项仍待接入。

| 序号 | 功能 | 涉及服务 | 优先级 | 状态 |
|------|------|----------|--------|------|
| 1 | 北向资金采集 | data-collector | 高 | 已实现后下线（见第 1 节） |
| 2 | 风险监控集成 | ai-decision | 高 | 已实现未接入 |
| 3 | 每日复盘数据完善 | ai-decision | 中 | 已实现 |

---

## 1. 北向资金采集（已实现后下线）

> **状态（2026-09-21）**：本项已完成实现，后因数据源停止披露而下线，无需再开发。
> `collect_north_bound_flow()` 现调用 AkShare `stock_hsgt_fund_flow_summary_em()`
> （沪股通 + 深股通北向净买额之和），写入 InfluxDB `north_bound_flow` measurement，
> 端点 `POST /collect/north-bound` 保留。
> 沪深港通自 2024-08-19 起停止披露该口径，采集结果恒为 0，故采集任务已于 2026-09-21
> 从调度器移除（见 `docs/08-scheduler.md` 3.6、`docs/04-data-collector.md` 4.4）。
>
> **以下"实现方案"为最初的需求草案，与最终代码不完全一致（最终实现走
> `stock_hsgt_fund_flow_summary_em()` 而非草案中的 `stock_hsgt_north_net_flow_in_em()`），仅作历史参考。**

### 现状（草案撰写时）

`services/data-collector/app/collector.py` 中 `collect_north_bound_flow()` 当时返回空列表：

```python
def collect_north_bound_flow(self) -> list[dict]:
    """采集北向资金数据（同花顺无对应接口，返回空列表）"""
    today = datetime.now().strftime("%Y%m%d")
    if not self.is_trade_day(today):
        logger.info(f"{today} 非交易日，跳过北向资金采集")
        return []
    logger.info("北向资金数据暂无数据源")
    return []
```

### 实现方案

使用 AkShare 的 `stock_hsgt_north_net_flow_in_em()` 接口获取北向资金净流入数据。

### 数据结构

```python
{
    "date": "2026-05-02",           # 日期
    "north_net_inflow": 1500000000, # 北向净流入（元）
    "north_buy": 8000000000,        # 北向买入（元）
    "north_sell": 6500000000,       # 北向卖出（元）
    "sh_connect": 800000000,        # 沪股通净流入
    "sz_connect": 700000000,        # 深股通净流入
}
```

### 实现步骤

1. 在 `collector.py` 中实现 `collect_north_bound_flow()` 方法
2. 调用 `akshare.stock_hsgt_north_net_flow_in_em()` 获取数据
3. 解析返回的 DataFrame，提取每日净流入
4. 写入 InfluxDB（measurement: `north_bound_flow`）
5. 在 `main.py` 的 `/collect/north-bound` 端点中调用

### 关键代码

```python
def collect_north_bound_flow(self) -> list[dict]:
    """采集北向资金数据"""
    import akshare as ak
    
    today = datetime.now().strftime("%Y%m%d")
    if not self.is_trade_day(today):
        logger.info(f"{today} 非交易日，跳过北向资金采集")
        return []
    
    try:
        # 获取北向资金净流入
        df = ak.stock_hsgt_north_net_flow_in_em()
        if df is None or df.empty:
            logger.warning("北向资金数据为空")
            return []
        
        results = []
        for _, row in df.iterrows():
            date_str = str(row.get("date", ""))
            if not date_str:
                continue
            results.append({
                "date": date_str,
                "north_net_inflow": float(row.get("value", 0)) * 1e4,  # 万元转元
            })
        
        # 写入 InfluxDB
        if results:
            self._write_north_bound_to_influx(results)
            logger.info(f"北向资金采集完成: {len(results)} 条")
        
        return results
    except Exception as e:
        logger.error(f"北向资金采集失败: {e}")
        return []
```

### InfluxDB 写入

在 `influx_client.py` 中新增：

```python
def write_north_bound_flow(self, data: list[dict]):
    """写入北向资金数据"""
    points = []
    for item in data:
        date_str = item.get("date", "")
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            dt = datetime.now()
        
        point = (
            Point("north_bound_flow")
            .field("north_net_inflow", float(item.get("north_net_inflow", 0)))
            .time(dt, WritePrecision.MS)
        )
        points.append(point)
    
    if points:
        self.write_api.write(bucket=self.bucket, org=self.org, record=points)
        logger.info(f"写入北向资金数据 {len(points)} 条")
```

---

## 2. 风险监控集成

### 现状

`services/ai-decision/app/risk_monitor.py` 中 `RiskMonitor` 类已完整实现，包含：
- 仓位集中度检查
- 当日亏损检查
- 回撤检查
- 市场风险检查

但未被任何 API 端点或 Agent 工具调用。

### 实现方案

1. 在 `main.py` 中添加 `/api/ai/risk-monitor` API 端点
2. 在 `tools.py` 中添加 `check_portfolio_risk` 工具供 Agent 调用
3. 在 Agent 系统提示词中说明风险监控能力

### API 端点

```python
@app.post("/api/ai/risk-monitor")
async def check_risk(request: RiskCheckRequest):
    """检查投资组合风险"""
    try:
        from .risk_monitor import RiskMonitor, PortfolioState
        
        monitor = RiskMonitor()
        state = PortfolioState(
            positions=request.positions,
            total_assets=request.total_assets,
            daily_pnl=request.daily_pnl,
            cum_return=request.cum_return,
            max_drawdown=request.max_drawdown,
            market_change=request.market_change,
            market_sentiment=request.market_sentiment,
        )
        
        alerts = monitor.check_portfolio(state)
        return success_response(data={
            "alerts": [a.model_dump() for a in alerts],
            "alert_count": len(alerts),
            "has_critical": any(a.level == "CRITICAL" for a in alerts),
        })
    except Exception as e:
        logger.error(f"风险检查失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
```

### Agent 工具

在 `tools.py` 中新增：

```python
{
    "type": "function",
    "function": {
        "name": "check_portfolio_risk",
        "description": "检查投资组合风险：仓位集中度、亏损、回撤、市场风险",
        "parameters": {
            "type": "object",
            "properties": {
                "positions": {
                    "type": "object",
                    "description": "持仓权重 {sector_code: weight}"
                },
                "total_assets": {
                    "type": "number",
                    "description": "总资产"
                },
                "daily_pnl": {
                    "type": "number",
                    "description": "当日盈亏"
                },
                "max_drawdown": {
                    "type": "number",
                    "description": "最大回撤"
                },
                "market_change": {
                    "type": "number",
                    "description": "大盘涨跌幅"
                }
            },
            "required": ["positions"]
        }
    }
}
```

### 工具执行器

在 `MCPToolExecutor` 中新增：

```python
async def _check_portfolio_risk(self, args: dict) -> dict:
    """检查投资组合风险"""
    from .risk_monitor import RiskMonitor, PortfolioState
    
    monitor = RiskMonitor()
    state = PortfolioState(
        positions=args.get("positions", {}),
        total_assets=args.get("total_assets", 0),
        daily_pnl=args.get("daily_pnl", 0),
        max_drawdown=args.get("max_drawdown", 0),
        market_change=args.get("market_change", 0),
    )
    
    alerts = monitor.check_portfolio(state)
    return {
        "alerts": [
            {
                "type": a.alert_type,
                "level": a.level.value,
                "title": a.title,
                "description": a.description,
                "suggestion": a.suggestion,
            }
            for a in alerts
        ],
        "alert_count": len(alerts),
        "has_critical": any(a.level == "CRITICAL" for a in alerts),
    }
```

---

## 3. 每日复盘数据完善（已实现）

### 修复前的问题

`services/ai-decision/app/daily_reviewer.py` 的 `DailyReviewDataCollector` 存在三处缺陷：

1. 构造时只传入 `redis_mgr.client`（ai-decision 的 Redis 为 DB3），信号/持仓实际存储于
   signal/strategy 服务的 DB1，导致始终读不到；
2. `influx_client` 从未传入，`_query_market_data` 形同虚设；
3. 即便传入，`_query_market_data` 也只统计板块，未填充 `sh_index` / `sz_index` / `cy_index` 等指数字段。

### 实现方案

改为统一通过各微服务 HTTP 接口取数，数据源与 `MCPToolExecutor` 保持一致，
不再跨服务直连 Redis/InfluxDB：

| 数据 | 来源 |
|------|------|
| 大盘指数（上证/深证/创业板） | `external_data.get_market_indices()`（外部实时行情） |
| 板块表现与成交额 | data-collector `GET /query/all-sectors?start_date=&end_date=` |
| 信号 | signal-notification `GET /signals/history?strategy_type=&start_date=&end_date=` |
| 持仓 | strategy `GET /positions?strategy_type=`（本次新增接口） |

关键约定：

- 任一数据源失败只降级为占位文案（`暂无数据` / `今日无信号` / `暂无持仓`），不影响报告生成；
- 板块 `turnover` 求和后换算为亿元写入 `total_turnover`；
- 顺带用板块列表构建「板块代码 → 名称」映射，持仓按名称展示；
- 指数为实时行情，仅在复盘日期为当日时填充；历史日期缺少可用的指数源，故留空并记日志。

### 附带修复

`MCPToolExecutor.get_current_positions` 此前请求 `{strategy_url}/positions`，但该接口并不存在（404），
工具实际不可用。本次在 strategy 服务补齐 `GET /positions`，工具与复盘同时恢复。

---

## 实现顺序

1. ~~北向资金采集 → 数据层完善~~（已实现，后因数据源停止披露而下线）
2. **风险监控集成** → API + Agent 工具
3. ~~每日复盘数据完善 → 数据收集完善~~（已完成）

每个功能实现后需要：
- 编写单元测试
- 更新 API 文档
- 在前端页面中集成展示
