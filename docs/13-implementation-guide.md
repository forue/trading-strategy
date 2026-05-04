# 未完成功能实现指导文档

> 版本: v1.0 | 更新日期: 2026-05-03

---

## 概述

本文档描述系统中尚未完成的 3 个功能模块的实现方案，按优先级排序。

| 序号 | 功能 | 涉及服务 | 优先级 | 状态 |
|------|------|----------|--------|------|
| 1 | 北向资金采集 | data-collector | 高 | 桩实现 |
| 2 | 风险监控集成 | ai-decision | 高 | 已实现未接入 |
| 3 | 每日复盘数据完善 | ai-decision | 中 | 部分实现 |

---

## 1. 北向资金采集

### 现状

`services/data-collector/app/collector.py:410-419` 中 `collect_north_bound_flow()` 返回空列表：

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

## 3. 每日复盘数据完善

### 现状

`services/ai-decision/app/daily_reviewer.py:121-159` 中 `DailyReviewDataCollector.collect()` 只从 Redis 读取信号和持仓，不从 InfluxDB 读取市场数据（`self.influx` 参数传入但从未使用）。

### 实现方案

1. 从 InfluxDB 读取当日市场数据（大盘指数、板块表现）
2. 计算板块涨跌排行
3. 填充 `MarketData` 对象的 `sh_index`、`sh_change` 等字段

### 实现步骤

```python
async def collect(self, date: str) -> MarketData:
    """收集复盘所需数据"""
    data = MarketData(date=date)
    
    # 1. 从 InfluxDB 读取市场数据
    if self.influx:
        try:
            market_data = self._query_market_data(date)
            data.sh_index = market_data.get("sh_index", 0)
            data.sh_change = market_data.get("sh_change", 0)
            data.sz_index = market_data.get("sz_index", 0)
            data.sz_change = market_data.get("sz_change", 0)
            data.total_turnover = market_data.get("total_turnover", 0)
            data.sector_performance = market_data.get("sector_performance", "")
        except Exception as e:
            logger.warning(f"从 InfluxDB 读取市场数据失败: {e}")
    
    # 2. 从 Redis 读取信号（已有逻辑）
    signals_text = []
    for st in ["AGGRESSIVE", "MODERATE", "CONSERVATIVE"]:
        raw = self.redis.get(f"signals:{st}:{date}")
        if raw:
            import json
            signals = json.loads(raw)
            if signals:
                signals_text.append(f"{st} 策略: {len(signals)} 条信号")
                for s in signals[:3]:
                    direction = "买入" if s.get("direction") == "BUY" else "卖出"
                    signals_text.append(f"  - {s.get('sector_name')} {direction} 评分{s.get('score', 0):.1f}")
    
    data.signals_text = "\n".join(signals_text) if signals_text else "今日无信号"
    
    # 3. 从 Redis 读取持仓（已有逻辑）
    portfolio_lines = []
    for st in ["AGGRESSIVE", "MODERATE", "CONSERVATIVE"]:
        raw = self.redis.get(f"positions:{st}")
        if raw:
            import json
            positions = json.loads(raw)
            if positions:
                portfolio_lines.append(f"{st} 策略持仓:")
                for code, weight in positions.items():
                    portfolio_lines.append(f"  - {code}: {weight*100:.1f}%")
    
    data.portfolio_text = "\n".join(portfolio_lines) if portfolio_lines else "暂无持仓"
    
    return data


def _query_market_data(self, date: str) -> dict:
    """从 InfluxDB 查询当日市场数据"""
    query = f'''
    from(bucket: "{self.influx.bucket}")
      |> range(start: {date}T00:00:00Z, stop: {date}T23:59:59Z)
      |> filter(fn: (r) => r._measurement == "sector_capital_flow")
      |> pivot(rowKey: ["_time", "sector_code"], columnKey: ["_field"], valueColumn: "_value")
    '''
    try:
        tables = self.influx.query_api.query_data_frame(query)
        if isinstance(tables, list) and len(tables) == 0:
            return {}
        if hasattr(tables, "empty") and tables.empty:
            return {}
        
        records = tables.to_dict("records")
        if not records:
            return {}
        
        # 计算汇总数据
        total_turnover = sum(r.get("turnover", 0) for r in records)
        up_count = sum(1 for r in records if r.get("index_change_pct", 0) > 0)
        down_count = sum(1 for r in records if r.get("index_change_pct", 0) < 0)
        avg_change = sum(r.get("index_change_pct", 0) for r in records) / max(len(records), 1)
        
        # 板块涨跌排行
        sorted_sectors = sorted(records, key=lambda x: x.get("index_change_pct", 0), reverse=True)
        top5 = sorted_sectors[:5]
        bottom5 = sorted_sectors[-5:]
        
        sector_lines = ["涨幅前5:"]
        for s in top5:
            sector_lines.append(f"  {s.get('sector_name')}: {s.get('index_change_pct', 0):+.2f}%")
        sector_lines.append("跌幅前5:")
        for s in bottom5:
            sector_lines.append(f"  {s.get('sector_name')}: {s.get('index_change_pct', 0):+.2f}%")
        
        return {
            "total_turnover": total_turnover,
            "up_count": up_count,
            "down_count": down_count,
            "avg_change": avg_change,
            "sector_performance": "\n".join(sector_lines),
        }
    except Exception as e:
        logger.error(f"查询市场数据失败: {e}")
        return {}
```

---

## 实现顺序

1. **北向资金采集** → 数据层完善
2. **风险监控集成** → API + Agent 工具
3. **每日复盘数据完善** → 数据收集完善

每个功能实现后需要：
- 编写单元测试
- 更新 API 文档
- 在前端页面中集成展示
