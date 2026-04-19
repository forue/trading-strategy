# 前端模块设计文档

> 版本: v1.0 | 更新日期: 2026-04-18

---

## 一、模块概述

前端采用 **Vue3 + TypeScript + Vite** 单页应用架构，提供A股轮动策略交易系统的完整可视化交互界面。

### 技术栈

| 技术 | 版本 | 用途 |
|------|------|------|
| Vue3 | 3.4+ | 核心框架（Composition API） |
| TypeScript | 5.3+ | 类型安全 |
| Vite | 5.1+ | 构建工具 + HMR |
| ECharts | 5.5+ | 图表可视化 |
| vue-echarts | 6.6+ | ECharts Vue3封装 |
| Element Plus | 2.5+ | UI组件库 |
| Pinia | 2.1+ | 状态管理 |
| Vue Router | 4.3+ | 路由管理 |
| Axios | 1.6+ | HTTP客户端 |
| Day.js | 1.11+ | 日期处理 |

---

## 二、目录结构

```
frontend/src/
├── api/                    # API接口层
│   ├── request.ts          # Axios实例 + 拦截器
│   ├── auth.ts             # 认证接口
│   ├── signal.ts           # 信号接口
│   ├── strategy.ts         # 策略接口
│   └── fund.ts             # 资金接口
├── layouts/                # 布局组件
│   └── MainLayout.vue      # 主布局（侧边栏+头部+内容区）
├── router/                 # 路由配置
│   └── index.ts            # 路由定义 + 守卫
├── stores/                 # Pinia状态管理
│   ├── user.ts             # 用户状态（Token/登录登出）
│   └── signal.ts           # 信号状态（WebSocket/信号列表）
├── styles/                 # 全局样式
│   └── index.scss          # SCSS变量 + 布局 + 组件样式
├── views/                  # 页面组件
│   ├── Login.vue           # 登录/注册页
│   ├── Dashboard.vue       # 仪表盘
│   ├── Strategy.vue        # 策略管理
│   ├── Signals.vue         # 交易信号
│   ├── Fund.vue            # 资金管理
│   └── Monitor.vue         # 系统监控
├── App.vue                 # 根组件
├── main.ts                 # 入口文件
└── env.d.ts                # 类型声明
```

---

## 三、路由设计

```typescript
/login                  # 登录页（无需认证）
/                       # 主布局（需认证）
  ├── /                 # 仪表盘
  ├── /strategy         # 策略管理
  ├── /signals          # 交易信号
  ├── /fund             # 资金管理
  └── /monitor          # 系统监控
```

### 路由守卫

- `beforeEach`: 检查 `localStorage` 中的Token
- 无Token → 重定向至 `/login`
- 有Token → 放行（Token有效性由后端校验）

---

## 四、API层设计

### 4.1 Axios实例 (`request.ts`)

```
baseURL: /api
timeout: 30s

请求拦截器:
  - 从 localStorage 读取 token
  - 设置 Authorization: Bearer {token}

响应拦截器:
  - code === 200 → 返回 data 字段
  - code !== 200 → ElMessage.error 提示
  - HTTP 401 → 清除Token + 跳转登录页
```

### 4.2 接口定义

#### auth.ts

| 方法 | 路径 | 参数 | 返回 |
|------|------|------|------|
| login | POST /auth/login | {username, password} | {token, user} |
| register | POST /auth/register | {username, password, email} | {token, user} |
| getUserInfo | GET /auth/user/info | - | UserInfo |
| logout | POST /auth/logout | - | void |

#### signal.ts

| 方法 | 路径 | 参数 | 返回 |
|------|------|------|------|
| getTodaySignals | GET /signals/today | strategyType | TradeSignal[] |
| getSignalHistory | GET /signals/history | {strategyType, startDate, endDate} | TradeSignal[] |
| getSignalCalendar | GET /signals/calendar | {strategyType, month} | TradeSignal[] |

#### strategy.ts

| 方法 | 路径 | 参数 | 返回 |
|------|------|------|------|
| getConfigs | GET /strategy/configs | - | StrategyConfig[] |
| updateConfig | PUT /strategy/configs/{id} | StrategyConfig | StrategyConfig |
| runBacktest | POST /strategy/backtest | BacktestRequest | BacktestResult |

#### fund.ts

| 方法 | 路径 | 参数 | 返回 |
|------|------|------|------|
| getPositions | GET /fund/positions | strategyType? | Position[] |
| getNavCurve | GET /fund/nav-curve | {strategyType, startDate, endDate} | NavRecord[] |
| getReturnAttribution | GET /fund/attribution | {strategyType, startDate, endDate} | ReturnAttribution[] |
| getAccountSummary | GET /fund/summary | - | AccountSummary |

---

## 五、状态管理

### 5.1 userStore

```
状态:
  token: string          - JWT Token
  userInfo: UserInfo     - 用户信息
  isLoggedIn: boolean    - 登录状态

动作:
  login(params)          - 登录（调用API + 存Token）
  checkAuth()            - 检查认证（获取用户信息）
  logout()               - 登出（清除Token + 状态）
```

