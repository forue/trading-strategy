# 信号通知服务设计文档

> 版本: v1.1 | 更新日期: 2026-04-19 | 更新内容: 优化消息模板，添加配置持久化

---

## 一、模块概述

信号通知服务负责将策略引擎生成的买卖信号实时推送给前端用户。支持WebSocket长连接推送和REST接口查询两种方式，同时作为RabbitMQ消费者监听策略计算事件。新增外部推送通道（钉钉、企业微信）支持，提供专业的消息模板和配置持久化功能。

| 属性 | 值 |
|------|-----|
| 服务名 | backend-signal |
| 端口 | 8004 |
| 语言 | Python 3.11 |
| 框架 | FastAPI |
| 通信 | WebSocket + RabbitMQ + Redis + 外部推送API |

---

## 二、技术架构

```
┌──────────────────────────────────────────────────────────┐
│                  信号通知服务 (:8004)                      │
│                                                          │
│  ┌────────────────┐    ┌────────────────────┐            │
│  │  WebSocket端点  │    │  REST API端点       │            │
│  │  /ws/signals   │    │  GET /signals/today │            │
│  │                │    │  GET /signals/history│            │
│  └───────┬────────┘    └────────┬───────────┘            │
│          │                      │                        │
│  ┌───────▼──────────────────────▼───┐                    │
│  │        ConnectionManager         │                    │
│  │  (WebSocket连接管理 + 广播)       │                    │
│  └──────────────────────────────────┘                    │
│          ▲                                               │
│          │ 信号推送                                       │
│  ┌───────┴──────────────────────────┐                    │
│  │      RabbitMQ Consumer           │                    │
│  │  (监听 signal.# 事件)            │                    │
│  │  ┌─────────────────────────┐     │                    │
│  │  │ signal.generated 事件   │     │                    │
│  │  │ → 解析信号列表           │     │                    │
│  │  │ → WebSocket广播推送     │     │                    │
│  │  │ → Redis缓存写入         │     │                    │
│  │  └─────────────────────────┘     │                    │
│  └──────────────────────────────────┘                    │
└──────────────────────────────────────────────────────────┘
         │               │               │
         ▼               ▼               ▼
    ┌─────────┐   ┌──────────┐   ┌──────────┐
    │WebSocket │   │ RabbitMQ │   │  Redis   │
    │  客户端  │   │  :5672   │   │  :6379   │
    └─────────┘   └──────────┘   └──────────┘
```

---

## 三、WebSocket通信设计

### 3.1 连接建立

```
URL: ws://{host}/ws/signals?token={jwt_token}

流程:
  1. 前端发起WebSocket连接，携带Token参数
  2. 服务端接受连接，分配user_id（基于Token或匿名ID）
  3. 连接建立后，默认接收所有策略信号
  4. 可通过subscribe/unsubscribe消息订阅特定策略
```

### 3.2 消息协议

#### 客户端 → 服务端

```json
// 订阅策略信号
{ "type": "subscribe", "strategy_type": "AGGRESSIVE" }

// 取消订阅
{ "type": "unsubscribe", "strategy_type": "AGGRESSIVE" }

// 心跳
{ "type": "ping" }
```

#### 服务端 → 客户端

```json
// 信号推送
{
  "signal_date": "2026-04-18",
  "strategy_type": "AGGRESSIVE",
  "sector_code": "SW801780",
  "sector_name": "银行",
  "direction": "BUY",
  "position_ratio": 0.5,
  "score": 8.23,
  "reason": "激进轮动: 资金强度排名#1..."
}

// 订阅确认
{ "type": "subscribed", "strategy_type": "AGGRESSIVE" }

// 取消订阅确认
{ "type": "unsubscribed", "strategy_type": "AGGRESSIVE" }

// 心跳回复
{ "type": "pong", "timestamp": "2026-04-18T15:05:21" }
```

### 3.3 连接管理

```python
class ConnectionManager:
    active_connections: Dict[str, WebSocket]      # user_id → WebSocket
    user_subscriptions: Dict[str, Set[str]]       # user_id → {strategy_types}

    async def connect(websocket, user_id)          # 接受连接
    def disconnect(user_id)                        # 断开连接
    async def send_personal_message(msg, user_id)  # 发送个人消息
    async def broadcast_signal(signal, strategy)    # 广播信号给订阅用户
    def subscribe(user_id, strategy_type)           # 订阅策略
    def unsubscribe(user_id, strategy_type)         # 取消订阅
```

