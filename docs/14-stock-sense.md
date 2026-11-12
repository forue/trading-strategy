# 盘感训练模块设计文档

> 版本: v1.0 | 更新日期: 2026-11-13 | 更新: 首次建立盘感训练专属说明，覆盖会话防作弊、交易结算、复盘后市、盘后总结与前端交互

---

## 一、模块概述

盘感训练是「个股 K 线盲盒回放」：系统随机抽取一只 A 股、隐藏其后市的连续一年日线，用户按天/周推进并判断买卖时机；结束后公开标的与区间、还原真实日期、结算收益并给出整段复盘与盘后总结。设计目标是**让用户练的是盘面判断，而不是记忆或查行情**，因此完整行情与真实日期在训练结束前都不下发给前端。

| 属性 | 值 |
|------|-----|
| 服务名 | backend-strategy（`/stock-sense` 路由，经网关为 `/api/strategy/stock-sense/*`） |
| 端口 | 8002 |
| 前端路由 | `/stock-sense` |
| 存储 | Redis（会话/记录/样本池）、InfluxDB `stock_kline`（行情） |
| 外部依赖 | data-collector（行情缺失时补采） |
| 前端技术 | Vue 3 + TypeScript + ECharts(vue-echarts) + Element Plus |
| 设计约束 | 无未来函数、训练中日期脱敏、规则可复现、不接入 LLM |

流程：`随机抽题 → 隐藏后市并只暴露前两个月 → 按天/周推进 + 分批交易/划线 → 主动结束或走到末尾 → 强制平仓与结算 → 复盘整段区间与后市 + 盘后总结`。

## 二、文件与依赖

```
services/strategy/app/
├── stock_sense.py      # 路由、会话、抽题、图表切片、交易、划线、结算、统计、复盘
└── sense_review.py     # 盘后总结规则引擎（形态/洗盘/出货/背离、离线方向校准、标准形态示意）

frontend/src/
├── views/StockSense.vue                 # 主页面：主图、操作条、划线、结算弹窗、复盘抽屉
├── components/SenseReviewPanel.vue      # 盘后总结面板 + 形态示例弹窗 + 建议点开关
├── components/SenseCandleDiagram.vue    # SVG 蜡烛示意图（标准形态 / 实际局部走势）
└── api/stockSense.ts                    # TS 类型与 8 个 API 封装
```

`stock_sense.py` 通过 `from shared import RedisManager, success_response` 复用共享库；Python 服务的导入路径与 Docker 构建上下文见 `AGENTS.md`。所有响应统一为 `{"code": 200, "data": ..., "message": "..."}`。

## 三、训练会话与防作弊

- 完整日线序列只保存在服务端 Redis 会话 `stock_sense:session:{sid}`（TTL 4 小时），接口按 `cursor` 切片返回 `_chart()` 结果，前端任何时刻拿不到未来数据。
- 训练中 `bars[].date`、`current_date`、`start_date`、成交与持仓日期统一替换为训练区间序号 `D0038`，前端显示为「第38根」，避免日期暗示牛熊阶段与政策窗口。`_state()` 不返回 `code` / `name`；结算后的 `summary`、`session.current_date`、`session.trades` 与复盘才返回真实日期。
- 抽题：`_fetch_stock_pool()` 取股票池 → 排除该用户最近 10 轮标的（`stock_sense:recent:{user}`）→ 取近 5 年日线（缺失时请求 data-collector 补采）→ `_pick_window()` 随机截取连续一年（≥230 个交易日、单次缺口 ≤30 天）→ 区间前 90 根作为 MA60/MACD 预热（不展示）。最多尝试 8 只标的。
- 每轮开始后台补采 12 只标的扩充 `stock_sense:ready_codes`（上限 120 只），用 `stock_sense:warm_lock` 避免并发重复采集。
- 初始可见区间为训练区间前两个月（`INITIAL_VIEW_MONTHS = 2`）；`unit=day` 推进一日，`unit=week` 推进到下一自然周最后一个交易日，前端切「按周」会同步把视图切成周线。
- 前端用 `localStorage['stock-sense-sid:' + user]` 记录会话 id，刷新页面后按 id 恢复（会话与划线都在后端）。结算时清除该键。

## 四、API 契约

| 方法 | 路径 | 关键参数 | 返回 |
|------|------|----------|------|
| POST | `/start` | `user` | `session` + `chart`（日线） |
| GET | `/{sid}/chart` | `view=day\|week\|month` | 当前可见 `chart` + `session`，不推进 |
| POST | `/{sid}/step` | `unit=day\|week`、`view` | 推进后的 `session` + `chart`；到末尾时附带 `summary` |
| POST | `/{sid}/trade` | `action=buy\|sell`、`ratio`、`view` | 成交后的 `session` + `chart` |
| POST | `/{sid}/lines` | body `{lines:[...]}` 整体覆盖 | 保存后的 `lines` |
| POST | `/{sid}/finish` | `view` | `summary` + `session` + 结算后真实日期的 `chart` |
| GET | `/stats/{user}` | — | 聚合统计 + 最近记录 |
| GET | `/replay/{session_id}` | `user`、`view` | `record`（含现场回算的 `review`）+ `chart` |

