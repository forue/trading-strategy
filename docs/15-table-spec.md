# 15 · 表格设计规范

> 版本 v1.1（2026-11-22，全站 19 张表 / 124 列已按本规范改造并通过实测验收，记录见第十一节）
> 全局实现：`frontend/src/styles/index.scss` → `div.el-table` 段（唯一入口）
> 适用范围：全站所有 `el-table`（19 张表 / 124 列，含弹窗内表格）
> 本规范一经确定，**新增表格只允许套模板，不允许逐页调样式**

---

## 一、总原则

1. **视觉只由全局决定**。颜色、字号、行高、内边距、外框、圆角一律来自 `div.el-table` 全局段，页面禁止覆盖。
2. **页面只声明三件事**：外层 `responsive-table` 包裹、列定义（宽度档位 + 对齐）、数据与空/载状态。
3. **不符合规范不是"风格差异"，是缺陷**。评审时按第 9 节校验清单逐条过。

判定标准：在 `frontend/src` 里搜索 `:deep(.el-table` 必须 0 命中；命中即为违规。

---

## 二、视觉规范

### 2.1 结构分解

```
┌──────────────────────────────────────────── 外框 1px --border-primary，圆角 4px
│ 表头带  --bg-hover，12px/600                     ← 表头底线 1px
├────────────────────────────────────────────
│ 数据行  白底 / 斑马纹交替，行底线 1px
│ 数据行  hover 品牌色淡底
└────────────────────────────────────────────
```

层级（从下到上）：表格底色 → 斑马纹 → hover → 表头带。**四层必须两两可辨**。

### 2.2 色值（实测，非估算）

| 元素 | 变量 | 浅色 | 暗色 |
|---|---|---|---|
| 表格底色 | `--el-fill-color-blank` → `--bg-surface` | `#FFFFFF` | `#17171A` |
| 表头带 | `--table-head-bg` → `--bg-hover` | `#E9E9E6` | `#2A2A30` |
| 表头文字 | `--el-table-header-text-color` → `--text-secondary` | `#52525B` | `#B4B4BB` |
| 正文 | `--el-table-text-color` → `--text-primary` | `#18181B` | `#FAFAFA` |
| 斑马纹 | `--table-stripe-bg` → `--el-fill-color-lighter` | `rgba(0,0,0,.03)` | `rgba(255,255,255,.035)` |
| 行 hover | `--table-hover-bg` → `--el-table-row-hover-bg-color` | `rgba(64,81,224,.06)` | `rgba(95,114,232,.16)` |
| 外框 / 分隔线 | `--el-table-border-color` → `--border-primary` | `#E4E4E1` | `#2A2A30` |
| 圆角 | `--radius-sm` | `4px` | `4px` |

### 2.3 为什么斑马纹和 hover 用半透明

表格会被放进三种父底色里：白卡片 `#FFFFFF`、嵌套分组块 `#F1F1EF`（暗色 `#222226`）、弹窗 `#FFFFFF`。任何**固定色值**至少在其中一种父底色下与背景同值——这是历史上"表格融进背景"的直接原因（表头取白、条纹取 `--bg-subtle` = 嵌套块底色）。

alpha 叠加保证恒定一档差：

| 父底色 | 斑马纹呈现 | 与底色差 |
|---|---|---|
| 白卡片 `#FFFFFF` | `#F7F7F5` | 8/255 |
| 嵌套块 `#F1F1EF` | `#EAEAE8` | 7/255 |
| 暗色卡片 `#17171A` | `#1F1F22` | 8/255 |

### 2.4 禁止项

| 禁止 | 原因 |
|---|---|
| 页面里写 `:deep(.el-table)` 改颜色/字号/内边距/高度 | 与全局段打架，逐页漂移 |
| 给 `el-table` 加 `box-shadow` 或再套一层带边框的卡片 | 与外框形成双重边线 |
| `border` / `border="true"` 开纵向网格线 | 全站只有横向分隔线 |
| 写死 `height` | 用 `max-height`，滚动发生在表体内，表头保持固定 |
| 使用 `size="small"` / `size="large"` 调节密度 | 全局已定死 12px/36px，`size` 只会被压平，不要依赖 |
| 表格内使用 `.el-tag` 超过 2 个/行 | 行高被撑到 59px，破坏 36px 节奏 |

---

## 三、字体规范

| 位置 | 字号 | 字重 | 颜色 | 行高 |
|---|---|---|---|---|
| 表头 | 12px | 600 | `--text-secondary` | 22px（单元格 36 + 分隔线 1） |
| 正文 | 12px | 400 | `--text-primary` | 22px |
| 次要信息（单位、说明、次列） | 12px | 400 | `--text-tertiary` | 22px |