### 3.4 断线重连

```
客户端断线处理:
  1. 检测到ws.onclose事件
  2. 等待5秒
  3. 重新建立WebSocket连接
  4. 重新发送subscribe消息恢复订阅
  5. 调用REST接口获取断线期间的信号（信号历史查询）
```

---

## 四、RabbitMQ消费者

### 4.1 消费配置

```
Exchange: rotation (topic, durable)
Queue: signal_notification (durable)
Routing Key: signal.#   (匹配 signal.generated 等)
```

### 4.2 消息处理流程

```python
def callback(ch, method, properties, body):
    message = json.loads(body)
    event = message.get("event")

    if event == "signals_generated":
        signals = message["signals"]
        strategy_type = message["strategy_type"]
        signal_date = message.get("signal_date", datetime.now().strftime("%Y-%m-%d"))

        # 1. 通过WebSocket广播信号（在主事件循环上执行）
        for signal in signals:
            asyncio.run_coroutine_threadsafe(
                ws_manager.broadcast_signal(signal, strategy_type), _main_loop
            )

        # 2. 外部推送通道（钉钉、企业微信）
        asyncio.run_coroutine_threadsafe(
            notify_manager.push_signal(signals, strategy_type, signal_date), _main_loop
        )

        # 3. 缓存信号到Redis
        redis_mgr.setex(
            f"signals:{strategy_type}:{signal_date}",
            86400 * 7,  # 7天过期
            json.dumps(signals)
        )
```

### 4.3 后台线程

```python
# 在FastAPI启动时，后台线程运行RabbitMQ消费者
mq_thread = threading.Thread(target=start_rabbitmq_consumer, daemon=True)
mq_thread.start()
```

使用daemon线程确保FastAPI退出时消费者线程自动终止。

---

## 五、REST接口设计

### 5.1 获取今日信号

```
GET /signals/today?strategy_type=AGGRESSIVE

响应:
{
  "code": 200,
  "data": [
    {
      "signal_date": "2026-04-18",
      "strategy_type": "AGGRESSIVE",
      "sector_name": "银行",
      "direction": "BUY",
      "position_ratio": 0.5,
      "score": 8.23,
      "reason": "..."
    }
  ]
}
```

### 5.2 获取历史信号

```
GET /signals/history?strategy_type=MODERATE&start_date=2026-04-01&end_date=2026-04-18

逻辑:
  1. 遍历日期范围
  2. 从Redis读取每日信号 (signals:{type}:{date})
  3. 汇总返回
```

### 5.3 获取信号日历

```
GET /signals/calendar?strategy_type=AGGRESSIVE&month=2026-04

逻辑:
  1. 计算月份起止日期
  2. 调用历史信号查询
  3. 返回当月所有信号
```

### 5.4 推送通道配置

```
GET /signals/notify/config
  - 获取推送通道配置（webhook URL会脱敏显示）

PUT /signals/notify/config
Content-Type: application/json
  - 更新推送通道配置（钉钉/企业微信）
  - 配置持久化到Redis (key: notify_channels_config)

POST /signals/notify/test/{channel}?strategy_type=MODERATE
  - 测试推送通道（channel: dingtalk/wecom）
  - 发送测试消息验证配置是否正确
```

### 5.5 健康检查

```
GET /health

响应:
{
  "status": "healthy",
  "service": "signal-notification",
  "ws_connections": 3,
  "notify_channels": {
    "dingtalk": true,
    "wecom": false
  },
  "timestamp": "2026-04-18T15:00:21"
}
```

---

## 六、Redis缓存策略

### 6.1 Key设计

```
signals:{strategy_type}:{date}   - 每日信号缓存
  TTL: 7天 (604800秒)
  Value: JSON数组

示例:
  signals:AGGRESSIVE:2026-04-18 → [{"sector_name":"银行","direction":"BUY",...}, ...]
```

### 6.2 缓存更新时机

| 事件 | 操作 |
|------|------|
| 策略计算完成 (signal.generated) | 写入当日信号缓存 |
| 查询信号时缓存不存在 | 返回空数组（不主动计算） |
| TTL过期 | 自动清理7天前信号 |

---

## 七、前端通知机制

