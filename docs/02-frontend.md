# 前端规范文档

> 版本: v3.1 | 更新日期: 2026-11-21 | 更新: 按 v6 视觉规范调整为 Icon Rail + Light Surface（轻量卡片边界），保留图标轨/底部标签栏/AI 双形态，恢复卡片白底+1px 边框与标题主色标识
>
> 历史版本: v3.0 按 v5 重构为无边框方案（真实界面反馈边界不清、主次不明，已弃用） | v2.2 侧边栏图标注册约定 | v2.1 新增策略复盘页 | v2.0 (2026-05-13)

---

## 一、模块概述

前端采用 **Vue 3 + TypeScript + Vite** 单页应用架构，提供A股轮动策略交易系统的完整可视化交互界面。

### 技术栈

| 技术 | 版本 | 用途 |
|------|------|------|
| Vue 3 | 3.4+ | 核心框架（Composition API） |
| TypeScript | 5.3+ | 类型安全 |
| Vite | 5.1+ | 构建工具 + HMR |
| ECharts | 5.5+ | 图表可视化 |
| vue-echarts | 6.6+ | ECharts Vue3 封装 |
| Element Plus | 2.5+ | UI 组件库 |
| Pinia | 2.1+ | 状态管理 |
| Vue Router | 4.3+ | 路由管理 |
| Axios | 1.6+ | HTTP 客户端 |
| Day.js | 1.11+ | 日期处理 |

---

## 二、目录结构

```
frontend/src/
├── api/                    # API 接口层
│   ├── request.ts          # Axios 实例 + 拦截器
│   ├── auth.ts             # 认证接口
│   ├── signal.ts           # 信号接口
│   ├── strategy.ts         # 策略接口
│   └── fund.ts             # 资金接口
├── components/             # 公共组件
│   ├── AiAnalysisPanel.vue
│   ├── AiSettings.vue
│   ├── ChatAssistant.vue
│   └── RiskAlertPanel.vue
├── composables/            # 组合式函数
│   └── useBreakpoint.ts    # 响应式断点检测
├── layouts/                # 布局组件
│   └── MainLayout.vue      # 主布局（桌面图标轨 + 上下文行 + 内容区 + 移动底部标签栏 + AI 浮层 + 回测悬浮卡）
├── components/
│   └── ReplayTaskCard.vue  # 回测任务悬浮卡（挂在布局层，切页面不销毁）
├── router/                 # 路由配置
│   └── index.ts            # 路由定义 + 守卫
├── stores/                 # Pinia 状态管理
│   ├── user.ts             # 用户状态（Token / 登录登出）
│   ├── signal.ts           # 信号状态（WebSocket / 信号列表）
│   ├── strategy.ts         # 策略状态（当前策略档位，跨页面共享）
│   ├── ai.ts               # AI 助手状态
│   ├── replayTask.ts       # 回测任务状态（供悬浮卡跨页面显示进度 / 结果）
│   └── theme.ts            # 主题状态（亮色 / 暗色切换）
├── styles/                 # 全局样式
│   └── index.scss          # 设计 Token + 布局 + 组件样式 + 响应式规则
├── views/                  # 页面组件 (11个)
│   ├── Login.vue           # 登录 / 注册
│   ├── Dashboard.vue       # 仪表盘
│   ├── Strategy.vue        # 策略管理 + 回测
│   ├── Signals.vue         # 交易信号
│   ├── Review.vue          # 策略复盘（命中率 / 净毛收益 / 板块明细 / 累计曲线）
│   ├── Fund.vue            # 资金管理
│   ├── Monitor.vue         # 系统监控
│   ├── DataReplay.vue      # 数据回放
│   ├── FactorAnalysis.vue  # 板块因子分析
│   ├── FactorRanking.vue   # 板块因子排名
│   └── Settings.vue        # 系统设置
├── App.vue                 # 根组件
├── main.ts                 # 入口文件
└── env.d.ts                # 类型声明
```

---

## 三、路由设计

```
/login                  # 登录页（无需认证）
/                       # 主布局（需认证）
  ├── /                 # 仪表盘 (Dashboard)
  ├── /strategy         # 策略管理 (Strategy)：系统三档策略参数与回测
  ├── /strategy-workshop # 策略工坊 (StrategyWorkshop)：个人策略 CRUD/版本/分享/应用，详见 05 文档第九章
  ├── /signals          # 交易信号 (Signals)
  ├── /review           # 策略复盘 (Review)
  ├── /fund             # 资金管理 (Fund)
  ├── /monitor          # 系统监控 (Monitor，仅管理员)
  ├── /data-replay      # 数据回放 (DataReplay)
  ├── /stock-sense      # 盘感训练 (StockSense)
  ├── /factor-analysis  # 板块因子分析 (FactorAnalysis)
  ├── /factor-ranking   # 板块因子排名 (FactorRanking)
  ├── /settings         # 设置 (Settings)：实时推送/AI 配置按账号保存，数据源/缓存/调度仅管理员可改
  ├── /admin/users      # 账号管理 (admin/AccountAdmin，仅管理员)
  ├── /admin/permissions# 页面权限 (admin/RoutePermission，仅管理员)
  └── /admin/features   # 高级功能 (admin/FeatureQuota，仅管理员)
```

### 路由守卫

`beforeEach` 是异步的，按「认证 → 权限 → 页面闸门」三层判断：

1. 无 Token → `usePermissionStore().reset()` 后重定向 `/login`（避免换账号沿用旧权限）
2. 有 Token 且权限未加载 → `await permission.fetchMine()`（`GET /auth/permissions/me`）
3. `meta.admin === true` 且 `!permission.isAdmin` → 跳到 `permission.firstAllowed()`
4. 目标路径不在 `allowedPaths` 中 → 同样跳 `firstAllowed()`

后台管理三条路由额外带 `meta.admin`，即使后台把 `/admin/*` 误勾给普通角色，前端这一层仍会拦住；
后端 `/api/auth/admin/**` 还会再校验一次数据库里的角色，形成双重闸门。

页面清单的单一来源是后端 `RouteCatalog`（`services/auth/.../support/RouteCatalog.java`）：
新增页面必须同时登记到该清单，否则不会出现在权限管理页，路由守卫也会判为无权限。

---

## 四、API 层设计

### 4.1 Axios 实例 (`request.ts`)

```
baseURL: /api
timeout: 30s

请求拦截器:
  - 从 localStorage 读取 token
  - 设置 Authorization: Bearer {token}

响应拦截器:
  - code === 200 → 返回 data 字段
  - code !== 200 → ElMessage.error 提示
  - HTTP 401 → 清除 Token + 跳转登录页
```

### 4.2 接口概览

| 模块 | 文件 | 主要接口 |
|------|------|---------|
| auth | `api/auth.ts` | login, register, getUserInfo, logout |
| admin | `api/admin.ts` | listUsers, createUser, updateUser, deleteUser, getRoutePermissions, saveRoutePermissions, getFeatureQuotas, saveFeatureQuotas |
| access | `api/admin.ts` | getMyPermissions, getMyQuota（所有登录用户可用） |
| signal | `api/signal.ts` | getTodaySignals, getSignalHistory, getSignalCalendar |
| strategy | `api/strategy.ts` | getConfigs, updateConfig, submitBacktest, getBacktestTask, analyzeFactorsBatch, getSignalPerformance, syncSignalCache, backfillSignalOutcomes |
| fund | `api/fund.ts` | getPositions, getNavCurve, getReturnAttribution, getAccountSummary |
| data | `api/data.ts` | getTradeDates（真实 A 股交易日历，信号日历判定休市日） |

---

## 五、状态管理

### 5.1 userStore

```
状态:
  token: string          - JWT Token
  userInfo: UserInfo     - 用户信息
  isLoggedIn: boolean    - 登录状态

动作:
  login(params)          - 登录（调用 API + 存 Token，重置权限与 AI 缓存）
  checkAuth()            - 检查认证（获取用户信息）
  logout()               - 登出（清除 Token + 权限 + AI 缓存）
```

### 5.2 signalStore

```
状态:
  currentSignals: TradeSignal[]   - 当前未读信号
  signalHistory: TradeSignal[]    - 历史信号
  wsConnection: WebSocket         - WebSocket 实例
  isConnected: boolean            - 连接状态

动作:
  fetchTodaySignals(strategyType) - 获取今日信号
  fetchSignalHistory(params)      - 获取历史信号
  connectWebSocket()              - 建立 WS 连接（自动重连 5s）
  disconnectWebSocket()           - 断开 WS 连接
```

### 5.3 themeStore

```
状态:
  mode: 'light' | 'dark'  - 当前主题模式

动作:
  toggle()                - 切换亮色 / 暗色
  applyTheme()            - 应用主题到 html.dark
```

### 5.4 permissionStore

```
状态:
  role: string            - 当前角色（USER / ADMIN），来自后端
  isAdmin: boolean        - 是否管理员
  allowedPaths: string[]  - 可访问页面路径
  loaded: boolean         - 是否已加载（路由守卫据此决定是否拉取）
  degraded: boolean       - 接口不可用时的降级标记

动作:
  fetchMine()             - GET /auth/permissions/me（并发去重）
  can(path)               - 单页可访问性；降级时仅拦 /admin/*
  firstAllowed()          - 无权访问时的落点
  refresh() / reset()     - 权限变更后重取 / 登录、登出时清空
```

`userStore.login()` 与 `logout()` 都会 `reset()` 权限 store，保证换账号不沿用旧权限；
侧栏 `MainLayout` 的分组与条目按 `can(path)` 过滤（`后台管理` 组对普通账号整组隐藏）。

### 5.5 aiStore

```
状态:
  providers: ProviderConfig[]   - 当前账号可用提供商（每次 loadProviders 重新拉取）
  lastProvider / lastModel      - 上次选择的提供商与模型（localStorage 偏好）

动作:
  loadProviders()               - GET /ai/providers?configured_only=true
  setProvider(provider, model)  - 记录选择并写 localStorage
  reset()                       - 换账号时清空提供商列表、模型偏好与 sessionStorage 对话状态
```

**账号切换必须清掉 AI 会话缓存**。`ChatAssistant` 原来把整段对话（`messages`）写进
`sessionStorage['ai_chat_state']`，登出时没有清理：admin 退出后登录另一个账号，打开 AI 侧栏
会直接看到 admin 的对话正文。后端 `user:{id}:ai:*` 本身是按账号隔离的，串的纯粹是前端缓存。

现行规则：