规则：

1. **数字必须等宽**：全局已给 `.cell` 设 `font-variant-numeric: tabular-nums`，同一列小数点上下对齐，刷新数据时列宽不跳动。页面不得再改 `font-family`。
2. **不切等宽字体**：`--font-mono` 只用于代码/密钥类内容。表格数值用 `tabular-nums` 已对齐，切 Mono 会让中文与数字基线错位。
3. **涨跌颜色**走 6.4 的信号方向约定（`.text-up` / `.text-down`），禁止手写红绿色值。
4. **长文本不截字符串**：用 `show-overflow-tooltip`，由 EP 出省略号 + 悬浮全文。
5. 表头全局 `white-space: nowrap`，**禁止表头折行**；放不下就缩短文案或换档位宽度。
6. 单元格默认单行（22px）；确需两行时用副标题模板，仍不得用 `size` 或 padding 造多行。
7. 含 24px 行内按钮（S 档）的行实际高 39px（24 + 7×2 + 1），这是唯一允许超出行距的情形；不要为了压回 37 而缩小按钮。

---

## 四、对齐规范

| 内容类型 | 写法 | 说明 |
|---|---|---|
| 日期、名称、代码、备注 | 不写（默认 `left`） | 文本列唯一合法对齐 |
| 金额、价格、评分、比率、数量、天数 | `align="right"` | 等宽数字 + 右对齐才能小数点对齐 |
| 状态标签、图标 | `align="center"` | 仅限不含文本的组合列 |
| 操作按钮 | `align="right"` | 永远是最后一列 |

规则：

1. **表头自动跟随列对齐**（EP 行为），不需要在表头单独写对齐。
2. 同一张表只允许"文本列左 + 数值列右"两种对齐，禁止出现居中数值列。
3. 空值统一写 `—`（U+2014），保持与列相同的对齐；禁止 `-`、`--`、`null`、`暂无` 混用。
4. 数值列内不写单位（单位进表头，如 `金额(元)`），保证右对齐基线一致。
5. 正数不加 `+`，涨跌类数值保留 `+`/`-` 前缀（与 6.4 一致）。

---

## 五、行列布局规范

### 5.1 列宽档位（只允许取这些值）

| 档位 | 典型用途 |
|---|---|
| 48 | 勾选框、图标 |
| 64 | 方向、状态、短标签 |
| 80 | 评分、仓位、天数、排名 |
| 96 | 日期、百分比、单价、计数 |
| 110 | 板块名 / 标的代码（3-4 字）、日期时间 |
| 120 | 金额（十万级）、组合列 |
| 140 | 名称 + 副标题、大额金额 |
| 160 / 180 / 200 | 长代码、多字段组合、时间戳 |
| 260 | 标签组、迷你图表 |
| 400 | 趋势条、宽图表 |

- **全站已归并（2026-11-22）**：19 张表的列宽属性全部落在上表档位内，`60/70/76/82/86/90/94/95/100/105/106/130/132/150/170/250` 等一次性值已全部删除。新增列只允许取档位值，**不允许再引入新的自由值**。
- 列宽合计 ≤ 容器宽（1440 屏内容区 1109px）时是**标准态**：无滚动条。
- 列宽合计超出容器时 EP 自动加 `--scrollable-x` 内部横滑，可接受，但必须先尝试合并列或降档位。

### 5.2 弹性列（硬性要求）

1. 每张表**至少 1 列**不写 `width`，EP 按各列 `min-width` 比例分配剩余宽度，表格才会铺满。推荐写 `min-width`（200/260）限定最小可读宽度；完全不写宽度也会被撑满，但无法控制下限。
2. 弹性列放在最后一个文本列（备注、说明），不要放在数值列：数值列宽度固定，右对齐基线才稳。
3. 全列 `width` 写死且合计小于容器，是**违规**：右侧会出现一块没有表头、没有列线的空白。

### 5.3 列数预算

| 内容区宽 | 可用列数（12px 字号） |
|---|---|
| 1109px（1440 屏） | 8-10 列 |
| 1589px（1920 屏） | 12-14 列 |
| 501px（800 屏，平板横滑态） | 5-6 列 |

超过预算时按顺序处理：合并同义列 → 移入行详情/抽屉 → 允许内部横滑。**不允许压缩字号或降低行高来塞列**。

### 5.4 列顺序模板

```
标识列（日期/名称） → 核心指标（评分/方向/收益） → 辅助指标（资金/换手） → 操作
```