`/finish?view=` 必须返回刷新后的图表：训练中主图是脱敏日期，结算后 `_state()` 还原成交真实日期，若主图不刷新，前端按日期字符串匹配会让 B/S 点全部落到首根（买入后中途结束训练时最明显）。

## 五、数据结构

**会话 `sess`（服务端内部）**：`session_id`、`user`、`code`、`name`、`bars`（含预热段的完整日线）、`train_start`、`window_end`、`cursor`、`cash`、`position`、`trades`、`lots`、`lines`、`ended`。

**`chart`**：`bars[]`（`date` / `no` / OHLC / `volume` / `amount` / `change_pct` / `turnover`）、`ma`（MA5/10/20/60）、`macd`（`dif`/`dea`/`macd`）、`vol_ma`、可选 `future_start` / `future_bars`。

**`session`（对外状态）**：`session_id`、`ended`、`current_date`、`start_date`、`progress{current,total}`、`cash`、`market_value`、`equity`、`return_pct`、`float_pnl_pct`、`position`、`trades[]`、`lines[]`、`can_buy` / `can_sell` / `can_step`。`can_sell` 由 `cursor > buy_index` 实现 T+1 限制。

**`record`（结算记录，写入 Redis list）**：`session_id`、`user`、`code`、`name`、`start_date`、`end_date`、`window_end`、`initial_capital`、`final_equity`、`return_pct`、`benchmark_pct`、`excess_pct`、`trade_count`、`hold_days`、`forced_exit`、`trades[]`、`pairs[]`、`lines[]`、`review`、`future`、`created_at`。`window_end` 是原定区间末尾，`end_date` 是实际结束日，两者不同即提前结束。

**`review`**：`{range, summary, method, patterns, signals[], counts}`。旧记录可能缺 `lines` / `pairs` / `review.stat`，前端类型均用可选字段兼容。

## 六、交易与结算规则

| 项 | 规则 |
|----|------|
| 初始资金 | 100000 元 |
| 成交价 | 当根收盘价 + 0.1% 滑点 |
| 费用 | 佣金万三、最低 5 元；卖出加收千一印花税 |
| 买入 | 按「现金 × ratio」计算可买整手数；已持仓时按数量加权累加成本，`buy_index` 取最后一次 |
| 卖出 | 按「持仓 × ratio」向下取整到 100 股（`ratio=1` 清仓），未卖出部分按比例折减成本 |
| T+1 | 买入当日不可卖出 |
| 配对盈亏 | FIFO：`lots → matches`，费用按消耗数量分摊，单笔卖出配对盈亏之和等于该笔卖出对账户的实际影响 |
| 结算 | 走到区间末尾或主动结束时按最后收盘价强制平仓；`summary.pairs` 为全部配对明细，`trade_count` 为配对数 |
| 基准 | 买入持有：区间首根收盘价 → 结束根收盘价；`excess_pct = return_pct - benchmark_pct` |

前端预设仓位 1/4、1/3、1/2、全部；旧记录没有 `pairs` 时，复盘前端退回「全仓单笔、买卖交替」的本地配对。

## 七、`no` 锚定与划线

`no` 是每根 K 线在训练区间内的 1-based 序号，与 `bars[].no`、`trades[].no`、`review.signals[].no`、划线锚点 `x` 同源，日/周/月视图下均单调。周/月聚合 K 线的 `no` 取组内最后一根，前端 `anchorIndexIn()` 取首个 `no >= 目标` 的聚合根，因此切周期不会错位。

- 买卖点：优先按 `no` 锚定，找不到才退回日期二分匹配（兼容旧记录）。
- 划线：`{type, points:[{x:no, price}], color}`，支持 `hline`(1 点) / `trend`(2 点) / `channel`(3 点：两点定基准 + 一点定平行偏移) / `rect`(2 点) / `fib`(2 点，0~100% 六个价位)；单轮最多 40 条，前端整体覆盖提交，后端 `_clean_lines()` 校验类型、锚点数、`1<=no<=total`、价格与颜色。
- 划线随会话存 Redis，推进、切视图、刷新都能恢复；结算随 `record.lines` 落库，复盘按同一套 `no` 还原。
- 工具条「微调」：zrender 事件拖动已有锚点（18px 命中半径），拖动时右上角浮出局部放大镜（锚点附近 ±10 根、价格轴自适应），松手统一提交，还可删除选中线。