### 5.2 signalStore

```
状态:
  currentSignals: TradeSignal[]   - 当前未读信号
  signalHistory: TradeSignal[]    - 历史信号
  wsConnection: WebSocket         - WebSocket实例
  isConnected: boolean            - 连接状态

动作:
  fetchTodaySignals(strategyType) - 获取今日信号
  fetchSignalHistory(params)      - 获取历史信号
  connectWebSocket()              - 建立WS连接（自动重连5s）
  disconnectWebSocket()           - 断开WS连接
```

### WebSocket通信协议

```
连接: ws://{host}/ws/signals?token={jwt}

客户端→服务端:
  { type: "subscribe", strategy_type: "AGGRESSIVE" }   - 订阅策略
  { type: "unsubscribe", strategy_type: "AGGRESSIVE" } - 取消订阅
  { type: "ping" }                                      - 心跳

服务端→客户端:
  { signal_date, strategy_type, sector_name, direction, position_ratio, score, ... }  - 信号推送
  { type: "subscribed", strategy_type: "..." }     - 订阅确认
  { type: "pong", timestamp: "..." }               - 心跳回复
```

---

## 六、页面设计

### 6.1 Login.vue - 登录/注册页

```
布局: 居中卡片，深色渐变背景
Tab切换: 登录 | 注册
表单校验: 用户名必填、密码必填(注册≥6位)、邮箱格式、确认密码一致
交互: Enter提交、Loading状态、错误提示
```

### 6.2 Dashboard.vue - 仪表盘

```
顶部统计卡片 (4列):
  - 总资产 | 今日盈亏 | 累计收益率 | 活跃信号数

左侧: 板块资金流向热力图 (14列)
  - X轴: 12个主要行业板块
  - Y轴: 资金强度/资金斜率/相对强弱
  - 色阶: 蓝(流出) → 红(流入)
  - 切换: 5日/10日/20日周期

右侧: 今日策略信号 (10列)
  - 策略类型下拉选择
  - 信号列表: 板块名 + 买入/卖出标签 + 评分 + 仓位

底部: 策略信号日历
  - ECharts Calendar热力图
  - 月份选择器
  - 颜色深浅表示信号数量
```

### 6.3 Strategy.vue - 策略管理

```
三栏卡片 (各8列):
  激进轮动 | 稳健轮动 | 保守轮动
  
  每个卡片:
    - 图标 + 名称 + 风险标签
    - 策略描述
    - 参数配置表单:
        选取前N名、最大仓位(滑块)、持有天数、止损比例
        保守额外: 估值分位上限
    - 保存配置按钮

回测区域:
  筛选条件: 策略类型 + 日期范围 + 初始资金
  结果展示: 总收益率/年化/最大回撤/夏普比率
  净值曲线: 策略净值 vs 基准净值
```

### 6.4 Signals.vue - 交易信号

```
筛选栏:
  策略类型 | 信号方向 | 日期范围 | 查询按钮

实时推送状态:
  连接状态指示灯 + 连接/断开按钮

信号列表 (表格):
  信号日期 | 策略类型(标签) | 板块 | 方向(红买绿卖) |
  建议仓位 | 评分(进度条) | 信号原因 | 生成时间

分页: 20/50/100条/页
```

### 6.5 Fund.vue - 资金管理

```
账户概览 (4列):
  总资产 | 可用资金 | 持仓市值 | 累计收益率

净值曲线 (16列):
  双Y轴: 净值 + 收益率%
  策略选择 + 日期范围筛选
  面积图: 账户净值
  虚线: 累计收益率

收益归因 (8列):
  饼图: 各板块盈亏贡献占比

当前持仓 (表格):
  板块 | 策略 | 方向 | 数量 | 均价 | 现价 |
  盈亏%(红涨绿跌) | 仓位占比 | 开仓时间
```

### 6.6 Monitor.vue - 系统监控

```
左: Docker服务状态 (12列)
  表格: 服务名 | 状态(徽章) | CPU | 内存 | 运行时间 | 端口

右: 服务健康检查 (12列)
  网格: 每个服务一个卡片
  图标 + 名称 + 详情
  左边框颜色: 绿=健康/黄=警告/红=异常

底部: 系统日志
  深色终端风格
  服务筛选下拉框
  颜色: INFO=白/WARN=黄/ERROR=红/DEBUG=灰
```

---

## 七、样式规范

### CSS变量

```scss
$primary-color: #409eff;     // 主色
$success-color: #67c23a;     // 成功/买入
$warning-color: #e6a23c;     // 警告
$danger-color: #f56c6c;      // 危险/卖出
$bg-color: #f0f2f5;          // 页面背景
$sidebar-width: 220px;       // 侧边栏宽度
```

### 信号方向颜色约定

- **买入 (BUY)**: 红色 `#f56c6c` （A股红色为涨）
- **卖出 (SELL)**: 绿色 `#67c23a` （A股绿色为跌）

### 响应式断点

```
≤768px: 侧边栏收缩为64px图标模式
```