- 操作列永远最后一列，宽度取 96 / 110 / 120 档，右对齐。
- 状态标签紧跟标识列，同行不超过 2 个。
- 主键类 ID 不展示（用日期 + 名称定位行）。

### 5.5 密度（定死，不可局部调）

| 项 | 值 |
|---|---|
| 表头行高 | 36 + 1px 分隔线（实测 37） |
| 数据行高 | 36 + 1px 分隔线（实测 37） |
| 单元格水平内边距 | 10px |
| 单元格行高 | 22px |
| 表头底线 / 行底线 | 1px `--border-primary` |

### 5.6 最大高度与固定列

- 放在弹窗、卡片固定区内的表格：`max-height="240"` 或 `"320"`，滚动条出现在表体内，表头保持可见（EP 默认表头 sticky）。
- `fixed` 只允许用于：宽表首列（名称）+ 操作列。
- ≤768px 禁止 `fixed`：会与内部横滑叠加，出现两套滚动且固定列错位。

### 5.7 分页

- 行数 > 50 使用分页，容器 `class="pagination-bar"`（移动端居中）。
- 分页在 `responsive-table` 之外，不随表格一起横滑。

---

## 六、响应式规范

### 6.1 断点行为（对齐 02 文档 7.1）

| 断点 | 表格行为 |
|---|---|
| > 1024px | 桌面表格；列宽合计 ≤ 容器时无滚动 |
| 769-1024px | 桌面表格保留；隐藏 `hide-tablet` 列；允许内部横滑 |
| 481-768px | 必须 `responsive-table`；次要列加 `hide-mobile`；允许内部横滑 |
| ≤ 480px | **不渲染表格**，改条目列表（见 02 文档 7.5.5）；桌面表格保留在 `v-else` 分支 |

### 6.2 包裹与宽度（硬性）

```html
<div v-if="rows.length" class="responsive-table"> <el-table ... /> </div>
<el-empty v-else description="暂无数据" />
```

- 每个 `el-table` 必须有 `.responsive-table` 祖先，无例外。
- 全局宽度规则：`.responsive-table .el-table { min-width: 100%; }`
- **禁止 `min-width: max-content`**。表格宽由内容反推，而 EP 又把"容器宽 − 固定列宽"的余量按比例分给 `min-width` 列——两者互相递归，实测把备注列算成 27743px、整表 28163px，右边框跑到屏外 2.8 万像素处，视觉上就是"白底无限延伸、没有边框"。这是 2026-11 表格"无边框"投诉的真实根因之一。

### 6.3 横滑层级

- 外层 `.responsive-table` 与内部 EP `el-scrollbar` 都可能出现滚动条，**优先只保留一层**：列宽合计超容器时先降档位，让合计落回容器内。
- 移动端必须实测 `document.documentElement.scrollWidth === window.innerWidth`（390×844 视口）。

---

## 七、状态规范

| 状态 | 做法 |
|---|---|
| 空数据 | `<el-empty description="暂无数据" />`，与 `.responsive-table` 为 `v-if`/`v-else` 兄弟 |
| 加载中 | `v-loading` 挂在 `el-table` 上；表格已渲染时不要换高度 |
| 接口错误 | 卡片顶部 `el-alert`，**不塞进表格体** |
| 行禁用 | 行加 `.is-disabled` 类（`color: var(--text-tertiary)`），不用 `disabled` 属性 |
| 行可点击 | 加 `class="is-clickable"`（`cursor: pointer`），并在行上 `@row-click` |

---

## 八、标准模板（复制即合规）

```html
<!-- 列表卡片：空态与表格是兄弟节点，表格必包 responsive-table -->
<div class="card">
  <div class="card-header">
    <div class="card-title">银证转账</div>
    <div class="header-actions"><!-- 工具栏 --></div>
  </div>

  <div v-if="transfers.length" class="responsive-table">
    <el-table :data="transfers" stripe>
      <!-- 标识列：固定档位 -->
      <el-table-column prop="transfer_date" label="日期" width="96" />
      <!-- 状态列：固定档位 -->
      <el-table-column prop="direction" label="方向" width="64">
        <template #default="{ row }">
          <el-tag :type="row.direction === 'DEPOSIT' ? 'success' : 'warning'" size="small">
            {{ row.direction === 'DEPOSIT' ? '入金' : '出金' }}
          </el-tag>
        </template>
      </el-table-column>
      <!-- 数值列：固定档位 + 右对齐 -->
      <el-table-column prop="amount" label="金额(元)" width="120" align="right">
        <template #default="{ row }">{{ fmtMoney(row.amount) }}</template>
      </el-table-column>
      <!-- 弹性列：min-width，铺满剩余宽度 -->
      <el-table-column prop="remark" label="备注" min-width="200" show-overflow-tooltip>
        <template #default="{ row }">{{ row.remark || '—' }}</template>
      </el-table-column>
      <!-- 操作列：最后一列，右对齐 -->
      <el-table-column label="操作" width="96" align="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="open(row)">详情</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
  <el-empty v-else description="暂无数据" />
</div>
```

