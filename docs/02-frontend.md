# 前端规范文档

> 版本: v2.0 | 更新日期: 2026-05-13

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
│   └── MainLayout.vue      # 主布局（侧边栏 + 头部 + 内容区）
├── router/                 # 路由配置
│   └── index.ts            # 路由定义 + 守卫
├── stores/                 # Pinia 状态管理
│   ├── user.ts             # 用户状态（Token / 登录登出）
│   ├── signal.ts           # 信号状态（WebSocket / 信号列表）
│   └── theme.ts            # 主题状态（亮色 / 暗色切换）
├── styles/                 # 全局样式
│   └── index.scss          # 设计 Token + 布局 + 组件样式 + 响应式规则
├── views/                  # 页面组件 (10个)
│   ├── Login.vue           # 登录 / 注册
│   ├── Dashboard.vue       # 仪表盘
│   ├── Strategy.vue        # 策略管理 + 回测
│   ├── Signals.vue         # 交易信号
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
  ├── /strategy         # 策略管理 (Strategy)
  ├── /signals          # 交易信号 (Signals)
  ├── /fund             # 资金管理 (Fund)
  ├── /monitor          # 系统监控 (Monitor)
  ├── /data-replay      # 数据回放 (DataReplay)
  ├── /factor-analysis  # 板块因子分析 (FactorAnalysis)
  ├── /factor-ranking   # 板块因子排名 (FactorRanking)
  └── /settings         # 系统设置 (Settings)
```

### 路由守卫

- `beforeEach`: 检查 `localStorage` 中的 Token
- 无 Token → 重定向至 `/login`
- 有 Token → 放行（Token 有效性由后端校验）

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
| signal | `api/signal.ts` | getTodaySignals, getSignalHistory, getSignalCalendar |
| strategy | `api/strategy.ts` | getConfigs, updateConfig, runBacktest, analyzeFactorsBatch |
| fund | `api/fund.ts` | getPositions, getNavCurve, getReturnAttribution, getAccountSummary |

---

## 五、状态管理

### 5.1 userStore

```
状态:
  token: string          - JWT Token
  userInfo: UserInfo     - 用户信息
  isLoggedIn: boolean    - 登录状态

动作:
  login(params)          - 登录（调用 API + 存 Token）
  checkAuth()            - 检查认证（获取用户信息）
  logout()               - 登出（清除 Token + 状态）
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

---

## 六、设计系统 (Design System)

所有设计 Token 定义在 `frontend/src/styles/index.scss`，使用 CSS 自定义属性。**严禁在组件样式中硬编码颜色、间距或阴影**，必须使用 `var(--xxx)` 引用。

### 6.1 色彩系统

| 类别 | 变量前缀 | 说明 |
|------|---------|------|
| 背景 | `--bg-*` | primary(页面), secondary(卡片), tertiary(次级), elevated(弹出层), sidebar(侧边栏) |
| 文本 | `--text-*` | primary, secondary, tertiary, inverse, sidebar, sidebar-active |
| 边框 | `--border-*` | primary, secondary, subtle |
| 主题色 | `--accent-*` | primary(主色), success(成功/卖出), danger(危险/买入), warning(警告) |
| 阴影 | `--shadow-*` | sm, card, modal, sidebar |
| 圆角 | `--radius-*` | sm(6px), md(10px), lg(14px) |
| 字体 | `--font-*` | sans(中文正文), mono(数字/数据) |

### 6.2 暗色主题

暗色主题通过 `html.dark` 选择器自动切换所有 CSS 变量。**严禁在组件中写单独的暗色模式样式**——只需使用 `var(--xxx)`，主题切换自动生效。

主题切换时，`html` 元素会短暂添加 `theme-switching` 类来抑制所有过渡动画，防止闪烁。

### 6.3 Element Plus 变量映射

`index.scss` 中将 Element Plus 的 CSS 变量映射到设计系统变量（如 `--el-color-primary: var(--accent-primary)`），确保 Element Plus 组件自动跟随主题。

### 6.4 信号方向颜色约定

- **买入 (BUY)**: 红色 `var(--accent-danger)` （A股红色为涨）
- **卖出 (SELL)**: 绿色 `var(--accent-success)` （A股绿色为跌）

CSS 工具类：`.signal-buy` / `.signal-sell`

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
| `.page-section` | 卡片区块之间的统一间距（16px，移动端自动缩小） |
| `.page-card` | 标准卡片容器，自带 `margin-bottom: 16px` |
| `.hide-mobile` | ≤480px 隐藏 |
| `.hide-tablet` | ≤768px 隐藏 |

### 7.3 全局自动响应式行为

以下行为由 `index.scss` 中的媒体查询自动处理，**组件中无需额外编写**：

- **`el-form--inline`**：≤768px 换行，≤480px 完全堆叠（纵向排列）
- **`el-date-editor--daterange`**：≤480px 宽度 100%，内部两个输入各占 40%
- **`.el-date-range-picker` 弹出层**：≤480px 两个日历面板纵向堆叠
- **`.page-card .card-header`**：≤480px 标题和操作区纵向堆叠
- **`.sidebar`**：≤768px 固定浮层模式，≤480px 全宽
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