- `sessionStorage` 只存对话 **id**（`AI_CHAT_STATE_KEY`），消息一律由 `GET /ai/conversations/{id}`
  按当前账号重新拉取，不落本地；
- `userStore.login()` / `logout()` 均调用 `aiStore.reset()`，同时清掉提供商偏好键；
- 恢复的对话 id 若不属于当前账号（后端查不到），`switchConversation` 会丢弃该 id 并清空缓存；
- 升级前遗留的旧格式缓存（带 `messages`）不会再被读取，只会取其中的 `convId`，取不到即视为空。

---

## 六、设计系统 (Design System)

所有设计 Token 定义在 `frontend/src/styles/index.scss`，使用 CSS 自定义属性。**严禁在组件样式中硬编码颜色、间距或阴影**，必须使用 `var(--xxx)` 引用。

### 6.1 色彩系统

| 类别 | 变量前缀 | 说明 |
|------|---------|------|
| 背景 | `--bg-*` | page(页面), surface(浮层), subtle(浅底), rail(图标轨), hover, active |
| 文本 | `--text-*` | primary, secondary, tertiary(≥4.5:1), inverse |
| 边框 | `--border-*` | primary(分隔线), secondary, subtle, strong(输入框) |
| 主题色 | `--accent-*` | primary(#4051E0，深色 #7B93F5), soft(大面积图表), hover, text(彩色文字), light(选中底), success(卖出/绿), danger(买入/红), warning |
| 阴影 | `--shadow-*` | modal(仅浮层)；卡片阴影已移除 |
| 圆角 | `--radius-*` | sm(4px), md(6px), lg(8px) |
| 字体 | `--font-*` | sans(Manrope+中文), mono(IBM Plex Mono 数字) |
| 动效 | `--dur-*` / `--ease` | fast(120ms), base(200ms)；仅 transform/opacity |

### 6.2 暗色主题

暗色主题通过 `html.dark` 选择器自动切换所有 CSS 变量。**严禁在组件中写单独的暗色模式样式**——只需使用 `var(--xxx)`，主题切换自动生效。

主题切换时，`html` 元素会短暂添加 `theme-switching` 类来抑制所有过渡动画，防止闪烁。

### 6.3 Element Plus 变量映射

`index.scss` 中将 Element Plus 的 CSS 变量映射到设计系统变量（如 `--el-color-primary: var(--accent-primary)`），确保 Element Plus 组件自动跟随主题。

- **必须用 `html:root` 而不是 `:root`**：EP 按需引入后组件 CSS 分片在入口样式之后加载，同特异性的 `:root` 会被它们的默认值覆盖（主色退回 `#409EFF`、info 退回 `#909399`），表现为"令牌写了但没生效"
- **组件级覆盖用双类选择器**（`.el-tag.el-tag--primary`）才能压过分片样式
- **品牌蓝固定五档**（原 `#637EE8` 白字仅 3.4:1，且页面各写近似蓝导致纯色块发灰、浅底出现两种）：

  | 变量 | 值 | 白底对比度 | 用在哪 |
  |---|---|---|---|
  | `--accent-primary` | `#4051E0` | 6.1（白字压它 6.1） | 填充、描边、选中态 |
  | `--accent-primary-hover` | `#3343C7` | 7.6 | 悬停/按下 |
  | `--accent-primary-text` | `#3A4BD4` | 6.7 | 彩色文字、链接 |
  | `--accent-primary-light` | `#EEF1FD` | 1.1 | 选中底、标签底（唯一浅蓝） |
  | `--accent-primary-soft` | `#5F72E8` | 4.2 | 大面积图表/描边（非文本，≥3 即可） |

- **`--bg-active` 已改为 `var(--accent-primary-light)`**：原 `#EFF2FD` 与 `#EEF1FD` 差一个色阶，侧栏选中与卡片选中出现两种浅蓝，现全局只有一个浅蓝
- **小字与链接用 `--accent-primary-text`**，不要直接用 `--accent-primary`
- **页面/ECharts 不得再手写蓝色十六进制**：需要常量时用 `#4051E0`（已替换 Fund/Review/Monitor/StockSense 里的旧值）
- `--text-tertiary` 由 `#71717A` 压深到 `#6A6A72`：原值在 `--bg-rail` / `--bg-secondary` 上仅 4.3:1
- **ECharts / 内联 style 不能用 `var()`**（canvas 渲染不解析 CSS 变量），必须写具体色值；`Fund.vue` 的 `themeColors` 已把 EP 默认红绿橙（2.0~3.1:1）换成语义色

### 6.4 品牌标识（RS 字母标）

- 唯一图形：64×64 圆角方块 + 白色几何 `RS`，保留原 PWA 字母识别；底色用 `--accent-primary-soft` → `--accent-primary` 斜向渐变（深色主题为 `#5F72E8` → `#7B93F5`，`--accent-primary-soft` 不在暗色主题中覆盖）。字母用矢量路径绘制，不再依赖系统字体渲染 `text`。
- 源文件：`frontend/public/brand/rs-mark.svg`（浅）、`rs-mark-dark.svg`（深）；位图 `rs-mark-16/32/48/192/512.png` 由同一份矢量导出。`pwa-192x192.svg` / `pwa-512x512.svg` 是同一图形的 PWA 尺寸版。
- 站内统一用 `components/BrandMark.vue`（`:size` 指定像素，渐变取 CSS 变量自动跟随主题）：侧栏、登录页、AI 助手欢迎语共用；禁止再写 `LS` 字样、`TrendCharts` 占位或其他自定义渐变。
- favicon 与 PWA manifest 同步引用这套文件，manifest `theme_color` 用 `#4051E0`，不再用 Element Plus 默认蓝 `#409eff`。
- `favicon.ico` 由 16/32/48 PNG 打包，供桌面快捷方式与旧浏览器使用；`nginx/default.conf` 必须给 `.webmanifest` 返回 `application/manifest+json`（nginx 默认按 `application/octet-stream` 返回会让安装应用读不到图标），并把图标 URL 从 immutable 30 天改成 `no-store`。此外 `vite.config.ts` 会按图标文件的 SHA-256 生成 8 位版本参数，注入 HTML 的 favicon 链接与 manifest 图标 URL：Windows/Chrome 按**完整 URL**缓存已安装 PWA 的图标，固定 URL 换内容不生效，必须让 URL 随图标内容一起变。已安装的 PWA 还需卸载后重装，桌面/任务栏图标才会替换（必要时清 Chrome 的 Web Applications 缓存与 Windows 图标缓存）。

### 6.5 信号方向颜色约定

- **买入 (BUY)**: 红色 `var(--accent-danger)` （A股红色为涨）
- **卖出 (SELL)**: 绿色 `var(--accent-success)` （A股绿色为跌）

CSS 工具类：`.signal-buy` / `.signal-sell`

### 6.6 停用指标置灰约定

沪深港通自 2024-08-19 起停止披露北向资金净买额，该指标保留展示但一律置灰并标注"已停用"，避免误读：

- `FactorRanking.vue`：北向净流入列加 `label-class-name="col-disabled"`，表头带 `el-tag` 与 `el-tooltip`
- `DataReplay.vue`：北向列、图表系列（灰色 + `opacity: 0.5`）、tooltip 文案统一标注"已停用"
- `FactorAnalysis.vue`：因子标签显示为"北向资金(已停用)"，因子说明标注停用原因
- `Settings.vue`：北向采集时点输入框 `disabled`，整项加 `feature-disabled` 类并标注"已停用"

CSS 工具类：`.disabled-text`（置灰文本）、`.col-disabled`（表格列置灰）

### 6.6 v6 结构规范（强制）

**任何前端改动必须先对照 `CLAUDE.md` User Rules 与视觉稿 `design-preview.html` (v7)，禁止回退到旧的「220px 深色侧栏 + 卡片网格」模式，也不要回到 v5 无边框方案（真实界面反馈看不清边界、分不清主次）。**

- **导航**：桌面默认 200px 带文字侧栏（`.sidebar`，11 项按业务域分组），可折叠为 60px 图标轨；移动端 56px 底部标签栏（`.bottom-tabs`，5 个主入口 + 「更多」抽屉含全部 11 项）。**严禁以简化为由删减导航项**
- **顶栏**：取消独立 header，改用 `.page-context` 上下文行（页面标题 + 全局策略 + 紧凑图标），与页面同底色
- **内容区**：轻量卡片 —— 白底 + 1px 边框 + 6px 圆角 + 24px 内边距 + 24px 区块间距，**无阴影**；卡片标题带 2px 主色短条区分主次，标题下方 1px 分隔线
- **KPI**：`.stat-grid` + `.stat-card` 为同规格轻量卡片，28px 等宽数字，无彩色图标块
- **AI 面板**：`.ai-sidebar` 桌面 640px 浮层、移动 100vw 全屏；是唯一保留阴影的区域。宽度不可压缩（曾由 640px 误改为 400px，导致图表显示不完整）
- **动效**：只动 `transform` / `opacity` / 颜色，时长只用 120ms / 200ms 两档，细则见 6.7
- **兼容别名**：旧令牌已映射到新令牌，未改造页面仍可运行，但新代码必须使用新令牌

### 6.7 动效规范（强制）

本节是动效的唯一出处。令牌定义在 `frontend/src/styles/index.scss`；全站 `transition` 只能引用这两个时长和一个缓动，**禁止写裸数值**。

#### 6.7.1 令牌

| 令牌 | 值 | 用途 |
|---|---|---|
| `--dur-fast` | `120ms` | 颜色、背景、边框的 hover / focus / active 反馈 |
| `--dur-base` | `200ms` | 位移、展开、宽度变化（侧栏折叠、抽屉、面板切换） |
| `--ease` | `cubic-bezier(.2, .8, .2, 1)` | 唯一缓动曲线：起步稍快、收尾平缓 |

变量段里的兼容别名 `--transition-fast` / `--transition-base` / `--transition-slow` 是旧写法（不带缓动，slow 为 300ms，全站 0 引用），**新代码禁止使用**。

#### 6.7.2 可动属性白名单

| 类别 | 属性 | 说明 |
|---|---|---|
| 合成 | `transform`、`opacity` | 首选，不触发布局与重绘 |
| 绘制 | `background-color`、`color`、`border-color` | 按钮、链接、输入框的悬停反馈 |
| 布局（例外，需注明） | `width` / `min-width` | 仅限侧栏 200↔60 折叠这一处 |

其余属性不动，尤其 `height`、`margin`、`padding`、`top`/`left`，以及 `all`。

#### 6.7.3 只有两档过渡

| 时长 | 用来做什么 |
|---|---|
| 120ms | 任何"指针离开前就要看到结果"的状态变化：hover、focus、选中 |
| 200ms | 任何元素位置或尺寸变化：侧栏折叠、抽屉推开、面板展开 |

循环类动画不属于过渡阶梯，单独管理：骨架 `skeleton-shimmer 1.4s`、AI 思考圈 `spin 1s`、工具脉冲 `pulse 1.5s`、typing `1.4s`、登录背景 `orb-float 20s`。

#### 6.7.4 禁止项

| 禁止 | 原因 |
|---|---|
| `transition: all` | 把布局属性一起带上，长列表滚动时逐行触发重排 |
| 裸时长（`0.3s`、`150ms`、`var(--transition-fast, 150ms)`） | 绕过令牌，主题切换与降级无法整体生效 |
| 给表格行、长列表项加 `transition` | 90 行表格 hover 扫描时每行一次样式重算 |
| 数据刷新做淡入淡出 | 轮询型页面会周期性闪动；数据变更用骨架或原地替换 |
| 动画改变占位高度 | 触发 CLS；展开收合直接显示或用 `grid-template-rows` |
| 给文本容器做 `width` 动画 | 每帧重排文本，改用 `transform: scaleX` 或不做 |
| 页面内单独写 `prefers-reduced-motion` 块 | 全局已统一处理，重复写会漏掉部分元素 |

#### 6.7.5 降级

`prefers-reduced-motion: reduce` 在 `index.scss` 末尾统一处理一次：`animation-duration` / `transition-duration` 压到 `.01ms`、`animation-iteration-count: 1`、`scroll-behavior: auto`。页面不得再写第二份降级。

#### 6.7.6 校验

```powershell
cd frontend/src
# 两条都应为 0 命中
Get-ChildItem -Recurse -Include *.vue,*.scss | Select-String -Pattern 'transition:\s*all'
Get-ChildItem -Recurse -Include *.vue,*.scss | Select-String -Pattern 'transition[^:]*:[^;]*\d+(\.\d+)?m?s' |
  Where-Object { $_.Line -notmatch 'var\(--dur-' }
```

2026-11-22 实测：全站 `transition` 声明 17 条，其中 1 条为 `transition: none !important`（显式禁用），其余 16 条全部引用 `--dur-fast` / `--dur-base` + `--ease`；`transition: all` 与裸时长均为 0。本次清零的 5 处历史遗留：`MainLayout.vue`（1）、`Login.vue`（2）、`StockSense.vue`（1，原为 `var(--transition-fast, 150ms)` 带假回退）、`Monitor.vue`（1，原用别名 `--transition-base` 且无缓动）。

**判定口径**：只统计 `frontend/src` 下的自有源码。Element Plus 组件内部自带 `transition: all`（`.el-button`、`.el-radio__inner`、`.el-drawer__dragger` 等）与 0.1s–0.6s 的多档时长，属库行为，不纳入本规范；要统一必须走 EP 变量（`--el-transition-*`），不要在页面里覆写。主题切换时 `html.theme-switching *` 的 `transition: none !important` 是有意为之，避免切主题时全站动画。

---

## 七、响应式设计

### 7.1 断点定义

| 名称 | 宽度 | 目标设备 |
|------|------|---------|
| 移动端 | ≤ 480px | 手机 |
| 平板 | ≤ 768px | iPad / 小屏笔记本 |
| 小桌面 | ≤ 1024px | 窄屏笔记本 |
| 桌面 | > 1024px | 标准显示器 |

### 7.2 全局响应式工具类

| 类名 | 用途 |
|------|------|
| `.responsive-table` | 包裹 `el-table`，窄屏时水平滚动 |
| `.page-section` | 卡片区块之间的统一间距（24px，移动端 16px） |
| `.page-card` | 轻量卡片容器，白底 + 1px 边框 + 6px 圆角，自带 `margin-bottom: 24px` |
| `.hide-mobile` | ≤480px 隐藏 |
| `.hide-tablet` | ≤768px 隐藏 |

### 7.3 全局自动响应式行为

以下行为由 `index.scss` 中的媒体查询自动处理，**组件中无需额外编写**：

- **`el-form--inline`**：≤768px 换行，≤480px 完全堆叠（纵向排列）
- **`el-date-editor--daterange`**：≤480px 宽度 100%，内部两个输入各占 40%
- **`.el-date-range-picker` 弹出层**：≤480px 两个日历面板纵向堆叠
- **`.page-card .card-header`**：≤480px 标题和操作区纵向堆叠
- **`.sidebar` / `.bottom-tabs`**：桌面默认 200px 带文字侧栏，可折叠为 60px 图标轨；≤768px 隐藏，由 56px 底部标签栏替代（含安全区适配）
- **`.ai-sidebar`**：桌面 640px 浮层；≤768px 全屏，遮罩保留
- **`.el-row` 栅格间距**：≤768px 减小到 8px，≤480px 减小到 4px

### 7.4 `useBreakpoint` 组合式函数

位于 `@/composables/useBreakpoint.ts`，用于图表坐标轴标签密度等需要 JS 判断的场景。

```ts
import { useBreakpoint } from '@/composables/useBreakpoint'
const bp = useBreakpoint()

// 响应式断点判断
bp.isMobile.value   // width < 480
bp.isTablet.value   // width < 768
bp.isDesktop.value  // width >= 1024

// 图表标签优化
bp.labelInterval(dataLength)  // 返回每隔几个标签显示一个
bp.labelCount(dataLength, minLabels)  // 返回总共显示几个标签
```

### 7.5 移动端强制规范（≤480px，所有页面必须遵守）

> 这是移动端设计与实现的唯一依据。任何移动端样式改动必须先对照本规则，禁止凭感觉调整。
> 目标：一屏内能看到足够信息，图表清晰可辨，K线可交互。

#### 7.5.1 字体（硬上限，不得超出）

| 场景 | 字号 | 令牌 |
|------|------|------|
| 页面主标题 h1 | 17px | `--m-fs-title` |
| 卡片标题 / 区块标题 | 13px | `--m-fs-card` |
| 正文 / 表单控件 / 按钮 | 12px | `--m-fs-body` |
| 表单标签 / 次要信息 / 表格 | 11px | `--m-fs-sub` |
| 辅助文字 / 标签 tag / 图例 / 轴标签 | 10-11px | `--m-fs-tiny` |
| KPI 数值（stat-value） | 18px | `--m-fs-kpi` |
| 数值强调（条目列表内） | 13-14px | — |

- 手机上 14px 已属大号；**正文一律 12px，只有 KPI 数值、页面标题可超过 13px**
- 禁止任何非 KPI 场景出现 ≥ 18px 字号
- **字号下限：常规文本 11px，纯辅助标签允许 10px，禁止再出现 9px**（9px 在 390px 下已不可读，日志/健康检查/复盘说明等原 9px 处已提到 10-11px）
- 统计/说明文字必须允许换行：`overflow-wrap: anywhere`，禁止长文本撑破容器
- Element Plus 的 CSS 由异步 chunk 注入，加载顺序不稳定，**移动层对组件内部字号与高度必须用 `!important` 收敛**（见 `styles/mobile.scss` 末尾「字号强制收敛」段），否则 `.el-button > span`、`.el-alert__title` 等仍会停在 14px；各页面 scoped 写死的 `height:24/32` 同理，会被统一抬到 32（`--m-tap`）
- `.el-input__wrapper` / `.el-select__wrapper` 是 content-box，只写 `min-height:32` 会实测到 34（32 + 上下 padding 1px），必须同时 `box-sizing:border-box`

#### 7.5.2 布局与间距

| 项目 | 规范 |
|------|------|
| 页面左右内边距 | 10px |
| 页面顶部内边距 | 标题区上 12px；`.page-content` 上 10px（`padding: var(--m-pad) 10px 12px`），保证首张卡片不顶住标题栏下边框 |
| 卡片内边距 | 10px（桌面 24px） |
| 卡片之间间距 | 8px（桌面 24px） |
| 表单项高度 | ≤ 56px，标签在上、控件全宽 |
| 触控高度 | 所有可点区域 32px（`--m-tap`，与桌面同档）：按钮、下拉、输入框、周期/分段切换，不再有 30/26/36 多档；控件偏大时整屏没有主次，主次交给字重（主操作 600）与颜色 |
| 触控目标下限 | 24×24（WCAG 2.5.8）：小号 `el-input-number` 默认 25×22，移动层已抬到 32px 高输入框，加减按钮 25×30 |
| 表单项之间间距 | 8-10px |
| 统计卡片 | 2 列，数值 18px |
| 一屏信息密度 | 844px 高的屏幕至少可见 6 个表单控件 / 2 个卡片 |
| 弹层抽屉 | 宽 `calc(100vw - 16px)`，内部 padding 8-10px，内容单列 |

- 表单严禁两个控件并排挤在一行（除非是两个短按钮）
- 长文本区（复盘说明、统计描述）必须单列展示，禁止"缩略图 + 窄文字列"造成文字竖排
- **卡片头部（`.card-header`）**：标题左对齐、控件右对齐并保持同一行（`flex-direction: row; flex-wrap: wrap; justify-content: space-between`），放不下才换行；控件按内容宽度（下拉 ≥120px），**禁止拉伸成整行宽按钮/下拉**
- **行内表单（`.el-form--inline`）**：Element Plus 给的是 `display: block`，只写 `flex-direction: column` 无效，会让表单项收缩成几十像素、下拉选中值看不见；移动层必须 `display: flex !important` 否则整块筛选区失效
- 标题左边界基准：页面内边距 10px + 卡片内边距 10px ≈ 21px；去壳卡片（`padding: 0`）会让标题比其它页少缩进 11px，视觉上"有的居中有的居左"，不允许再对 `.page-card` 写 `padding: 0`
- **相邻触控目标间距 ≥8px**：底部标签栏为 5 列 grid，必须保留 `column-gap: 8px`，否则相邻 tab 边缘贴合（每列仍为 72px 宽，远高于 44px）
- **标签页（`el-tabs`）**：条目统一 32px 高（`--m-tap`，EP 默认 top 型 40、border-card 型 32，是同站两档的由来），选择器必须带 `.el-tabs__header`（0,2,0），否则被 EP 后注入的 (0,1,0) 压回；`border-card` 的内容区必须有 `padding: var(--m-pad)`，页面 scoped 写 `padding: 0` 会让第一张卡片顶在标签条下边框、最后一行贴住容器底部（设置页踩过）
- **点击延迟**：可交互元素（`a`/`button`/`input`/`label`/EP 按钮、下拉、标签页、分页）统一 `touch-action: manipulation`，去掉双击缩放的 300ms 等待；`body` 不加，正文保留双击缩放

#### 7.5.3 图表（ECharts，所有图表）

| 项目 | 规范 |
|------|------|
| 主图高度 | 260-300px（不得压缩到 200px 以下） |
| 多子图总高 | ≤ 420px，每个子图 ≥ 70px |
| 图例 | 图表顶部横向单行，字号 9px，最多 4 项，超出用滚动或省略 |
| 坐标轴标签 | 9px，旋转 ≤ 45°，长名称截断到 4-6 字 + `…` |
| 双 Y 轴 | 移动端隐藏轴名称，仅用图例颜色区分左右轴 |
| 图表容器 | 不得出现嵌套滚动条；`autoresize` 必须开启 |
| 图表下方留白 | visualMap/图例与 x 轴标签间距 ≥ 30px，禁止重叠 |

- 禁止把多个 ECharts 实例垂直堆叠来-multiplex 一个逻辑图表，应使用单个 option 的多 grid
- 图例文字与图形必须对齐，禁止出现文字压在图形上
- `calendar` + `visualMap`：一律用**七天横向月历**（`orient: 'vertical'` 才是 7 列 × 6 行；`horizontal` 是 6 列周视图，格子会被横向拉宽），`dayLabel.firstDay: 0` 且 `nameMap: ['日','一','二','三','四','五','六']`，`rangeStart` 取当月 1 号所在周的周日，固定 42 格。格子内两行标签：第一行日号、第二行状态/收益；列宽用 `cellSize: ['auto', 行高]` 配 `left/right: 12` 自适应卡片宽度（禁止写死 7×44=308px 的固定宽度，卡片会显得很小）；行高桌面 44、平板 34、手机 36，对应容器 320/260/280px；`calendar.top` 至少 30，否则星期抬头会被画布裁掉。格子边框色与卡片底色一致（浅 `#FFFFFF` / 深 `#17171A`），只让日期格子本身着色，不画整片网格线；间隙靠边框撑开，`borderWidth` 手机 2 / 桌面 3、`borderRadius` 手机 5 / 桌面 7，过窄会显得拥挤；所有格子必须统一圆角与间隙，且**每个 series 都要显式写 `itemStyle`**——只写在 `calendar.itemStyle` 上时，未显式设置的系列会回退到 ECharts 默认样式，出现部分格子无圆角、间隙不一致。两个日历共用 `utils/calendarStyle.ts` 的 `calendarItemStyle` / `calendarLabelBase` / `calendarCellPalette` / `calendarSurfaceColor` / `calendarEmphasisItemStyle`，保证风格一致。标签两行都 `align: 'center'` + `verticalAlign: 'middle'`；日期数字用 Manrope、字号 12/13 且加粗，第二行状态/收益用中文系统字体、字号 9/10 常规字重；`label.color` 控制日期数字、`rich` 控制第二行文字，按数据层级分别指定颜色。三档底色与文字色**统一走 `calendarCellPalette`**：本月交易日(无数据) 浅 `#D7DBE2` / 深 `#454B58`，本月休市 浅 `#EAECF0` / 深 `#2C303A`，非本月 浅 `#F7F7F8` / 深 `#1B1D23`；两页不得各自硬编码一套，否则着色明显不一致。`calendar.itemStyle.color` 必须取 `calendarSurfaceColor`（与卡片底色相同），不能填中性底色——ECharts 会在圆角缺口处露出这一层，导致格子交叉处出现杂色斑点。每个 series 必须显式带 `emphasis.itemStyle`（统一走 `calendarEmphasisItemStyle`，用主题强调色 浅 `#4051E0` / 深 `#7B93F5`），禁止悬停后仍贴近中性底色；`calendarLabelBase` 的 `emphasis` 把日期数字放大到 15/17 并加粗、第二行放到 11/12，两行文字统一转白。本月内「未来交易日」也要填格子，否则月中会出现没有内容的空洞
- 信号日历（Dashboard）：格子下方「休 / 空 / 调」分别对应非交易日、已计算空仓、有买卖信号。休市判定走 `api/data.ts` 的 `/api/data/trade-dates?days=400`（`composables/useTradeCalendar.ts` 全局缓存一次）+ 周末兜底；接口只覆盖最近 N 个交易日，范围外不可标休市，避免误判。收益日历（Fund）只显示日号 + 当日收益率并按红涨绿跌着色，不展示空仓/调仓。两个日历都把 42 格拆成四个互斥 series（有数据 / 交易日无数据 / 休市 / 非本月），底色、日期数字色、第二行文字色与星期抬头色共用同一套 palette；`visualMap` 的 0 点等于 `palette.neutral`，只是有数据时的强调色按业务区分（信号数量用绿色系，收益率用红涨绿跌，且盈亏日历的红绿直接取 `themeColors.profit/loss`，格子与色阶条同色、不另写硬编码值），空仓日保留蓝色标记。`label.color` 与 `rich` 按同一层级递减对比，禁止只靠强调色把所有格子染成近似同色
- 日历里「非本月」日期必须是独立 series（`visualMap.seriesIndex` 默认只作用于 0 号系列），否则被一并染色、与本月无区分；点击事件也要提前 return 忽略非本月

#### 7.5.4 K 线交互（盘感训练 / 数据回放 / 训练复盘）

| 项目 | 规范 |
|------|------|
| 显示宽度 | 容器与画布 100% 视口宽（≈348px），**不得**再用固定 600px + 横向滚动 |
| 可视根数 | 默认 40 根（桌面未缩放时整段），单根 ≈ 8-9px；用 `startValue`/`endValue` 控制，不用像素宽度。用户捏合/拖滑块后的窗口即「用户窗口」，宽度跨操作保留，并写入 localStorage（`stock-sense-zoom-bars:<user>`，存根数不存百分比）供下次训练复用 |
| 手势缩放 | `dataZoom` type=inside，触摸捏合；slider `height:12`、`showDetail:false`；`datazoom` 事件把窗口写回 `zoomWin`，160ms 防抖，按钮操作前先 flush |
| 下一根自动前移 | `ensureCurrentBarVisible()` 只保证「当前根可见」：当前根已在窗口内一律不动（买卖/划线/微调都不重置缩放）；越出右边界才整体右移一根、宽度不变。**不能用 `dispatchAction`**：option 重建会把手势窗口覆盖回 `start:0, end:100`（整段） |
| 操作条顺序 | 仓位 → 买入/卖出 → 自动播放 + 速率 → 按天/按周 → 下一根（末位）。播放类放前段，高频「下一根」独立放末尾，避免夹在低频切换中间误触；结束训练用 `type="danger"` 实心按钮 |
| 复盘视窗 | 训练复盘按时间顺序看，视窗**锚定区间开头**（`start: 0`，手机 40 根 / 桌面 60 根），后续走势靠拖滑块/捏合；不要用 `total - win` 停在末尾——那样一进来看到的是训练区间之后的后市 |
| 图例位置 | 图表顶部单行，`fontSize:9`，`itemWidth:12`、`itemHeight:6`；盘感训练图例 `top:26`，把 0-24px 让给提示横条 |
| 子图高度 | K线主图 150-160px，成交量 ≥ 60px，MACD ≥ 60px；总高 300-320px；主图 `top:44` 时按 42% / 56% / 76% 收缩，避免与下方子图重叠 |
| grid | `left:4, right:4`，横轴铺满视口；纵轴 `axisLabel.inside:true` 显示在图内，移动端隐藏 `axisLine` / `axisTick`，禁止左侧留白吃掉 K 线宽度 |
| 提示横条 | `triggerOn:'click'` + `confine:true`，`position` 把 y 钉在图顶；盘感训练 y=0（0-24px），数据回放图例占 0-14px 故取 y=18（18-42px，grid 从 45px 开始）。formatter 单行输出「日期 开 高 低 收 涨跌幅（+资金流）」，指数级 OHLC 取整保证横条 ≤348px |
| 放大镜 | 微调时不用右上角 330×200 浮层：移动端改为图顶 24px 全宽横条（`box-sizing:border-box`、21 根迷你 K 线、标题去前缀、隐藏 markLine 标签），与 tooltip 互斥（`tooltip.show = !magnifier`） |
| 周期切换 | 数据回放按板块 K 线提供 日K/周K/月K/季K 四档，按自然周/月/季在前端聚合（开=组内首根、收=末根、高低=极值、资金流求和），不新增后端接口。控件放图表外独立工具栏：移动端四等分、选中态用主色，桌面 24px；切换后 MA 与 dataZoom 窗口按新根数重算 |
| 均线开关 | 禁用 ECharts 内置 legend（长文本在窄屏换行会压住 K 线），改为工具栏内 MA5 / MA10 / MA20 / MA60 四条独立 toggle（桌面 24px、手机 32px 触控高，默认开前三条），同排标注「主力净流入」与「北向·已停用」；series 按开关状态与当前周期重算 |
| 图表布局 | 周期与图例工具栏紧贴图表（间距 8px），统计信息统一放图表下方，禁止夹在工具栏与 K 线之间造成割裂 |
| 最小可视根数 | 雪球式最小窗口 28 根：inside 与 slider 两个 `dataZoom` 都设 `minValueSpan: Math.min(28, dates.length)`，捏合/放大无法把窗口缩到 28 根以下（再放大无意义）。**盘感训练/复盘是例外**：要放大看单根细节与微调锚点，下限取 `MIN_ZOOM_BARS = 6`（与 `stock-sense-zoom-bars` 的存储下限同源），写成 `minValueSpan: Math.min(MIN_ZOOM_BARS, dates.length) - 1`，训练图与复盘图共用 `buildChartOption` 故一处生效。注意 `minValueSpan` 是**索引跨度**、可视根数 = 跨度 + 1（回放写 28 即最少 29 根；盘感减 1 后实测 inside 滚轮缩到极限、拖滑块右手柄缩到极限都停在 6 根，`stock-sense-zoom-bars` 也写回 6，与 `readZoomBars` 下限一致不回跳）。窗口百分比存 `klineStart`/`klineEnd` **普通变量（非响应式）**，`datazoom` 事件写回、option 重算时回填，禁止在 option 里写死 `start`（否则 asLine/均线切换触发 `setOption` 会把用户缩放重置回默认窗口） |
| 过密折线模式 | 可视根数 > 120（`LINE_KLINE_BARS`）时主图由 `candlestick` 切为 `line`（`symbol:'none'`），同时移除全部 MA series 并把工具栏均线区置灰（`.kline-ma.ma-hidden`），提示文案改为「K线过密，已切折线模式」。折线 series 的 `data` 是收盘价数字而非 OHLC 数组，formatter 与自绘横条都需兼容两种形态：candlestick data 为 4 元素（`[open,close,low,high]`），折线为数字（`[d,d,d,d]` 展开），解构错位会显示 NaN |
| 移动端手势 | 容器 `touch-action:none` 阻止页面滚动。**单指平移自己接管，不用 ECharts inside 内置拖动**：移动端点按/滑动实测 ECharts `moveOnMouseMove` 跟手极差（滑一屏只走约 5 根，鼠标拖动却正常），故移动端把 `moveOnMouseMove` 设 false，`pointerdown` 锁定当前 dataZoom 窗口为基准，`pointermove` 按 `deltaPct = dx / 图宽 × 窗口跨度` 直接 `dispatchAction(dataZoom)` 更新 start/end（**拖拽内容语义：右滑 dx>0 露出左侧更早数据 → `start = 基准start - deltaPct`，左滑则 `start` 增大；窗口跨度不变，撞 0/100 边界时平移量被 clamp**），`dispatchAction` 不指定 `dataZoomIndex` 以同步 inside + slider 两个组件，实测 348px 图宽 / 60 根窗口下每滑 20px 推进 3.4 根、1:1 跟手；双指捏合缩放仍交给 inside（不受影响）。**K 线图必须设 `animationDurationUpdate: 0`**：ECharts 默认 500ms 更新动画会被每帧 `dispatchAction` 反复重启并互相排队，实测松手后画面仍要追 0.5-1s 才到位，主观感受是「K 线过一会儿才过来、过来后才重绘，均线反而像跟手」（candlestick 每根 4 个图形逐项补间，耗时远大于单条 polyline）；置 0 后松手即终态（0/120/400ms 取样像素完全一致），首帧 `animationDuration` 淡入保留。单次 `dispatchAction`（482 根数据、60 根窗口）实测 7-14ms，20 次连发无堆积、位移与公式完全吻合，故不必再叠 rAF 节流。**拖动是每帧 `dispatchAction`，因此窗口状态 `klineStart`/`klineEnd` 必须是普通变量，不能是 `ref`**：否则每帧 `datazoom` → option computed 重算 → `setOption` 全量重建，既卡顿又会被 `setOption` 覆盖窗口，表现为「拖了不动 / 不即时绘制」；option 里的 `start: klineStart` 只在 asLine、周期、数据等真正变化时才回填一次。**十字线必须自绘 DOM，禁用 ECharts axisPointer**：axisPointer 与平移争用同一组指针事件，`dispatchAction(showTip)` 在捕获拦截平移后会被 ECharts 内部 leave 清掉（滑动中虚线消失），`hideTip` 又清不掉竖虚线（松手残留），两条路都走不通。实现：动态建 `.kline-crosshair` 覆盖层 `.sector-history-chart`（`position:relative`），内层竖虚线 `top:45px` + 图顶横条 `top:18px`；动态节点须复制宿主 `data-v-*` scoped 属性否则样式不生效，层引用存模块级变量避免 `querySelector` 取错容器。流程：`pointerdown` 起 280ms 计时（新触摸先 `clearCross()` 清残留）；`pointermove` 位移 >8px 立即取消计时并进入平移（滑动绝不误弹十字线）；长按激活后清掉平移基准、`stopPropagation` 拦截 move、自绘层跟随手指刷新竖线 left 与横条 OHLC（**不能 `preventDefault`，否则 Chrome 派发 `pointercancel` 被误判松手**）；松手在 `document` 捕获阶段兜底监听（`pointerup`/`pointercancel`，绕开 zrender 指针捕获），清平移基准、直接隐藏所有十字线 DOM 节点再 `clearCross()`。横条 OHLC 取 series[0].data：candlestick 为 4 元素 `[open,close,low,high]`，折线为收盘价数字 |

- 移动端 K 线禁止把整段历史压缩进一屏，也禁止横向滚动整张图；用视窗 + 手势浏览
- 上条手势规则**对全站 K 线图统一生效**：`DataReplay` 板块K线（`.sector-history-chart`）与 `StockSense` 盘感训练/复盘K线（`.kline-chart-scroll`、`.replay-chart`）都要 `moveOnMouseMove: !isMobile` + 自接管平移；且移动端 CSS 必须给这些容器写 `touch-action: none`——缺这条时浏览器把横向拖动判成页面滚动并派发 `pointercancel`，实测表现为第一步移动后窗口就卡死（`startValue` 停在 2 不再前进、后续 `dispatchAction` 全被丢弃）。盘感页微调（`adjustMode`）下拖拽是锚点操作，`enabled()` 返回 false 不平移，退出微调后自动恢复（实测 12..51 微调内不动、退出后右滑 100px → 1..40）。
- 自接管平移必须**让出图表底部滑块区**（触点落在容器底部 26px 内不接管）：那里是 ECharts slider 的选中条与左右手柄，自接管每帧 `dispatchAction` 同宽度窗口会把拖手柄覆盖成整体平移，实测拖右手柄向左 220px 窗口宽度不变、只是整体左移 3 根；让出后同一手势变成收窄（36→18→6 根），滑块条上的拖动则交给 ECharts 自身的整窗平移（100px ≈ 11 根）。
- 盘感页 K 线本来就有 `animation: false`（等价更新动画 0，实测松手像素即终态），无需再叠 `animationDurationUpdate: 0`；`DataReplay` 里带 dataZoom 的资金流柱状图与净值曲线图统一补了 `animationDurationUpdate: 0`，避免拖滑块时 500ms 过渡追赶。
- 当日板块K线尚未生成时接口会给 `open/high/low = 0`、无 `close`（`/data/replay/sector/{code}` 以资金流表的日期为骨架，K 线表缺该日就不覆盖；实测 2026-11-23 收盘后 15:30 采集全板块如此，同花顺当日 K 线稍后才出）。前端**必须把 `<=0` 视为无效价**：日K这一根退回按涨跌幅合成蜡烛；周/月/季聚合只从 `>0` 的候选里取极值、缺失回退当日 `index_close`，并用 `max(open, close, highs)` / `min(open, close, lows)` 兜底。否则 `0` 参与 `Math.min` 会把该组低点压到 0——实测旧实现周线最后一根 `O/H/L` 全为 0、月/季 `low = 0`，就是"最后一根 K 线非常长"的原因。
- "下一根/上一根"按钮必须保证当前 K 线始终在可视区内，不得让用户手动去找
- 复盘抽屉里 `.replay-chart` 的 `min-height` 必须与 `.replay .kline-chart` 同档（桌面 420 / ≤768 280）：只把图表降到 280 而容器还留 420，图表与盘后总结之间就会空出 140px
- 带 `viewBox` 的 SVG 图示（`SenseCandleDiagram`）由组件自身写 `max-width:100%; height:auto`：图示在 `el-dialog` 里，而弹窗 teleport 到 body 后父页面的 `:deep(.el-dialog)` / `:deep(.shape-box svg)` 匹配不到，400px 宽的图会在手机上被裁掉右侧

#### 7.5.5 表格 → 条目列表（必改）

- 列数 > 4 或桌面最小宽度 > 视口宽的 `el-table`，移动端**必须**用 `v-if="isMobile"` 渲染条目列表，`v-else` 保留桌面表格
- 条目结构：主行（名称 + 主指标）/ 副行（2-4 个辅助指标，横向网格或换行）/ 操作行
- 命名统一：`.m-rank-list`、`.m-factor-list`、`.m-bt-list`、`.m-hist-list`、`.m-provider-list`、`.m-pos-list`、`.m-metric-list`、`.m-sector-list`、`.m-cache-list`
- 行间距 8px、块状背景 `--bg-tertiary` + 圆角 4-6px，分隔线仅在列表条目之间
- 未改造的次要表格才允许 `.responsive-table` 横滑兜底；能改造的一律改造

**数据回放页「策略叠加回放」的落地口径**（≤480px）：
- 九列「每日持仓明细」→ `.m-overlay-day-list`（主行日期+策略日收益、持仓/信号标签、四项资产网格）
- 五列「调仓快照」→ `.m-snap-list`（板块+仓位主行、金额/当日涨跌/贡献网格）
- 净值曲线用 `.overlay-chart`，桌面 420px、≤768px 走 `var(--chart-h-md)`；option 按 7.5.3 收缩图例、纵轴标签外置、缩放条压到 14px
- 净值曲线展示口径（仅展示层，数据与后端字段不动）：图内标题「净值走势」+ 桌面副标题「区间收益 / 超额」；图例固定 4 项（策略净值、基准净值、买入、卖出）；x 轴标签只显示 `MM-DD`（完整日期在 tooltip），旋转 0 且 `hideOverlap`；y 轴统一「万」并按净值区间自适应小数位，**移动端与桌面一律标签外置**（靠 `containLabel` 让出宽度，禁止 `inside`：标签压在曲线上无法读）；策略线带同色渐变面积 + 淡投影，基准线灰色虚线；`markArea` 标注最大回撤区间（前高→后低，红 12%/16% 淡底，区间靠右时标签改 `insideTopRight` 防裁切）、`markPoint` 标注净值峰值、`markLine` 标注初始本金；网格线只留水平虚线
- 买卖点标记必须**先按「日期 + 方向」聚合，再按可视窗口的像素密度稀释**：同一天多个板块只落一个点（明细看 tooltip），相邻标记最小横向间距移动端 20px、桌面 14px，窗口两端各强制保留一个标记；稀释由 `@datazoom` 事件（160ms 节流）驱动，放大后自动按新窗口重算。禁止逐日直接铺标记——长区间（400+ 交易日）会把标记叠成一条彩带
- 回测进度与结果存 `stores/replayTask.ts`，由 `components/ReplayTaskCard.vue` 在 MainLayout 层渲染：切路由/切页签不销毁，支持收起、关闭与「查看回放详情」跳回；账号登录/登出时清理

#### 7.5.6 分段选择（多选一，`el-radio-group`）

原先 4 处各写一套（height 32/24、padding-y 5/6、line-height 18/22、font-size 11/12），同一控件换页面就变高、文字固定偏上 1-4px。现在**桌面端只允许改 `index.scss`**（`.el-form` 的 M 档 32 / `.card-header` 等的 S 档 24 各一处），**移动端只允许改 `mobile.scss` 一处**，页面不得自建：

| 项 | 令牌 / 写法 | 值 | 约束 |
|---|---|---|---|
| 段高 | `--m-seg-h` | 32 = `--m-tap` | 卡片头、工具栏、正文一律 32，禁止降到 24 |
| 段内边距 | `--m-seg-pad-x` | `0 8` | 只写水平；垂直居中靠 flex，禁止 padding-y / line-height |
| 字号 | `--m-seg-fs` | 12 = `--m-fs-body` | 不再出现 11px |
| 对齐 | `justify-content:center` | 居中 | 不靠 `text-align` 拼 |
| 等分 | 容器加 `class="fill"` | `flex:1 1 0` | 页面不写 width / flex |
| 段间分隔 | `border-left` | 1px | 不写 margin / gap |
| 选中态 | 主色填充 + 白字 | 6.1:1 | 32 高下填充比浅底描边更清楚，主操作再加 600 字重 |

选择器写**三层** `.el-radio-group .el-radio-button .el-radio-button__inner`（0,3,0），否则被 EP 自带 `.el-radio-button--small .el-radio-button__inner`（0,2,0，padding `5px 11px`）反压，"内边距不统一"会复现。桌面与移动端同口径：`inline-flex + align-items:center + justify-content:center + box-sizing:border-box + line-height:1`，**不写 padding-y**；`height + line-height: calc(高度 - 2px)` 会使文字固定下沉（2026-11-25 实测 6.5px），禁止再用。等分容器两端都加 `class="fill"`（`index.scss` 与 `mobile.scss` 各有一份同语义规则），页面不得再写高度/内边距/字号/width。

同理，**卡片头/过滤行在移动端不再降到桌面 S 档 24**：24 高配 6px 内边距 + 22 行高时文字必然偏上（24 − 6×2 − 22 < 0），是"同排按钮文字不对齐"的直接来源。放不下就换行，不靠缩高度腾空间。

#### 7.5.7 scoped 样式与 Element Plus 的踩坑（每条都实测复现过）

| 坑 | 现象 | 正确写法 |
|---|---|---|
| 纯 CSS 的 `<style scoped>`（无 `lang="scss"`）里把 `:deep()` 写进嵌套规则 | 编译成 `.a[data-v] [data-v] .b`（双 data-v 后代），永不命中，规则静默失效 | 该文件所有 `:deep()` 必须写在**顶层**（不能包在 `.a { }` 里）。`StockSense.vue`、`Sense*.vue` 属此类；写 SCSS 的文件由 Sass 先拍平，没有此问题 |
| 对 EP 组件根节点加 class / 期望继承 `data-v` | `.ctrl-daterange { grid-column: 1/-1 }` 完全无效：`el-date-picker` 根节点既**丢了 `data-v`**、也**不接收 class**（`class` 落在内层） | 改用结构选择器 `:deep(.header-actions > .el-date-editor)` |
| `el-radio-group` 在栅格里宽度塌缩 | `inline-flex` + `grid-column: span 3` 未命中时组宽只有内容宽（53px），"按天/按周""慢/中/快" 被挤成竖排 | 组必须显式 `grid-column: span N` + `display: flex` + 子项 `flex: 1 1 0` |
| 用 flex 换行做多行等宽按钮 | 每行 `flex: 1 1 auto` 的伸缩基数不同，行宽不等，第一行整体偏移 4px（"两行前后边距不对齐"） | 改 `grid-template-columns: repeat(6, minmax(0,1fr))`，且**逐个写 `grid-area`**（组内有占位元素时 `span` 自动排布会把首行顶到第 2 列） |
| `el-slider` 的 `show-input` | `.el-slider__input` 本身就是 `.el-input-number`，被移动层的 `width:100% !important` 拉满 → 轨道被挤成 0（"滑块看不见"），再加 12px 外边距 → 溢出屏幕 | 轨道 `flex:1 1 auto; min-width:0`，输入框单独 `flex: 0 0 72px` |
| 带单位的单行控件（`天`、`每交易日`） | `.el-form-item__content` 是 `flex-wrap: wrap`，控件 `width:100%` 后单位被挤到下一行 | 模板包一层 `div.ctrl-unit`（`display:flex; flex-wrap:nowrap`），控件 `flex: 1 1 0`（flex-basis 0 优先于 `width:100% !important`），单位 `flex: 0 0 auto` |
| `el-button` 放进 grid | EP 的 `.el-button + .el-button { margin-left: 12px }` 保留着，"回填收益"这类行首按钮仍右移 12px | `:deep(.el-button) { margin-left: 0 !important }` |
| 圆形图标按钮 | `.el-button.is-circle` 宽度是 24/32，被移动层的 `height: 32 !important` 拉成椭圆 | `.el-button.is-circle { width: var(--m-tap) !important; padding: 0 !important }` |
| `el-row/el-col` 归零 padding | 卡片之间的 gutter 一并消失，卡片首尾相接；桌面 `el-row` 的 `:gutter` 只给横向间距，窄屏堆叠后纵向就是 0 | 窄屏整行改 `display:grid`（`grid-template-columns:1fr 1fr`）+ `gap: var(--m-gap)`，并归零 `el-col` 的 `padding/width/flex/max-width`，横纵间距才一致（`Settings.vue` 的 `.stat-row`） |
| 原生 `<button>` 当导航项 | UA 默认 `buttonface` 底色 + outset 边框 + 居中样式，5 个标签中它一个像「置灰选中」 | `.bottom-tab { appearance:none; border:0; padding:0; background:none; font-family:inherit }`，选中态只靠 `.active` 类控制 |
| 同一行出现不同规格控件 | `el-tag`（高 20）+ `el-button`（高 32）并排 | 手机端改成纵向两行（tag 整行、按钮整行），不要靠拉伸高度凑齐 |

#### 7.5.8 验证方法（强制）

任何移动端改动完成后，必须：
1. 用 Playwright 以 390×844 视口逐页截图
2. 对照本规则逐条检查字号、间距、图表高度、K线交互
3. 交互测试：打开日期弹层、启动训练、点击下一根，确认无溢出/无错乱
4. 未通过验证的代码不得部署

---

## 八、组件开发规范

### 8.1 轻量卡片区块

```html
<div class="page-card">
  <div class="card-header">
    <span class="card-title">标题</span>
    <!-- 操作区：按钮、选择器等 -->
  </div>
  <!-- 区块内容：图表、列表、表格 -->
</div>
```

**规则**：
1. 页面级区块用 `<div class="page-card">`：白底 + 1px 边框 + 6px 圆角 + 24px 内边距，**无阴影**
2. 区块标题用 `card-header > card-title`（16px/600，带 2px 主色短条），标题下方 1px 分隔线
3. 统计数据统一用 `.stat-grid > .stat-card`（同规格轻量卡片 + 28px 等宽数字），**禁止**彩色图标块
4. 卡片之间统一 24px 间距，**严禁**写 `style="margin-top: 20px"`
5. 嵌套数值项使用 `<el-row :gutter="16">` + `<el-col>` 并设置响应式 span

### 8.2 表格

```html
<!-- 表格必须包裹在 responsive-table 中 -->
<div v-if="data.length > 0" class="responsive-table">
  <el-table :data="data" stripe size="small">
    <!-- 移动端隐藏次要列 -->
    <el-table-column :class="bp.isMobile.value ? 'hide-mobile' : ''" ... />
  </el-table>
</div>
<el-empty v-else description="暂无数据" />
```

**规则**：
1. **每个 `el-table` 必须包裹**在 `<div class="responsive-table">` 中——无例外
2. `.responsive-table` 已全局设置 `.responsive-table .el-table { min-width: 100% }`：表格宽度始终跟容器走，列按 `min-width` 比例铺满；列宽合计超容器时 EP 自动加 `.el-table--scrollable-x`，由内部 `el-scrollbar` 横滑，不会丢列。**禁止使用 `min-width: max-content`**：表格宽由内容反推、EP 又把容器余量分给 `min-width` 列，两者递归，实测把备注列算成 27743px、整表 28163px，右边框跑到屏外，整表看着"白底无边界"。页面不要再给表格写固定 `width` 或自行加 `overflow`
3. 分页使用 `class="pagination-bar"`（移动端居中）
4. 移动端列数超过 4-5 列时，次要列用 `:class="bp.isMobile.value ? 'hide-mobile' : ''"` 隐藏
5. **`v-if`/`v-else` 链**：将 `v-if` 放在 wrapper div 上，不要放在 `<el-table>` 上。`<div v-if>` 和 `<el-empty v-else>` 必须是直接兄弟元素
6. 手机端（≤480px）优先按 7.5.5 改为条目列表（`v-if="isMobile"`），表格只作为桌面端分支保留
7. **配色由全局统一**（`index.scss` 的 `div.el-table`，勿在页面里再写）：EP 的斑马纹取 `--el-fill-color-lighter`、行线取 `--el-table-border-color`，两者全局映射到 `--bg-subtle`（等于卡片内嵌套区块底色 `--bg-tertiary`），表头又取 `--el-fill-color-blank`（白，等于白卡片）——表格放进任何容器都会「融进背景」。全局已统一为：表头带与斑马纹 `--bg-hover`、行线/表头底线 `--border-primary`。必须带元素名 `div.el-table`：EP 自己的 `.el-table` 同样声明这些变量，同特异性按加载顺序取胜，裸类名压不住
8. **列宽必须铺满**：至少一列不写 `width`（优先给 `min-width="200"`），EP 按各列 `min-width` 比例分配剩余宽度；全部列写死 `width` 且合计小于容器时，表格右侧会留一块没有任何列线/表头的空白，与卡片底色连成一片。其余列的 `width` 只能取 15 号 5.1 的档位值（48/64/80/96/110/120/140/160/180/200/260/400），不允许自由值
9. 表格放在**有底色的容器**里（如 `--bg-tertiary` 分组卡）时，再给表格补 `1px solid var(--border-primary)` 轮廓 + `border-radius`；`--border-subtle` 与这类容器底色同值，画了看不见

10. **视觉、字体、对齐、行列布局、响应式、状态、校验清单的完整定义见
    [15 · 表格设计规范](15-table-spec.md)**。本节只保留结构约束；两处冲突时以 15 号为准。新增表格直接套 15 号第 8 节模板，不再逐页调样式。

11. **表格放进 grid 布局时，grid 项必须写 `min-width: 0`**（`display:grid` 容器的直接子元素）。grid 项默认 `min-width: auto`，下界取内容 min-content；而表格**空态**（新账号还没有信号）时 EP 会给 `.el-table__empty-block` 写内联 `width`=当前表格宽，配上第 2 条的 `.el-table{min-width:100%}`，表格宽与轨道宽互为输入，每次 ResizeObserver 回调都放大一次——实测复盘页「板块表现」空表 8 秒内从 10725px 涨到 19827px，横向滚动条无限延伸，看着像"表格一直变长"。有数据时 `empty-block` 不渲染，所以只有空数据的账号能复现。`:class`/`:style` 都不管用，必须落在 CSS 的 grid 项上（如 `views/Review.vue` 的 `.detail-block`）。

### 8.3 表单

```html
<!-- inline 表单会自动响应式换行/堆叠，无需额外处理 -->
<el-form :inline="true">
  <el-form-item label="标签">
    <el-select class="my-select" ... />
  </el-form-item>
</el-form>
```

```scss
// 控件宽度：用 CSS 类 + max-width 约束
.my-select { width: 160px; max-width: 100%; }
```

**规则**：
1. 谨慎使用 `:inline="true"`——全局样式会自动处理换行和堆叠，**不要在 scoped 样式中覆盖 inline 表单行为**
2. 表单控件**禁止固定宽度**——使用 CSS 类设置 `width` + `max-width: 100%`
3. ≤480px 全局样式会自动将表单控件设为 100% 宽度
4. 表单标签**一律左对齐**（全局已强制），不要再用 `label-position="right"` 或 `text-align` 改回去
5. 表单内控件统一 M 档 32px（≤480px 同为 32px，不再单独抬高一档），见 8.7；不要在表单里混用 `size="small"`
6. 带单位的数值项写成 `<span class="unit">‰ (千分之)</span>`，单位与控件同一行，禁止用 `margin-left` 内联样式定位

### 8.4 ECharts 图表

```html
<v-chart :option="chartOption" class="my-chart" autoresize />
```

```scss
// 图表高度通过 CSS 类 + 媒体查询控制，不用内联 style
// 只允许三档：200 / 260 / 320（对应 --chart-h-sm/md/lg）
.my-chart { height: var(--chart-h-md); }
@media (max-width: 480px) { .my-chart { height: var(--chart-h-sm); } }
```

**规则**：
1. 图表高度**禁止**使用内联 `style="height: 350px"`——使用 CSS 类 + 媒体查询
2. X 轴标签必须使用 `bp.labelInterval(dataLength)` 计算间隔
3. 移动端旋转标签 90°：`axisLabel: { rotate: bp.isMobile.value ? 90 : 45 }`
4. 移动端减少可见数据点（如热力图显示 Top 8 板块而非 12）
5. 始终使用 `autoresize` 属性
6. 图表配置中需适配暗色模式：读取 `themeStore.mode` 设置坐标轴/分割线颜色
7. **坐标轴名称（yAxis.name）防裁切**：默认 `nameLocation: 'end'` 会把名称画在轴顶端，需保证 `grid.top ≥ 40`（有 `nameGap` 或加粗字体时更大）；xAxis 名称同理需保证 `grid.bottom` 充足。多个轴名与 `legend` 同处顶部时，间距要能同时容纳两者。改动轴名或 grid 后必须切到亮/暗两套主题目测确认名称完整可见
8. **tooltip 不出图、手机端能触发**：`tooltip.confine: true` 必填（否则贴边的格子会把提示框甩到屏幕外）；≤480px 用 `triggerOn: 'click'`（手指没有 hover 状态）、`textStyle.fontSize: 11`、`extraCssText: 'max-width:220px;white-space:normal;line-height:1.5;'`。参考 `Dashboard.vue` 的热力图与信号日历
9. **`confine` 只保证不出容器，容器本身可能被视口裁掉**：iframe 式布局（MainLayout 固定视口、内容区内部滚动）里图表底部常低于视口下沿，此时 `confine: true` 仍会让提示框压到屏幕外（DataReplay 按日期回放 390×844 实测越界 22px）。需要 `tooltip.position` 回调里按「容器可见区 ∩ 视口」夹取：先放指针右侧/下方，放不下再翻左/翻上，最后 `Math.min(Math.max(...))` 夹进矩形。参考 `DataReplay.vue` 的 `clampTooltipPosition`

### 8.5 图表数据取数（禁止前端串行 N 次请求）

图表需要"多日 / 多板块"的聚合数据时，**不要**在前端 `for` 循环里逐个 `await` 明细接口：

```js
// 反例：Dashboard 热力图原来这么写，5/10/20 日 = 5/7/15 个串行请求，1.3~3.3 秒
const dates = await settingsApi.getReplayDates(start, end)
for (const date of dates) { const day = await settingsApi.getReplayDayData(date); /* 累加 */ }
```

正确做法是后端提供区间聚合接口，一次返回图表直接可用的数组：

```js
// Dashboard 热力图：一次请求，服务端按板块聚合，5 日 0.28s / 20 日 0.40s
const { sectors } = await settingsApi.getReplayHeatmap(parseInt(heatmapPeriod.value))
```

- 聚合口径（平均 / 求和、缺失值按 0）必须写在后端并有注释，前端只负责渲染
- 返回字段直接对齐图表入参（如热力图的 `sector_name / main_net_inflow / index_change_pct`），不要再让前端二次 map
- 排序也在后端完成，前端不要为了排序再排一遍（顺序不同会导致图表标签与数据错位）

### 8.6 对话框

```html
<!-- 宽度只用三档：460（表单）/ 640（详情）/ 780（宽表格） -->
<el-dialog width="640px" ... />
```

```scss
// 移动端不用逐页写覆盖：全局已限制 .el-dialog { max-width: calc(100vw - 24px) }
// 需要特殊处理时按 .my-dialog 作用域写，不要改全局
```

### 8.7 导航与布局

- **桌面端 (>768px)**：默认 200px 带文字侧栏 `.sidebar`，11 项按「工作台 / 策略与交易 / 复盘与分析 / 系统」分组；点击 logo 或折叠按钮收起为 60px 图标轨，图标带 `title`；无独立 header，标题与操作在 `.page-context` 上下文行
- **平板/手机 (≤768px)**：侧栏隐藏，改用 56px 底部标签栏 `.bottom-tabs`（5 个主入口 + 「更多」抽屉含全部 11 项），适配 `safe-area-inset-bottom`
- **AI 面板**：`.ai-sidebar` 桌面 640px 从右滑入 + 遮罩，移动端 100vw 全屏；Esc 关闭，焦点归还触发按钮

**图标注册约定**：`allNavItems` 的 `icon` 是图标名字符串，模板用 `<component :is="item.icon" />` 动态渲染，因此**新增菜单项时必须同步在 `main.ts` 的 `icons` 对象中注册同名图标**，否则该菜单项图标渲染为空且不报错。

---

### 8.8 控件尺寸与对齐规格（硬约束）

所有可交互控件的尺寸/字号/间距只取下表的值。**同一区域只能出现一档高度**——24px 按钮挨着 32px 下拉、22px 单选挨着 24px 下拉，就是"有的长有的短"的来源。

| 档位 | 高度 | 字号 | 适用范围 |
|---|---|---|---|
| M | 32px `--ctrl-h-md` | 12px `--ctrl-fs-md` | 卡片正文表单控件、弹框表单与底部按钮 |
| S | 24px `--ctrl-h-sm` | 11px `--ctrl-fs-sm` | `.card-header`、`.context-actions`、`.filter-row`、表格行内 |
| 触控 | 32px `--m-tap` | 12px `--m-fs-body` | ≤480px 的全部可点区域：正文表单、弹框按钮、卡片头、过滤行、分段选择（不再降到 S 档 24，见 7.5.6） |

已在 `styles/index.scss` + `styles/mobile.scss` 全局强制，**页面里不要再写死高度**：

1. 表单标签左对齐：`.el-form .el-form-item .el-form-item__label`；EP 默认右对齐被覆盖，不要用 `label-position` 改回
2. 表单内控件统一 M 档（≤480 同为 32px）：EP 按钮/下拉高度是字面值，全局已按档位重设，页面照常用 `size` 或无 `size`
3. 卡片头/过滤行整排同高：桌面 S 档 24，移动端统一 32（含表单、按钮、下拉、单选按钮，见 7.5.6）
4. 同排控件 `align-items: center` + `gap: var(--ctrl-row-gap) var(--ctrl-gap)`（行/列都是 8px），禁止用 `margin-left/right` 造间距；换行行为见 8.7.1
5. 单位后缀统一 `<span class="unit">`，与控件同行；移动端控件 `flex: 1 1 auto`，单位 `flex: 0 0 auto`
6. 弹框宽度只有 460 / 640 / 780 三档；移动端上限 `calc(100vw - 24px)`
7. 页面级图表高度只有 200 / 260 / 320 三档（`--chart-h-sm/md/lg`），tooltip 规则见 8.4-8。已落地：Dashboard 热力图 320→260、信号日历桌面 320 / ≤768 260 / ≤480 280（七天月历需容纳 6 行格子与状态字；280 为例外）；Strategy 回测 320→260→200；Review 260→200；Fund `nav-chart` 260 / `calendar-chart` 桌面 320、≤768 与 ≤480 280（例外）；FactorRanking 320→260→200；DataReplay 两图桌面 320、≤768 统一 260
8. 例外（写死不算违规，但同类必须同高）：
   - K 线类 `.kline-chart` / `.replay .kline-chart` / 回放叠加图承载 OHLC + 副图 + dataZoom，按 §7.5.4 自定：桌面 520 / 420，≤768 320 / 280
   - 嵌入式迷你图 `.magnifier-chart`(180) / `.future-chart`(130) 随宿主浮层，不参与三档
   - Fund 页等高行内的 `.fill-chart`：桌面 `flex: 1` 由卡片行剩余空间决定（实测 202/347），≤768 单列后固定 `--chart-h-sm`

**验证方法**：390 / 768 / 1440 三档宽度各量一次，每个区域收集控件高度集合，`Set` 里只能有 1 个值；标签 `text-align` 只能是 `left`；页面级图表高度只能落在 200 / 260 / 320；再从 1440 逐档拖到 390，每档按 8.7.1 复检换行。

### 8.8.1 响应式换行间距（换行不换档）

宽度变窄让控件下移到下一行时，只有两种失败方式：**行首多出缩进**、**行间缺少间距**。

| 规则 | 要求 |
|---|---|
| 间距来源 | 只能用容器 `gap`；禁止子项 `margin-left/right/bottom` 造间距 |
| 行列双写 | `gap: var(--ctrl-row-gap) var(--ctrl-gap)`；只写 `column-gap` 会让换行后行间为 0 |
| 行首 | `gap` 不作用于行首，天然零缩进；`:not(:first-child){margin-left}` 换行后在行首留下缩进 |
| inline 表单 | `.el-form.el-form--inline` 已统一 `gap: 8px 8px` + `> .el-form-item { margin: 0 }`，页面不得再写 margin；≤480 单列堆叠同样由 gap 给行距（不得同时写 `margin-bottom`，否则叠加成 16px） |
| 纵向堆叠 | 移动端容器 `gap` / `margin-bottom: var(--ctrl-row-gap)`（8px）；桌面沿用 EP 的 18px。同一表单内只能有一个值，禁止 9/10/12px 随手值 |
| 可压缩 | 控件 `min-width: 0`，单位后缀 `flex: 0 0 auto`，换行点才可预测 |
| 例外 | `.context-actions` 在移动端允许 `nowrap` + 横向滚动，此时不得再叠加 `gap` 与 `margin` 两套间距 |

实测结果（`/strategy` `/fund` `/signals`，1440/900/700/560/390 五档）：行首偏移 0、行间距 8px、`gap` 恒为 `8px/8px`。

可视基准：仓库根目录 `design-preview.html`（v7，16 节）——01 令牌与硬约束、02 颜色（含 WCAG 对比度实测）、03 字体排版、04 间距节奏、05 圆角边框阴影动效、06 桌面控件档位、07 移动端规范（触控 32 = `--m-tap`，与桌面同档，主次靠字重与颜色 / 分段选择唯一规格 / 令牌速查）、08 控件组合（含混档错误示范）、09 表单、10 表格、11 断点与四张可拖拽换行实测卡、12 图表与弹框、13 导航外壳、14 可访问性、15 页面骨架、16 自动读数。

第 16 节用 `getComputedStyle` 回读本页真实渲染并给出判定：控件三档高度集合、图表三档、换行行首缩进/行距/margin、颜色对比度、横向溢出。改令牌后先看这里，读数变红说明规范与实现已经不一致。

已知临界项（待确认，未改令牌）：`--accent-danger` (#D92D20) 压在 `--accent-danger-light` (#FEF3F2) 上仅 **4.4:1**，低于 4.5；它正是 `.el-tag--danger` 的文字色。两种解法任选其一——徽标文字加粗到 600（大字 3:1 达标），或把该场景文字色换成 #B42318（6.0:1）；`--accent-success` / `--accent-warning` 的同款组合分别为 4.7 / 5.2，达标。

## 九、页面实现参考

### Dashboard (`views/Dashboard.vue`)

- KPI：轻量卡片 4 列等宽数字，≤1024px 变 2 列，≤480px 变 1 列
- 热力图 + 信号列表：`1.4fr 1fr` → ≤1024px 单列
- 热力图：移动端显示 Top 8 板块（桌面 12）
- 日历热力图：七天横向月历，高度 320px（桌面）→ 260/280px（平板）→ 280px（手机），格子内两行文字需要比旧周视图更高

### Strategy (`views/Strategy.vue`)

- 策略卡片 (3× `:span="8"`)：响应式 `:xs="24" :md="12" :lg="8"`
- 回测表单：inline 表单自动换行
- 回测图表：高度 350px → 280px (平板) → 220px (手机)
- 回测曲线纵轴：金额简写 `axisMoney()`（≥1 万 `w`、≥1 千 `k`，2 位小数去尾 0；百万级只占 5-6 字符），配合 `grid.containLabel: true` 才不会被卡片左边裁掉；`grid.right` 取 34（≈ 半个 `2025-12-19` 标签宽），否则末位日期被右边缘裁掉
- 指标卡片 (4× `:span="6"`)：响应式 `:xs="12" :sm="6"`；≤480 全局把 `.el-col` padding 归零后这 4 张卡会横向贴死，需用 `.backtest-result :deep(.el-col) { padding: 0 4px !important }`（配 `-4px` 负 margin）单独补回 8px 缝
- 回测状态续接：切路由会卸载本组件（`MainLayout` 无 keep-alive），进行中的任务在后端继续跑；`taskId`/`btId` 存 `sessionStorage['strategy.backtestSession']`，重新进入时探测任务状态，未完成则恢复进度卡并继续轮询，已完成则按 `btId` 重新拉结果回填（恢复时不滚动），404 则清除记录
- 页面顺序：策略回测（指标 + 曲线）→ 回测历史 → 调仓明细。调仓明细内容长，单独作为 `page-card` 放在回测历史之后，不再嵌在 `.backtest-result` 内
- 调仓明细按调仓日倒序（`rebalanceGroups` 用 `localeCompare` 降序），最近的调仓在最前，不必滚动到卡片底部找最新一天
- 调仓明细：`.rebalance-group` 内的持仓快照 ≤480 用 `.m-pf-list` 条目（板块 + 仓位一行，金额/当日涨跌/贡献三宫格），桌面仍走 `el-table`；格子底色用 `--bg-surface`（分组本身已是 `bg-tertiary`）
- 调仓明细表格配色见 8.2 第 7-9 条（全局 `div.el-table` 统一表头/条纹/行线，容器有底色时补 `--border-primary` 轮廓）；持仓快照 5 列全用 `min-width`，否则列宽合计 470px 会在 900px 宽的表格里留出右半边空白

### Review (`views/Review.vue`)

- 头部控制区：策略档位（`strategyStore.currentStrategy`，与全站共享）、持有期（1/3/5/10 交易日）、日期范围、查询、回填收益
- 指标卡：使用全局 `.stat-grid`（4 列 → 2 列 → 1 列），窄屏自动折行，轻量卡片边界
- 图表与明细：累计净收益曲线 + 月度命中率、方向拆分 + 板块表现，两列 `1fr 1fr` → ≤900px 单列
- 图表高度：`class="review-chart"`（280px），禁止内联 `style`（见 8.4）
- 切换策略档位/持有期自动重新拉取 `/signals/performance`；`backfillSignalOutcomes()` 用于手动触发结算回填
- 页头标注成交口径（T+1 开盘价买入、第 N 个交易日收盘价结算）与实际往返成本率
  （`cost_rate`，取自策略配置），避免把毛收益误读为可落袋收益
- 当所选持有期尚未走完（`evaluated_count === 0` 且 `pending_count > 0`）时，页头显示黄色提示，说明待评估原因并引导切换持有期查看已有数据
- 指标口径见 `docs/05-strategy-engine.md` 5.13：命中率即方向判定正确率，与平均净收益在符号上自洽

### DataReplay (`views/DataReplay.vue`)

- 回放控件：移动端纵向堆叠，分隔线隐藏
- 日期范围选择器 `.control-date-range`：260px + max-width: 100%
- 状态卡片所有 `el-col` 需设置 `:xs="12" :sm="6"` 响应式 span
- 板块行情 / 板块历史两张表（除固定在左的板块/日期列）与策略叠加的持仓快照表全部用 `min-width`：原来写死 `width` 合计 710px / 470px，在 900+ 宽的表体里右侧留大片空白，见 8.2 第 8 条
- 策略叠加的 `.rebalance-group` 无底色，白色表体与白卡片同色，需 `:deep(.el-table)` 补 `1px solid var(--border-primary)` 轮廓
- 板块历史表（`sectorHistoryRows`）按日期倒序展示，最新交易日在最前；K 线与资金流图仍用 `sectorHistory` 原始升序，避免图表时间轴逆序

### Fund (`views/Fund.vue`)

- 概览卡片：已使用 `:xs="12" :sm="12" :md="4" :lg="4"`
- 移动端卡片内边距和字号缩小

### 后台管理 (`views/admin/*`)

三张页面共用「单个 `page-card` + 卡片头操作区」的结构，不嵌套卡片；仅管理员可见。

- `AccountAdmin.vue`（账号管理）：卡片头为关键字搜索 + 角色筛选 + 新建；桌面走 `el-table`（用户名/邮箱/角色/状态/创建时间/操作），
  ≤480 改为 `.m-user-list` 条目（名称 + 角色标签、邮箱与状态说明、操作按钮一行）；分页用 `.pagination-bar` 右对齐（≤480 居中）；
  新建/编辑共用一个 `el-dialog`（width 460），编辑时用户名禁用、密码留空表示不修改
- `RoutePermission.vue`（页面权限）：角色用 `el-radio-button` 切换，页面按后端 `group` 分组，桌面两列网格（`repeat(2, minmax(0,1fr))`）、
  ≤768 单列；每行是「页面名 + 路径（等宽字体）+ 开关」，`lockedPaths`（后台管理三项）对所有角色都禁用且不可勾选：
  管理员显示为开启，普通账号显示为关闭并带「仅管理员」标签
- `FeatureQuota.vue`（高级功能）：每个功能一块 `.feature-block`（浅边框，非嵌套卡片），每块内按角色一行：
  角色名 + `el-input-number`（0 = 不限次）+ 开关，改动后按功能卡单独保存；≤480 行内改为纵向堆叠

三个页面的 `.card-header` 都补了 `flex-wrap: wrap`，保证操作区在窄屏换行而不是压缩输入框。

---

## 十、验证清单

每次前端改动后，在以下断点测试：

| 宽度 | 模拟设备 | 检查项 |
|------|---------|--------|
| 375px | iPhone SE | 无水平溢出、底部标签栏可切换、AI 面板全屏、表格可滚动、表单纵向堆叠、图表自适应 |
| 768px | iPad | 同上 + 底部标签栏替代图标轨 |
| 1280px | 笔记本 | 正常桌面布局（60px 图标轨 + 轻量卡片边界） |
| 1920px | 全高清 | 正常桌面布局 |

**检查要点**：
- 无水平溢出（页面不需要左右滚动）
- 表格可以水平滚动或列已隐藏
- 表单控件纵向堆叠，不超出屏幕
- 桌面图标轨 tooltip/aria-label 齐全，选中态正确；移动端底部标签栏 5 个入口 + 更多抽屉可开关
- AI 面板桌面 640px / 移动全屏，Esc 可关闭、焦点归还
- 图标焦点环可见，`prefers-reduced-motion` 下动效关闭
- 图表高度和标签密度适合屏幕宽度
- 弹窗宽度 ≤ 屏幕 90%
- 亮色/暗色主题均正常