## 八、复盘与后续走势

- 会话结算后即删除；`replay` 用记录里的标的与区间从 InfluxDB 重查（含前置 90 根预热），因此旧记录也有盘后总结（现场回算）。
- `window_end` 之后最多 60 个交易日的真实行情只在结算/复盘后返回：结算弹窗给出收盘价迷你走势图与涨跌幅；复盘图把后市拼在训练区间之后，用橙色实线、半透明背景与淡色 K 线分界，灰色虚线标出提前结束日。
- 周/月视图按 `_phase`（train / future）分组聚合，分界那一周或一个月不会被合并成一根；`future_start` 是后市首根下标、`future_bars` 是根数，后市 bars 的 `no` 接着训练区间递增但不参与划线锚定。数据只到区间末尾时后市为空。
- 因不保存 cursor 轨迹，复盘是**整段回看**而非逐日重放。

## 九、盘后总结与形态示例

`sense_review.py` 是纯规则引擎（不接 LLM、无未来函数）：逐根按「当前根及其之前」识别 `_kline_patterns`（锤子、吞没、星线、长上影、放量突破、巨量十字星等）、`_washout`（洗盘）、`_distribution`（出货）、`_divergence`（MACD/RSI 背离），输出顺序即时间顺序；同向冷却 8 根、中性 12 根，不全局挑分数前 N、不为凑类别硬选。

- **方向不按教科书给结论**：`RULE_EDGE` 来自离线校准——24 只 A 股 × 3 个一年窗口、69 段区间共 5203 次形态命中，按「下一交易日开盘介入、第 5 日收盘退出」统计；标的等分两组，方向只由第一组确定（样本 ≥8 且均值绝对值 ≥0.3%），第二组仅作样本外检验。例如「放量突破平台」样本后 5 日平均 -2.10%、仅 33.3% 上涨，标为「统计偏空 · 与教科书相反」；第一组不显著一律中性。
- 样本外检验（第二组，同口径）：买入信号后 5 日超额由旧版 -0.71% 收敛到 -0.06%、10 日由 -2.10% 转为 +0.33%（不再系统性反指，但仍无显著优势，**不足以当作买入指令**）；卖出信号后 10 日超额由 +1.00% 转为 -1.34%，方向命中率由 51.7% 提升到 60.0%。提高定向门槛会让信号变少却在样本外更不稳定，故保持低门槛、由面板滚动展示。
- 每条理由带 `tag` / `text` / `title` / `bias` / `weight` / `contrarian` / `stat{n,r5,pos5,h0,h1,side}` / `pattern`；参考点附「下一交易日开盘执行 / 失效位 / 观察 5 日」，`window` 只含触发根及之前 8 根真实 K 线。
- `PATTERN_SHAPES` 提供 14 种标准形态的归一化 `[o,h,l,c]`、`focus`、`note`、`rule`。`rule` 说明图中画不出的量能与均线命中条件；每个示例都按对应识别规则校验过（曾修正早晨/黄昏之星的跳空、滞涨涨幅阈值，以及缩量回踩、横盘蓄势、阴线反包被错配到别的图）。`REASON_PATTERN` 负责理由→示意映射，背离类没有确定 K 线外形，不给示意。
- `SenseCandleDiagram.vue` 用 SVG 按自身 `hi/lo` 归一化画蜡烛（红涨绿跌），蓝色虚线标触发根；弹窗把实际 `window` 切成与示意相同的最后 N 根并列对照，另附完整 9 根上下文，避免根数不同造成的视觉错位。
- 面板默认「仅定向」，可切「含中性」；图上编号圆点只标定向点，编号与面板定向列表一致。

## 十、前端交互

**操作条**：仓位、买入/卖出、按天/按周、下一根、自动播放与慢/中/快档（1200/600/250ms）、速度档位。「请求进行中按钮宽度不变」由 CSS 把 Element Plus loading 图标绝对定位到按钮左侧内边距、清掉文字 `span` 的 `margin-left` 实现（否则图标 14px + 间距 6px 会让宽度 +20px，连续点「下一根」时操作条抖动）。

**快捷键**：

| 键 | 动作 |
|----|------|
| `空格` / `→` | 下一根 |
| `B` / `S` | 买入 / 卖出 |
| `P` | 自动播放 / 暂停 |
| `1` / `2` / `3` | 日 / 周 / 月线 |
| `H` | 显示 / 隐藏建议点 |
| `Esc` | 停止播放 |

文本输入框聚焦、弹窗/抽屉打开时不推进不交易（弹窗内 `H` / `Esc` 仍可用）。