### 7.1 WebSocket连接管理（前端）

```typescript
// signalStore.ts
function connectWebSocket() {
    const wsUrl = `ws://${host}/ws/signals?token=${token}`
    const ws = new WebSocket(wsUrl)

    ws.onopen = () → isConnected = true
    ws.onmessage = (event) → {
        const signal = JSON.parse(event.data)
        // 1. 添加到当前信号列表
        currentSignals.unshift(signal)
        // 2. 播放提示音
        new Audio('/notification.mp3').play()
        // 3. 浏览器通知
        new Notification('轮动信号推送', { body: ... })
    }
    ws.onclose = () → setTimeout(() → connectWebSocket(), 5000)  // 5秒重连
}
```

### 7.2 通知权限

```
首次连接时请求浏览器通知权限:
  Notification.requestPermission()

权限状态:
  granted  → 显示通知
  denied   → 仅页面内提示
  default  → 请求权限
```

---

## 八、外部推送通道设计

### 8.1 多渠道推送

系统已实现多种推送通道，满足不同场景需求：

| 渠道 | 状态 | 实现方式 | 场景 |
|------|------|----------|------|
| WebSocket | ✅ 已实现 | 长连接实时推送 | 网页实时推送 |
| 钉钉机器人 | ✅ 已实现 | Webhook + Markdown | 团队协作通知 |
| 企业微信机器人 | ✅ 已实现 | Webhook + Markdown | 团队协作通知 |
| Redis缓存 | ✅ 已实现 | 键值存储 | 信号历史查询 |
| 邮件 | 🔄 规划中 | SMTP + 模板 | 非在线用户每日汇总 |
| 短信 | 🔄 规划中 | 阿里云SMS | 重要信号（如止损触发） |

### 8.2 钉钉/企业微信消息模板

#### 8.2.1 策略类型中文映射
- `AGGRESSIVE` → `⚡激进策略`
- `MODERATE` → `⚖️稳健策略`
- `CONSERVATIVE` → `🛡️保守策略`

#### 8.2.2 消息结构
```
📊板块轮动信号 - ⚖️稳健策略
📅 信号日期: 2025-04-19
🎯 策略类型: ⚖️稳健策略

🟢 买入信号:
  1. 科技 (515000 科技ETF)
    📊 综合评分: 8.5/10
    📈 建议仓位: 30.0%
    💡 信号理由: 动量排名第1，RSI指标超卖反弹...

🔴 卖出信号:
  1. 金融 (512800 金融ETF)
    📊 综合评分: 4.1/10
    ⚠️ 卖出理由: 技术面破位，MACD死叉...

📋 信号统计
- 买入信号: 2 个
- 卖出信号: 1 个
- 总计: 3 个信号

⚠️ 风险提示
1. 本信号基于量化模型生成，仅供参考
2. 投资有风险，决策需谨慎
3. 建议结合自身风险承受能力调整仓位

⏰ 生成时间: 2025-04-19 13:30:45
```

### 8.3 配置持久化机制

#### 8.3.1 配置存储
- 推送通道配置存储在Redis中（key: `notify_channels_config`）
- 支持部分更新，合并新旧配置
- 服务启动时自动从Redis加载配置

#### 8.3.2 配置API
```http
# 获取当前配置
GET /signals/notify/config

# 更新配置
PUT /signals/notify/config
Content-Type: application/json

{
  "dingtalk": {
    "enabled": true,
    "webhook_url": "https://oapi.dingtalk.com/robot/send?access_token=xxx",
    "secret": "SEC..."
  },
  "wecom": {
    "enabled": true,
    "webhook_url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx"
  }
}

# 测试推送通道
POST /signals/notify/test/{channel}
?strategy_type=MODERATE
```

#### 8.3.3 配置恢复流程
1. 用户在前端设置页面配置钉钉/企业微信webhook
2. 配置通过API保存到Redis
3. 服务重启时自动从Redis加载配置
4. 后续服务重建不会丢失配置（除非Redis被清空）

### 8.2 推送策略

```
信号优先级:
  HIGH   → 止损触发、大额信号 → 多渠道推送
  MEDIUM → 常规买卖信号 → WebSocket + 邮件
  LOW    → 策略微调 → 仅WebSocket

频率控制:
  同一板块24小时内只推送1次
  同一策略每日最多推送5条
```