移动端分支（≤480px 必须改条目列表，参见 02 文档 7.5.5）：

```html
<ul v-if="isMobile" class="m-pair-list">
  <li v-for="row in rows" :key="row.id">
    <div class="m-pair-main">{{ row.name }}<span class="val">{{ fmtMoney(row.amount) }}</span></div>
    <div class="m-pair-sub"><span>{{ row.date }}</span><span>{{ row.direction }}</span></div>
  </li>
</ul>
<div v-else class="responsive-table"> <el-table ... /> </div>
```

---

## 九、校验清单（提交前逐条过）

| 编号 | 检查项 | 判定方法 |
|---|---|---|
| T1 | 所有 `el-table` 有 `.responsive-table` 祖先 | 静态扫描：`<el-table` 之前最近的 `responsive-table` 位于最近的 `</div>` 之后 |
| T2 | 每张表 ≥1 列不写 `width`（推荐 `min-width`） | 搜索该文件 `min-width="`，或确认存在无宽度的文本列 |
| T3 | 数值列全部 `align="right"` | 逐列核对 label 与 align；标签/进度条/操作列可居中 |
| T4 | 无页面级表格样式 | `Get-ChildItem frontend/src -Recurse -Include *.vue,*.scss \| Select-String -Pattern ':deep\(\.el-table'` → 0 命中 |
| T5 | 无 `min-width: max-content` | 同上搜索 `max-content` → 仅允许出现在注释里 |
| T6 | 1440×900 实测：表格内宽 ≤ 容器宽、表头 12px/600、表头高 37px | playwright 读 `getBoundingClientRect` / `getComputedStyle` |
| T7 | 390×844 实测：`scrollWidth === innerWidth`，无表格（或已改列表） | playwright 读 `document.documentElement.scrollWidth` |
| T8 | 亮/暗两套主题下三层底色可辨 | 切换 `html.dark` 后读表头/条纹/hover 变量 |

---

## 十一、存量验收记录（2026-11-22）

| 项 | 结果 |
|---|---|
| 静态审计 19 张表（T1/T2/T3 + 列宽档位） | 0 违规；全部列宽属性落在档位表内 |
| 列宽归并 | 一次性值归并到档位（`60/70/76/82/86/90/94/95/100/105/106/130/132/150/170/250` → 档位值） |
| 1440×900 | `/factor-ranking`、`/strategy`、`/signals`、`/review`、`/fund` 表格内宽 ≤ 容器宽、`scrollable-x = false`、表头 `12px/600/37px`、数值列右对齐 |
| 768×1024 | `/factor-ranking` 保留桌面表格、`responsive-table` 生效、表格内宽 1064 > 容器 702 → 内部横滑（符合 6.1）、页面 `scrollWidth = 768` 不溢出 |
| 390×844 | 11 个页面 `tables = 0`、`scrollWidth = 390 = innerWidth` |
| 主题色 | 亮：表头 `#E9E9E6` / 行白 / 条纹 `rgba(0,0,0,.03)`；暗：表头 `#2A2A30` / 底 `#17171A` / 条纹 `rgba(255,255,255,.035)` |
| 未闭环 | `/dashboard`、`/monitor`、`/data-replay`、`/stock-sense` 弹窗、`/factor-analysis` 的表格未在本次取到数据（页面走空态或未触发查询），仅通过静态审计与全局样式覆盖 |

---

## 十二、全局实现索引

| 内容 | 位置 |
|---|---|
| 表格变量、外框、字体、密度 | `frontend/src/styles/index.scss` → `div.el-table { }` |
| 暗色条纹 / hover 覆盖 | 同文件 `html.dark div.el-table { }` |
| 横滑容器 | 同文件 `.responsive-table` / `.responsive-table .el-table` |
| 空态字号颜色 | 同文件 `.el-table__empty-text` |
| 移动端表格兜底 | 同文件 `@media (max-width: 767px)` 内 `.responsive-table` / `.el-table` |
| 移动端条目列表 | `frontend/src/styles/mobile.scss` + 各页 `.m-*-list` |
| 信号方向色 | 02 文档 6.4 |

修改表格外观时**只改这里**，改完按第 9 节全站复验。