**自动播放**：串行推进，等上一根返回再排下一根；结算、请求失败、暂停或任何手动操作都会停止。播放中的单步请求用独立的 `stepping` 计数，不占用按钮的 `busy`，因此整排按钮不会反复出现 loading 图标；`guardManual()` 会先停止播放、等在途请求结束，再执行手动推进/交易/切视图/划线/结束训练，避免两个请求同时改同一个 Redis 会话。

**指标开关**：均线、成交量、MACD 可单独勾选，主图与复盘图共用；`buildChartOption()` 按剩余副图数动态重排 grid、坐标轴、dataZoom 与 legend（隐藏全部副图时主图占满），series 按开关裁剪。

**建议点开关**：盘后总结标题行、复盘工具条与 `H` 键共用一个状态（结算弹窗与复盘抽屉同步）。关掉后总结列表与复盘图上的编号圆点一起隐藏，只留自己的 B/S 点；划线、结束日虚线、后市分界与 `markLine` 不受影响，`含中性` 开关同时禁用。

**复盘入口**：页面头部「历史复盘」按钮始终可用（未开始训练也能打开），抽屉按区间列出最近记录，点任一条即回放；结算弹窗另有「查看后续走势与复盘」按钮，直接回放本轮。

## 十一、统计与历史记录

记录按用户存 Redis list（`stock_sense:records:{user}`，最近 200 条）。`_stats()` 返回 `total`、`win_count`、`win_rate`、`avg_return`、`avg_excess`、`best_return`、`worst_return`、`cumulative_return`、`avg_hold_days`、`avg_trade_count` 与 `records`（前端只展示前 50 条）。`cumulative_return` 按各轮收益复利相乘。

## 十二、关键常量

| 常量 | 值 | 含义 |
|------|-----|------|
| `INITIAL_CAPITAL` | 100000.0 | 初始资金 |
| `COMMISSION_RATE` / `MIN_COMMISSION` | 0.0003 / 5.0 | 佣金与最低佣金 |
| `STAMP_TAX_RATE` / `SLIPPAGE_RATE` | 0.001 / 0.001 | 卖出印花税 / 滑点 |
| `WARMUP_BARS` / `WINDOW_DAYS` / `MIN_WINDOW_BARS` | 90 / 365 / 230 | 指标预热 / 区间跨度 / 最少交易日 |
| `INITIAL_VIEW_MONTHS` / `MAX_PICK_ATTEMPTS` | 2 / 8 | 初始可见月数 / 抽题重试 |
| `FUTURE_BARS` / `FUTURE_DAYS` | 60 / 150 | 后市交易日数 / 查询跨度 |
| `SESSION_TTL` / `MAX_RECORDS` / `MAX_LINES` | 14400 / 200 / 40 | 会话 TTL(秒) / 记录上限 / 划线上限 |
| `EXCLUDE_RECENT` / `WARM_BATCH` / `READY_TARGET` | 10 / 12 / 120 | 去重轮数 / 后台补采数 / 样本池目标 |

## 十三、部署与验证

```powershell
docker compose up -d --build backend-strategy frontend
cd frontend; npm run build; npm run typecheck; npm run lint
```

- 前端构建产物经 `vite-plugin-pwa` 生成 Service Worker，改 CSS/JS 后浏览器可能仍加载旧 `StockSense-*.css`；验证前需注销 SW、删除 caches 并强制刷新（Ctrl+F5）。
- `npm run typecheck` 目前存在与本模块无关的既有错误（`tsconfig.json` 的 `useDefineForExpose`、`ChatAssistant.vue` 等），`npm run lint` 依赖全局 ESLint 且项目缺少 eslint 配置；排查本模块时以 `npm run build` 与改动文件的 IDE 诊断为准。
- 浏览器实测要点：指标开关后 ECharts `getOption()` 的 grid/series 数量与 `dataZoom.xAxisIndex`；自动播放期间按钮宽度与 `.is-loading` 数量；建议点开关后 `series[0].markPoint.data` 只剩 B/S 且 `markLine` 不变；提前结束训练时 B/S 点按 `no` 落在正确位置。

## 十四、已知限制与后续候选

- 不保存 cursor 轨迹，复盘无法逐日重放当时的资金/持仓状态；只能整段回看。
- 训练参数（区间长度、初始资金、预热根数、后市根数、题库范围、难度）均为后端常量，`/start` 无配置入参；改 `INITIAL_CAPITAL` 会影响结算基准，需与历史记录口径隔离。
- 移动端与无障碍较弱：划线仅绑定 zrender 的 `mousedown/mousemove/mouseup`，无 pointer/touch 通道。
- 无文字笔记/错题本、成长曲线/成就、排行榜与多用户对比；无指标之外的自定义叠加层。
- 盘后总结是统计倾向而非买卖指令；样本外检验显示买入信号仍无显著优势，面板已明确标注口径与不确定性。