---

## 八、组件开发规范

### 8.1 卡片布局

```html
<!-- 标准页面卡片 -->
<div class="page-card">
  <div class="card-header">
    <span class="card-title">标题</span>
    <!-- 操作区：按钮、选择器等 -->
  </div>
  <!-- 卡片内容 -->
</div>

<!-- 与上一卡片有间距时 -->
<div class="page-card page-section">
  ...
</div>
```

**规则**：
1. 页面级卡片一律使用 `<div class="page-card">`
2. 卡片之间需要间距时加 `class="page-section"`，**严禁**写 `style="margin-top: 20px"`
3. 卡片标题使用 `card-header > card-title` 结构，标题自动带左侧强调色条
4. 嵌套的统计数据项使用 `<el-row :gutter="16">` + `<el-col>` 并设置响应式 span

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
2. 分页使用 `class="pagination-bar"`（移动端居中）
3. 移动端列数超过 4-5 列时，次要列用 `:class="bp.isMobile.value ? 'hide-mobile' : ''"` 隐藏
4. **`v-if`/`v-else` 链**：将 `v-if` 放在 wrapper div 上，不要放在 `<el-table>` 上。`<div v-if>` 和 `<el-empty v-else>` 必须是直接兄弟元素

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

### 8.4 ECharts 图表

```html
<v-chart :option="chartOption" style="height: 350px" autoresize />
```

```scss
// 图表高度通过 CSS 类 + 媒体查询控制，不用内联 style
.my-chart { height: 350px; }
@media (max-width: 768px) { .my-chart { height: 280px; } }
@media (max-width: 480px) { .my-chart { height: 220px; } }
```

**规则**：
1. 图表高度**禁止**使用内联 `style="height: 350px"`——使用 CSS 类 + 媒体查询
2. X 轴标签必须使用 `bp.labelInterval(dataLength)` 计算间隔
3. 移动端旋转标签 90°：`axisLabel: { rotate: bp.isMobile.value ? 90 : 45 }`
4. 移动端减少可见数据点（如热力图显示 Top 8 板块而非 12）
5. 始终使用 `autoresize` 属性
6. 图表配置中需适配暗色模式：读取 `themeStore.mode` 设置坐标轴/分割线颜色

### 8.5 对话框

```html
<el-dialog width="600px" ... />
```

```scss
// 移动端响应式宽度
@media (max-width: 480px) {
  :deep(.el-dialog) { width: 90% !important; }
}
```

### 8.6 侧边栏 / 布局

- **桌面端 (>768px)**：侧边栏 220px 固定宽度。关闭按钮 `.sidebar-close-btn` 隐藏
- **平板 (≤768px)**：侧边栏变为浮层（`position: fixed, z-index: 100`），从左侧滑入。汉堡菜单按钮出现，关闭按钮可见，背景遮罩带模糊
- **移动端 (≤480px)**：侧边栏全宽浮层

侧边栏关闭方式（移动端）：
1. 点击侧边栏内部关闭按钮
2. 点击背景遮罩
3. 路由跳转自动关闭

---

## 九、页面实现参考

### Dashboard (`views/Dashboard.vue`)

- 统计卡片：4列网格，≤1024px 变2列，≤480px 变1列
- 热力图 + 信号列表：`1.4fr 1fr` → ≤1024px 单列
- 热力图：移动端显示 Top 8 板块（桌面 12）
- 日历热力图：高度 240px → 200px (平板) → 180px (手机)

### Strategy (`views/Strategy.vue`)

- 策略卡片 (3× `:span="8"`)：响应式 `:xs="24" :md="12" :lg="8"`
- 回测表单：inline 表单自动换行
- 回测图表：高度 350px → 280px (平板) → 220px (手机)
- 指标卡片 (4× `:span="6"`)：响应式 `:xs="12" :sm="6"`

### DataReplay (`views/DataReplay.vue`)

- 回放控件：移动端纵向堆叠，分隔线隐藏
- 日期范围选择器 `.control-date-range`：260px + max-width: 100%
- 状态卡片所有 `el-col` 需设置 `:xs="12" :sm="6"` 响应式 span

### Fund (`views/Fund.vue`)

- 概览卡片：已使用 `:xs="12" :sm="12" :md="4" :lg="4"`
- 移动端卡片内边距和字号缩小

---

## 十、验证清单

每次前端改动后，在以下断点测试：

| 宽度 | 模拟设备 | 检查项 |
|------|---------|--------|
| 375px | iPhone SE | 无水平溢出、表格可滚动、表单纵向堆叠、侧边栏浮层可关闭、图表自适应、对话框不超出屏幕 |
| 768px | iPad | 同上 + inline 表单开始换行 |
| 1280px | 笔记本 | 正常桌面布局 |
| 1920px | 全高清 | 正常桌面布局 |

**检查要点**：
- 无水平溢出（页面不需要左右滚动）
- 表格可以水平滚动或列已隐藏
- 表单控件纵向堆叠，不超出屏幕
- 侧边栏浮层模式正常，可关闭
- 图表高度和标签密度适合屏幕宽度
- 对话框宽度 ≤ 屏幕 90%
- 亮色/暗色主题均正常
