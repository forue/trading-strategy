<template>
  <div class="sense-page">
    <header class="sense-header">
      <div class="title-block">
        <h2>盘感训练</h2>
        <p>随机标的 · 隐藏后市的连续一年K线 · 按天/周推进，判断买卖时机</p>
      </div>
      <div class="header-actions">
        <el-radio-group v-model="view" size="small" :disabled="busy || !sid" @change="onViewChange">
          <el-radio-button value="day">日线</el-radio-button>
          <el-radio-button value="week">周线</el-radio-button>
          <el-radio-button value="month">月线</el-radio-button>
        </el-radio-group>
        <el-button v-if="!state" type="primary" :loading="busy" @click="start">开始训练</el-button>
        <el-button v-else-if="state.ended" type="primary" :loading="busy" @click="start">
          再来一轮
        </el-button>
        <el-button v-else plain :loading="busy" :disabled="!sid" @click="doFinish">结束训练</el-button>
        <el-button plain @click="historyVisible = true">历史复盘</el-button>
      </div>
    </header>

    <el-empty v-if="!state" description="点击「开始训练」，系统会随机抽取一只A股并隐藏后市K线">
      <el-button type="primary" :loading="busy" @click="start">开始训练</el-button>
    </el-empty>

    <div v-else class="sense-body">
      <section class="chart-panel">
        <div class="chart-meta">
          <div class="meta-text">
            <span v-if="summary" class="revealed">
              标的：{{ summary.name }}（{{ summary.code }}） · {{ summary.start_date }} ~
              {{ summary.end_date }}
            </span>
            <span v-else class="masked">标的：??????（训练结束后公开）</span>
            <span>当前 {{ dayLabel(state.current_date) }}</span>
            <span class="progress-text">
              进度 {{ state.progress.current }} / {{ state.progress.total }}
            </span>
          </div>
          <div v-if="!state.ended" class="draw-tools">
            <span class="draw-hint">{{ drawHint }}</span>
            <el-button-group>
              <el-button
                v-for="t in drawTools"
                :key="t.type"
                size="small"
                :type="drawMode === t.type ? 'primary' : 'default'"
                :disabled="busy"
                @click="setDrawMode(t.type)"
              >
                {{ t.label }}
              </el-button>
            </el-button-group>
            <el-button size="small" text :disabled="!lines.length || busy" @click="undoLine">
              撤销
            </el-button>
            <el-button size="small" text :disabled="!lines.length || busy" @click="clearLines">
              清除
            </el-button>
          </div>
        </div>
        <el-progress :percentage="progressPct" :show-text="false" :stroke-width="4" />
        <VChart ref="chartRef" class="kline-chart" :option="chartOption" autoresize />
        <div class="chart-legend-tip">
          {{ view === 'day' ? 'MA5 / MA10 / MA20 / MA60' : 'MA5 / MA10' }} · MACD(12,26,9) · 红涨绿跌
        </div>
        <div v-if="!state.ended" class="trade-bar">
          <span class="trade-label">仓位</span>
          <el-radio-group v-model="ratio" size="small" :disabled="busy">
            <el-radio-button :value="0.25">1/4</el-radio-button>
            <el-radio-button :value="1 / 3">1/3</el-radio-button>
            <el-radio-button :value="0.5">1/2</el-radio-button>
            <el-radio-button :value="1">全部</el-radio-button>
          </el-radio-group>
          <el-button type="danger" :loading="busy" :disabled="!state.can_buy" @click="doTrade('buy')">
            买入
          </el-button>
          <el-button type="success" :loading="busy" :disabled="!state.can_sell" @click="doTrade('sell')">
            卖出
          </el-button>
          <span class="trade-divider" />
          <el-radio-group v-model="unit" size="small" :disabled="busy" @change="onUnitChange">
            <el-radio-button value="day">按天</el-radio-button>
            <el-radio-button value="week">按周</el-radio-button>
          </el-radio-group>
          <el-button :loading="busy" :disabled="!state.can_step" @click="doStep">下一根</el-button>
        </div>
      </section>

      <aside class="side-panel">
        <div class="card">
          <div class="card-title">账户</div>
          <div class="kv"><span>总资产</span><b>{{ fmt(state.equity) }}</b></div>
          <div class="kv"><span>可用现金</span><b>{{ fmt(state.cash) }}</b></div>
          <div class="kv"><span>持仓市值</span><b>{{ fmt(state.market_value) }}</b></div>
          <div class="kv">
            <span>累计收益</span>
            <b :class="pnlClass(state.return_pct)">{{ signed(state.return_pct) }}%</b>
          </div>
          <template v-if="state.position">
            <el-divider />
            <div class="kv"><span>持股</span><b>{{ state.position.shares }} 股</b></div>
            <div class="kv"><span>成本价</span><b>{{ state.position.cost_price.toFixed(3) }}</b></div>
            <div class="kv"><span>买入日</span><b>{{ dayLabel(state.position.buy_date) }}</b></div>
            <div class="kv">
              <span>浮动盈亏</span>
              <b :class="pnlClass(state.float_pnl_pct ?? 0)">{{ signed(state.float_pnl_pct ?? 0) }}%</b>
            </div>
          </template>
        </div>

        <div class="card">
          <div class="card-title">交易记录</div>
          <div v-if="!state.trades.length" class="empty-tip">暂无交易</div>
          <div v-for="(t, i) in state.trades" :key="i" class="trade-row">
            <span :class="t.action === 'BUY' ? 'tag-buy' : 'tag-sell'">
              {{ t.action === 'BUY' ? '买' : '卖' }}
            </span>
            <span class="trade-date">{{ dayLabel(t.date) }}</span>
            <span class="trade-price">{{ t.price.toFixed(3) }}</span>
            <span class="trade-shares">{{ t.shares }}股</span>
          </div>
        </div>

      </aside>
    </div>

    <el-dialog v-model="summaryVisible" title="训练结算" width="620px" :close-on-click-modal="false">
      <div v-if="summary" class="summary">
        <div class="summary-reveal">
          <span class="reveal-label">标的</span>
          <b>{{ summary.name }}（{{ summary.code }}）</b>
          <span class="reveal-label">区间</span>
          <b>{{ summary.start_date }} ~ {{ summary.end_date }}</b>
        </div>
        <div class="summary-nums">
          <div>
            <span>策略收益</span>
            <b :class="pnlClass(summary.return_pct)">{{ signed(summary.return_pct) }}%</b>
          </div>
          <div>
            <span>买入持有</span>
            <b :class="pnlClass(summary.benchmark_pct)">{{ signed(summary.benchmark_pct) }}%</b>
          </div>
          <div>
            <span>超额收益</span>
            <b :class="pnlClass(summary.excess_pct)">{{ signed(summary.excess_pct) }}%</b>
          </div>
          <div>
            <span>期末资产</span>
            <b>{{ fmt(summary.final_equity) }}</b>
          </div>
          <div>
            <span>交易次数</span>
            <b>{{ summary.trade_count }}</b>
          </div>
          <div>
            <span>持有天数</span>
            <b>{{ summary.hold_days }}</b>
          </div>
        </div>
        <div v-if="summary.forced_exit" class="forced-tip">回放结束，持仓已按最后交易日收盘价强制平仓</div>
        <el-table v-if="summary.trades.length" :data="summary.trades" size="small" max-height="220">
          <el-table-column prop="action" label="方向" width="70">
            <template #default="{ row }">{{ row.action === 'BUY' ? '买入' : '卖出' }}</template>
          </el-table-column>
          <el-table-column prop="date" label="日期" width="110" />
          <el-table-column prop="price" label="价格" width="90">
            <template #default="{ row }">{{ row.price.toFixed(3) }}</template>
          </el-table-column>
          <el-table-column prop="shares" label="股数" width="90" />
          <el-table-column prop="fee" label="费用" width="90">
            <template #default="{ row }">{{ row.fee.toFixed(2) }}</template>
          </el-table-column>
        </el-table>
      </div>
      <template #footer>
        <el-button v-if="summary" @click="replayCurrent">复盘完整行情</el-button>
        <el-button @click="summaryVisible = false">查看统计</el-button>
        <el-button type="primary" :loading="busy" @click="start">再来一轮</el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="replayVisible" title="训练复盘" size="80%" :destroy-on-close="true">
      <div v-if="replayRecord" class="replay">
        <div class="summary-reveal">
          <span class="reveal-label">标的</span>
          <b>{{ replayRecord.name }}（{{ replayRecord.code }}）</b>
          <span class="reveal-label">区间</span>
          <b>{{ replayRecord.start_date }} ~ {{ replayRecord.end_date }}</b>
        </div>
        <div class="summary-nums">
          <div>
            <span>策略收益</span>
            <b :class="pnlClass(replayRecord.return_pct)">{{ signed(replayRecord.return_pct) }}%</b>
          </div>
          <div>
            <span>买入持有</span>
            <b :class="pnlClass(replayRecord.benchmark_pct)">{{ signed(replayRecord.benchmark_pct) }}%</b>
          </div>
          <div>
            <span>超额收益</span>
            <b :class="pnlClass(replayRecord.excess_pct)">{{ signed(replayRecord.excess_pct) }}%</b>
          </div>
          <div>
            <span>交易次数</span>
            <b>{{ replayRecord.trade_count }}</b>
          </div>
        </div>

        <div
          v-if="replayRecord.window_end && replayRecord.window_end !== replayRecord.end_date"
          class="forced-tip"
        >
          你在 {{ replayRecord.end_date }} 结束训练，竖线之后是未经历的后市行情
        </div>

        <div class="replay-toolbar">
          <el-radio-group
            v-model="replayView"
            size="small"
            :disabled="replayLoading"
            @change="switchReplayView"
          >
            <el-radio-button value="day">日线</el-radio-button>
            <el-radio-button value="week">周线</el-radio-button>
            <el-radio-button value="month">月线</el-radio-button>
          </el-radio-group>
          <span class="replay-hint">B/S 为你的买卖点；复盘展示整个训练区间，不是当时的逐日视野</span>
          <span v-if="replayRecord.lines?.length" class="replay-hint">
            本轮划线 {{ replayRecord.lines.length }} 条
          </span>
        </div>

        <div v-loading="replayLoading" class="replay-chart">
          <VChart v-if="replayChart" class="kline-chart" :option="replayOption" autoresize />
        </div>

        <div class="card-title">逐笔交易</div>
        <el-table v-if="pairs.length" :data="pairs" size="small" max-height="240">
          <el-table-column prop="buy_date" label="买入日" width="106" />
          <el-table-column label="买入价" width="82">
            <template #default="{ row }">{{ row.buy_price.toFixed(3) }}</template>
          </el-table-column>
          <el-table-column prop="sell_date" label="卖出日" width="106" />
          <el-table-column label="卖出价" width="82">
            <template #default="{ row }">{{ row.sell_price.toFixed(3) }}</template>
          </el-table-column>
          <el-table-column prop="shares" label="股数" width="76" />
          <el-table-column label="盈亏" width="94">
            <template #default="{ row }">
              <span :class="pnlClass(row.pnl)">{{ row.pnl > 0 ? '+' : '' }}{{ fmt(row.pnl) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="盈亏比" width="86">
            <template #default="{ row }">
              <span :class="pnlClass(row.pnl_pct)">{{ signed(row.pnl_pct) }}%</span>
            </template>
          </el-table-column>
          <el-table-column prop="days" label="持有天数" width="86" />
          <el-table-column label="备注">
            <template #default="{ row }">{{ row.forced ? '回放结束强制平仓' : '' }}</template>
          </el-table-column>
        </el-table>
        <div v-else class="empty-tip">全程空仓，没有产生交易</div>
      </div>
    </el-drawer>

    <el-drawer v-model="historyVisible" title="历史复盘" size="560px">
      <template v-if="stats && stats.total">
        <div class="stat-grid">
          <div><span>训练次数</span><b>{{ stats.total }}</b></div>
          <div><span>胜率</span><b>{{ stats.win_rate }}%</b></div>
          <div><span>平均收益</span><b :class="pnlClass(stats.avg_return ?? 0)">{{ signed(stats.avg_return ?? 0) }}%</b></div>
          <div><span>平均超额</span><b :class="pnlClass(stats.avg_excess ?? 0)">{{ signed(stats.avg_excess ?? 0) }}%</b></div>
          <div><span>累计收益</span><b :class="pnlClass(stats.cumulative_return ?? 0)">{{ signed(stats.cumulative_return ?? 0) }}%</b></div>
          <div><span>平均持有</span><b>{{ stats.avg_hold_days }} 天</b></div>
        </div>
        <el-divider />
        <div class="record-list record-list-wide">
          <div
            v-for="r in stats.records"
            :key="r.session_id"
            class="record-row"
            @click="openReplay(r)"
          >
            <div class="record-info">
              <span class="record-name">{{ r.name }}（{{ r.code }}）</span>
              <span class="record-date">{{ r.start_date }} ~ {{ r.end_date }}</span>
            </div>
            <div class="record-side">
              <span class="record-return" :class="pnlClass(r.return_pct)">{{ signed(r.return_pct) }}%</span>
              <span class="record-action">复盘</span>
            </div>
          </div>
        </div>
        <div class="record-tip">点任意一条即可回放当轮完整K线与买卖点，不用重新训练</div>
      </template>
      <div v-else class="empty-tip">还没有已结算的训练，先完成一轮</div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { BarChart, LineChart, ScatterChart, CandlestickChart } from 'echarts/charts'
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
  MarkPointComponent,
  MarkLineComponent,
  MarkAreaComponent,
} from 'echarts/components'

import { CanvasRenderer } from 'echarts/renderers'
import { ElMessage } from 'element-plus'
import { stockSenseApi } from '@/api/stockSense'
import type {
  ChartView,
  SenseChart,
  SenseLine,
  SenseLineType,
  SensePair,
  SenseState,
  SenseStats,
  SenseSummary,
  SenseTrade,
  StepUnit,
} from '@/api/stockSense'
import { useUserStore } from '@/stores/user'

use([
  BarChart, LineChart, ScatterChart, CandlestickChart,
  GridComponent, TooltipComponent, LegendComponent, DataZoomComponent,
  MarkPointComponent, MarkLineComponent, MarkAreaComponent, CanvasRenderer,
])

const userStore = useUserStore()
const userName = computed(() => userStore.userInfo?.username || 'default')

/** 当前训练会话 id 的本地记录，用于刷新页面后恢复训练（会话与划线都在后端） */
const SID_KEY = 'stock-sense-sid:'

const busy = ref(false)
const sid = ref('')
const state = ref<SenseState | null>(null)
const chart = ref<SenseChart | null>(null)
const view = ref<ChartView>('day')
const unit = ref<StepUnit>('day')
const summary = ref<SenseSummary | null>(null)
const summaryVisible = ref(false)
const stats = ref<SenseStats | null>(null)

/** 本次交易使用的仓位比例 */
const ratio = ref(1)

// ─── 划线：锚点为「训练区间序号 + 价格」，随会话存在后端 ───
const chartRef = ref<any>(null)
const lines = ref<SenseLine[]>([])
const drawMode = ref<SenseLineType | ''>('')
const pendingPoints = ref<{ x: number; price: number }[]>([])
const LINE_COLORS = ['#e6a23c', '#409eff', '#b18cf0', '#67c23a', '#f56c6c']
const drawTools: { type: SenseLineType; label: string; anchors: number }[] = [
  { type: 'hline', label: '水平', anchors: 1 },
  { type: 'trend', label: '趋势', anchors: 2 },
  { type: 'channel', label: '通道', anchors: 3 },
  { type: 'rect', label: '矩形', anchors: 2 },
  { type: 'fib', label: '斐波', anchors: 2 },
]

const drawHint = computed(() => {
  const tool = drawTools.find((t) => t.type === drawMode.value)
  if (!tool) return '点击工具后在图上取点，划线随训练保存'
  if (state.value?.ended) return '训练已结束'
  const got = pendingPoints.value.length
  if (tool.type === 'channel') {
    return got === 0 ? '通道：点趋势线起点' : got === 1 ? '通道：点趋势线终点' : '通道：点一点定宽度'
  }
  if (tool.anchors === 1) return '水平线：点一下确定价位'
  return got === 0 ? '点第一个点' : '点第二个点'
})

const historyVisible = ref(false)
const replayVisible = ref(false)
const replayLoading = ref(false)
const replayRecord = ref<SenseSummary | null>(null)
const replayChart = ref<SenseChart | null>(null)
const replayView = ref<ChartView>('day')

const progressPct = computed(() => {
  if (!state.value) return 0
  const { current, total } = state.value.progress
  return Math.min(100, Math.round((current / Math.max(total, 1)) * 100))
})

const fmt = (v: number) => v.toLocaleString('zh-CN', { maximumFractionDigits: 2 })
const signed = (v: number) => `${v > 0 ? '+' : ''}${v.toFixed(2)}`
const pnlClass = (v: number) => (v > 0 ? 'up' : v < 0 ? 'down' : '')

/** 训练中后端用 D0001 这类序号代替真实日期，这里转成「第N根」；真实日期原样显示 */
const dayLabel = (v: string) => (/^D\d+$/.test(v) ? `第${Number(v.slice(1))}根` : v)

function buildChartOption(
  c: SenseChart | null,
  trades: SenseTrade[],
  endDate?: string,
  guides: SenseLine[] = [],
  pending: { x: number; price: number }[] = [],
) {
  if (!c || !c.bars.length) return {}

  const rawDates = c.bars.map((b) => b.date)
  const dates = rawDates.map(dayLabel)
  const ohlc = c.bars.map((b) => [b.open, b.close, b.low, b.high])
  const colors = c.bars.map((b) => (b.close >= b.open ? '#ef232a' : '#14b143'))
  const maColors: Record<string, string> = {
    ma5: '#e6a23c', ma10: '#409eff', ma20: '#b18cf0', ma60: '#67c23a',
  }

  const maSeries = Object.keys(c.ma).map((name) => ({
    name: name.toUpperCase(),
    type: 'line',
    data: c.ma[name],
    smooth: true,
    showSymbol: false,
    lineStyle: { width: 1, color: maColors[name] || '#909399' },
    itemStyle: { color: maColors[name] || '#909399' },
    xAxisIndex: 0,
    yAxisIndex: 0,
  }))

  // 买卖点标记：日线精确命中，周线/月线归到所属周期那根K线
  const marks: any[] = []
  const idxOf: Record<string, number> = {}
  rawDates.forEach((d, i) => { idxOf[d] = i })
  const barIndexFor = (d: string): number => {
    if (idxOf[d] !== undefined) return idxOf[d]
    let lo = 0
    let hi = rawDates.length - 1
    let ans = -1
    while (lo <= hi) {
      const mid = (lo + hi) >> 1
      if (rawDates[mid] <= d) {
        ans = mid
        lo = mid + 1
      } else {
        hi = mid - 1
      }
    }
    return ans
  }
  for (const t of trades) {
    const i = barIndexFor(t.date)
    if (i < 0) continue
    marks.push({
      name: t.action === 'BUY' ? '买入' : '卖出',
      coord: [i, t.price],
      value: t.action === 'BUY' ? 'B' : 'S',
      itemStyle: { color: t.action === 'BUY' ? '#ef232a' : '#14b143' },
      symbol: 'pin',
      symbolSize: 34,
      label: { color: '#fff', fontSize: 11 },
    })
  }

  // 复盘时标出「你结束的那天」，之后是未经历的后市
  const endIdx = endDate ? barIndexFor(endDate) : -1
  const markLineData: any[] = []
  if (endIdx >= 0) {
    markLineData.push({
      xAxis: endIdx,
      lineStyle: { color: '#909399', type: 'dashed', width: 1 },
      label: { formatter: '结束', color: '#909399', fontSize: 10, position: 'insideEndTop' },
    })
  }

  // 训练划线：锚点是训练区间序号，按当前视图的K线序号映射到索引
  const barNos = c.bars.map((b, i) => b.no ?? i + 1)
  const anchorIndex = (no: number): number => {
    let idx = 0
    for (let k = 0; k < barNos.length; k++) {
      if (barNos[k] <= no) idx = k
      else break
    }
    return idx
  }
  const guideAreas: any[] = []
  for (const g of guides) {
    const pts = g.points.map((p) => [anchorIndex(p.x), p.price] as [number, number])
    const dashed = { color: g.color, width: 1, type: 'dashed' as const }
    if (g.type === 'hline') {
      markLineData.push({
        yAxis: pts[0][1],
        lineStyle: dashed,
        label: { formatter: pts[0][1].toFixed(2), position: 'insideEndTop', color: g.color, fontSize: 10 },
      })
    } else if (g.type === 'trend') {
      markLineData.push([{ coord: pts[0], lineStyle: dashed }, { coord: pts[1] }])
    } else if (g.type === 'channel') {
      const [[x1, y1], [x2, y2], [x3, y3]] = pts
      const slope = x2 === x1 ? 0 : (y2 - y1) / (x2 - x1)
      const offset = y3 - (y1 + slope * (x3 - x1))
      markLineData.push([{ coord: pts[0], lineStyle: dashed }, { coord: pts[1] }])
      markLineData.push([
        { coord: [x1, y1 + offset], lineStyle: dashed },
        { coord: [x2, y2 + offset] },
      ])
    } else if (g.type === 'rect') {
      guideAreas.push([
        { coord: pts[0], itemStyle: { color: g.color, opacity: 0.06 } },
        { coord: pts[1] },
      ])
    } else if (g.type === 'fib') {
      const y1 = pts[0][1]
      const span = pts[1][1] - y1
      for (const lv of [0, 0.236, 0.382, 0.5, 0.618, 1]) {
        const price = y1 + span * lv
        markLineData.push({
          yAxis: price,
          lineStyle: { color: g.color, width: 1, type: 'dotted' },
          label: {
            formatter: `${(lv * 100).toFixed(1)}% ${price.toFixed(2)}`,
            position: 'insideEndTop',
            color: g.color,
            fontSize: 9,
          },
        })
      }
    }
  }
  const guideMarkLine = markLineData.length
    ? { symbol: 'none', silent: true, animation: false, data: markLineData }
    : undefined
  const guideMarkArea = guideAreas.length
    ? { silent: true, animation: false, data: guideAreas }
    : undefined

  return {
    animation: false,
    backgroundColor: 'transparent',
    legend: {
      top: 0,
      left: 0,
      data: Object.keys(c.ma).map((n) => n.toUpperCase()),
      textStyle: { color: '#8a94a6', fontSize: 11 },
    },
    tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
    grid: [
      { left: 56, right: 20, top: 30, height: '46%' },
      { left: 56, right: 20, top: '58%', height: '13%' },
      { left: 56, right: 20, top: '76%', height: '15%' },
    ],
    xAxis: [0, 1, 2].map((i) => ({
      type: 'category',
      gridIndex: i,
      data: dates,
      boundaryGap: true,
      axisLine: { lineStyle: { color: '#2f3644' } },
      axisLabel: { show: i === 2, color: '#8a94a6', fontSize: 10 },
      axisTick: { show: false },
      splitLine: { show: false },
    })),
    yAxis: [
      {
        scale: true,
        gridIndex: 0,
        splitLine: { lineStyle: { color: 'rgba(128,128,128,0.15)' } },
        axisLabel: { color: '#8a94a6', fontSize: 10 },
      },
      {
        scale: true,
        gridIndex: 1,
        splitNumber: 2,
        axisLabel: { show: false },
        splitLine: { show: false },
      },
      {
        scale: true,
        gridIndex: 2,
        splitNumber: 2,
        axisLabel: { color: '#8a94a6', fontSize: 10 },
        splitLine: { show: false },
      },
    ],
    dataZoom: [
      { type: 'inside', xAxisIndex: [0, 1, 2], start: 0, end: 100 },
      { type: 'slider', xAxisIndex: [0, 1, 2], height: 16, bottom: 4, start: 0, end: 100 },
    ],
    series: [
      {
        name: 'K线',
        type: 'candlestick',
        data: ohlc,
        xAxisIndex: 0,
        yAxisIndex: 0,
        itemStyle: {
          color: '#ef232a', color0: '#14b143',
          borderColor: '#ef232a', borderColor0: '#14b143',
        },
        markPoint: marks.length ? { data: marks } : undefined,
        markLine: guideMarkLine,
        markArea: guideMarkArea,
      },
      ...maSeries,
      ...(pending.length
        ? [{
            name: '划线锚点',
            type: 'scatter',
            data: pending.map((p) => [anchorIndex(p.x), p.price]),
            symbolSize: 9,
            itemStyle: { color: '#409eff' },
            xAxisIndex: 0,
            yAxisIndex: 0,
            silent: true,
            tooltip: { show: false },
          }]
        : []),
      {
        name: '成交量',
        type: 'bar',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: c.bars.map((b, i) => ({ value: b.volume, itemStyle: { color: colors[i], opacity: 0.7 } })),
      },
      {
        name: 'MACD',
        type: 'bar',
        xAxisIndex: 2,
        yAxisIndex: 2,
        data: c.macd.macd.map((v) => ({
          value: v,
          itemStyle: { color: v >= 0 ? '#ef232a' : '#14b143', opacity: 0.8 },
        })),
      },
      {
        name: 'DIF',
        type: 'line',
        xAxisIndex: 2,
        yAxisIndex: 2,
        data: c.macd.dif,
        showSymbol: false,
        lineStyle: { width: 1, color: '#e6a23c' },
        itemStyle: { color: '#e6a23c' },
      },
      {
        name: 'DEA',
        type: 'line',
        xAxisIndex: 2,
        yAxisIndex: 2,
        data: c.macd.dea,
        showSymbol: false,
        lineStyle: { width: 1, color: '#409eff' },
        itemStyle: { color: '#409eff' },
      },
    ],
  }
}

const chartOption = computed(() =>
  buildChartOption(chart.value, state.value?.trades || [], undefined, lines.value, pendingPoints.value)
)
const replayOption = computed(() =>
  buildChartOption(
    replayChart.value,
    replayRecord.value?.trades || [],
    replayRecord.value?.end_date,
    replayRecord.value?.lines || [],
  )
)

async function loadStats() {
  try {
    stats.value = await stockSenseApi.stats(userName.value)
  } catch { /* 统计失败不影响训练 */ }
}

/** 复盘逐笔：新记录用后端 FIFO 配对（支持分批买卖），旧记录退回「全仓单笔、买卖交替」的本地配对 */
const pairs = computed<SensePair[]>(() => {
  const rec = replayRecord.value
  if (!rec) return []
  if (rec.pairs?.length) return rec.pairs

  const list: SensePair[] = []
  let pending: SenseTrade | null = null
  for (const t of rec.trades || []) {
    if (t.action === 'BUY') {
      pending = t
      continue
    }
    if (!pending) continue
    const cost = pending.price * pending.shares + pending.fee
    const income = t.price * t.shares - t.fee
    list.push({
      buy_date: pending.date,
      buy_price: pending.price,
      sell_date: t.date,
      sell_price: t.price,
      shares: t.shares,
      pnl: Math.round((income - cost) * 100) / 100,
      pnl_pct: cost ? Math.round((income / cost - 1) * 10000) / 100 : 0,
      days: Math.round((new Date(t.date).getTime() - new Date(pending.date).getTime()) / 86400000),
      forced: !!t.forced,
    })
    pending = null
  }
  return list
})

async function openReplay(r: SenseSummary) {
  historyVisible.value = false
  replayRecord.value = r
  replayView.value = 'day'
  replayVisible.value = true
  await loadReplay(r.session_id, 'day')
}

/** 结算弹窗直接打开本轮复盘，不必去历史列表里找 */
async function replayCurrent() {
  const s = summary.value
  if (!s) return
  summaryVisible.value = false
  await openReplay(s)
}

async function switchReplayView(v: string | number | boolean | undefined) {
  if (!replayRecord.value) return
  await loadReplay(replayRecord.value.session_id, v as ChartView)
}

async function loadReplay(sessionId: string, v: ChartView) {
  replayLoading.value = true
  try {
    const res = await stockSenseApi.replay(sessionId, userName.value, v)
    replayRecord.value = res.record
    replayChart.value = res.chart
  } catch {
    // 回放失败时清空图表，提示由请求拦截器给出
    replayChart.value = null
  } finally {
    replayLoading.value = false
  }
}

async function start() {
  busy.value = true
  try {
    const res = await stockSenseApi.start(userName.value)
    sid.value = res.session.session_id
    state.value = res.session
    chart.value = res.chart
    lines.value = res.session.lines || []
    drawMode.value = ''
    pendingPoints.value = []
    summary.value = null
    summaryVisible.value = false
    localStorage.setItem(SID_KEY + userName.value, sid.value)
  } catch {
    // 错误提示由请求拦截器统一给出
  } finally {
    busy.value = false
  }
}

async function onViewChange(v: string | number | boolean | undefined) {
  if (!sid.value || !state.value) return
  busy.value = true
  try {
    const res = await stockSenseApi.chart(sid.value, v as ChartView)
    chart.value = res.chart
    state.value = res.session
  } finally {
    busy.value = false
  }
}

/** 按周推进时同步切成周线，避免「点了按周K线形态没变」 */
async function onUnitChange(v: string | number | boolean | undefined) {
  if (!sid.value || !state.value) return
  const target: ChartView = v === 'week' ? 'week' : 'day'
  if (view.value === target) return
  view.value = target
  await onViewChange(target)
}

async function doStep() {
  busy.value = true
  try {
    const res = await stockSenseApi.step(sid.value, unit.value, view.value)
    state.value = res.session
    chart.value = res.chart
    if (res.summary) await finishUp(res.summary)
  } catch {
    // 错误提示由请求拦截器统一给出
  } finally {
    busy.value = false
  }
}

async function doTrade(action: 'buy' | 'sell') {
  busy.value = true
  try {
    const res = await stockSenseApi.trade(sid.value, action, ratio.value, view.value)
    state.value = res.session
    chart.value = res.chart
    lines.value = res.session.lines || lines.value
    ElMessage.success(`${action === 'buy' ? '买入' : '卖出'}成功（${ratioLabel(ratio.value)}仓位）`)
  } catch {
    // 错误提示由请求拦截器统一给出（后端 detail 会原样展示，如 T+1 限制）
  } finally {
    busy.value = false
  }
}

/** 仓位比例的显示名 */
function ratioLabel(v: number) {
  if (v >= 1) return '全部'
  if (Math.abs(v - 1 / 3) < 1e-6) return '1/3'
  if (Math.abs(v - 0.5) < 1e-6) return '1/2'
  if (Math.abs(v - 0.25) < 1e-6) return '1/4'
  return `${Math.round(v * 100)}%`
}

function chartInstance(): any {
  const c = chartRef.value
  return c?.chart || c?.getChart?.() || null
}

function setDrawMode(t: SenseLineType) {
  drawMode.value = drawMode.value === t ? '' : t
  pendingPoints.value = []
}

/** 取点：只在主图区域生效，坐标取鼠标位置（不是K线收盘价），锚点记成 训练区间序号 + 价格 */
function handlePointAt(px: number, py: number) {
  const tool = drawTools.find((x) => x.type === drawMode.value)
  if (!tool || !sid.value || state.value?.ended) return
  const inst = chartInstance()
  if (!inst || !inst.containPixel({ gridIndex: 0 }, [px, py])) return
  const pt = inst.convertFromPixel({ gridIndex: 0 }, [px, py]) as number[]
  if (!pt) return
  const idx = Math.round(pt[0])
  const bar = chart.value?.bars[idx]
  const price = Math.round(Number(pt[1]) * 1000) / 1000
  if (!bar || !(price > 0)) return
  pendingPoints.value = [...pendingPoints.value, { x: bar.no ?? idx + 1, price }]
  if (pendingPoints.value.length >= tool.anchors) void commitLine()
}

// 用 zrender 的点击（而不是 series 的 click），点K线之间的空白处也能取点
let zrBound: any = null
let zrHandler: ((e: any) => void) | null = null
function bindZrClick(retry = 0) {
  const inst = chartInstance()
  const zr = inst?.getZr?.()
  if (!zr) {
    if (retry < 20) setTimeout(() => bindZrClick(retry + 1), 200)
    return
  }
  // 同一个 zrender 实例只绑一次，避免反复绑定时重复取点
  if (zrBound === zr) return
  if (zrBound && zrHandler) zrBound.off('click', zrHandler)
  zrHandler = (e: any) => {
    if (!drawMode.value) return
    handlePointAt(e.offsetX, e.offsetY)
  }
  zrBound = zr
  zr.on('click', zrHandler)
}

watch(
  chart,
  () => {
    void nextTick(bindZrClick)
  },
  { immediate: true },
)

async function commitLine() {
  const type = drawMode.value
  if (!type) return
  const next: SenseLine[] = [
    ...lines.value,
    {
      type,
      points: pendingPoints.value.slice(),
      color: LINE_COLORS[lines.value.length % LINE_COLORS.length],
    },
  ]
  drawMode.value = ''
  pendingPoints.value = []
  await persistLines(next)
}

async function persistLines(next: SenseLine[]) {
  if (!sid.value) return
  const prev = lines.value
  lines.value = next
  try {
    const res = await stockSenseApi.saveLines(sid.value, next)
    lines.value = res.lines || next
  } catch {
    lines.value = prev
  }
}

async function undoLine() {
  if (!lines.value.length) return
  await persistLines(lines.value.slice(0, -1))
}

async function clearLines() {
  if (!lines.value.length) return
  await persistLines([])
}

async function doFinish() {
  // 会话已结束（回放走完或已结算）时，服务端会话已销毁，直接引导开始新一轮
  if (!sid.value || state.value?.ended) {
    ElMessage.info('本轮训练已结束，可点击「再来一轮」')
    return
  }
  busy.value = true
  try {
    const res = await stockSenseApi.finish(sid.value)
    state.value = res.session
    await finishUp(res.summary)
  } catch {
    // 错误提示由请求拦截器统一给出
  } finally {
    busy.value = false
  }
}

async function finishUp(s: SenseSummary) {
  summary.value = s
  summaryVisible.value = true
  localStorage.removeItem(SID_KEY + userName.value)
  sid.value = ''
  lines.value = []
  drawMode.value = ''
  pendingPoints.value = []
  await loadStats()
}

onMounted(async () => {
  await loadStats()
  // 刷新页面后排断：会话与划线都存后端，按本地记录的会话 id 恢复
  const saved = localStorage.getItem(SID_KEY + userName.value)
  if (!saved) return
  try {
    const res = await stockSenseApi.chart(saved, view.value)
    sid.value = saved
    state.value = res.session
    chart.value = res.chart
    lines.value = res.session.lines || []
  } catch {
    localStorage.removeItem(SID_KEY + userName.value)
  }
})
</script>

<style scoped>
.sense-page {
  padding: 18px 22px 28px;
  color: var(--text-primary, #1a1d2e);
}

.sense-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}

.title-block h2 {
  margin: 0 0 4px;
  font-size: 19px;
  font-weight: 600;
}

.title-block p {
  margin: 0;
  font-size: 12px;
  color: var(--text-secondary, #8a94a6);
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.sense-body {
  display: flex;
  gap: 16px;
  align-items: flex-start;
}

.chart-panel {
  flex: 1;
  min-width: 0;
  background: var(--bg-secondary, #ffffff);
  border: 1px solid var(--border-primary, #e4e7ed);
  border-radius: 10px;
  padding: 12px 14px 8px;
}

.chart-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  font-size: 12px;
  color: var(--text-secondary, #8a94a6);
  margin-bottom: 6px;
}

.meta-text {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
}

.draw-tools {
  display: flex;
  align-items: center;
  gap: 6px;
}

.draw-hint {
  font-size: 11px;
  color: var(--accent-primary, #637ee8);
  margin-right: 2px;
}

.trade-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  padding: 10px 0 2px;
  margin-top: 6px;
  border-top: 1px dashed var(--border-primary, #e4e7ed);
}

.trade-label {
  font-size: 12px;
  color: var(--text-secondary, #8a94a6);
}

.trade-divider {
  width: 1px;
  height: 20px;
  background: var(--border-primary, #e4e7ed);
}

.masked {
  color: var(--text-primary, #1a1d2e);
  font-weight: 500;
}

.revealed {
  color: var(--accent-primary, #637ee8);
  font-weight: 600;
}

.kline-chart {
  width: 100%;
  height: 520px;
  margin-top: 8px;
}

.chart-legend-tip {
  font-size: 11px;
  color: var(--text-secondary, #8a94a6);
  text-align: right;
}

.side-panel {
  width: 290px;
  flex: 0 0 290px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.card {
  background: var(--bg-secondary, #ffffff);
  border: 1px solid var(--border-primary, #e4e7ed);
  border-radius: 10px;
  padding: 12px 14px;
}

.card-title {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 10px;
  color: var(--text-primary, #1a1d2e);
}

.kv {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  padding: 4px 0;
  color: var(--text-secondary, #8a94a6);
}

.kv b {
  color: var(--text-primary, #1a1d2e);
  font-weight: 600;
}

.up {
  color: #ef232a !important;
}

.down {
  color: #14b143 !important;
}

.empty-tip {
  font-size: 12px;
  color: var(--text-secondary, #8a94a6);
  padding: 6px 0;
}

.trade-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  padding: 3px 0;
}

.tag-buy,
.tag-sell {
  display: inline-block;
  width: 20px;
  height: 18px;
  line-height: 18px;
  text-align: center;
  border-radius: 3px;
  font-size: 11px;
  color: #fff;
}

.tag-buy {
  background: #ef232a;
}

.tag-sell {
  background: #14b143;
}

.trade-date {
  color: var(--text-secondary, #8a94a6);
  flex: 1;
}

.stat-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.stat-grid > div {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 11px;
  color: var(--text-secondary, #8a94a6);
}

.stat-grid b {
  font-size: 14px;
  color: var(--text-primary, #1a1d2e);
}

.record-list {
  max-height: 180px;
  overflow-y: auto;
}

.record-list-wide {
  max-height: 62vh;
}

.record-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  font-size: 12px;
  padding: 5px 6px;
  border-radius: 4px;
  color: var(--text-secondary, #8a94a6);
  cursor: pointer;
  transition: background var(--transition-fast, 150ms);
}

.record-info {
  display: flex;
  flex-direction: column;
  min-width: 0;
  line-height: 1.4;
}

.record-name {
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.record-date {
  font-size: 11px;
  color: var(--text-tertiary, #9499a6);
  white-space: nowrap;
}

.record-side {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.record-return {
  text-align: right;
  white-space: nowrap;
}

.record-action {
  font-size: 11px;
  color: #409eff;
  white-space: nowrap;
}

.record-row:hover {
  background: var(--bg-tertiary, #f7f8fa);
  color: var(--text-primary, #1a1d2e);
}

.record-tip {
  font-size: 11px;
  color: var(--text-tertiary, #9499a6);
  margin-top: 6px;
}

.replay {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.replay-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 4px;
}

.replay-hint {
  font-size: 11px;
  color: var(--text-tertiary, #9499a6);
}

.replay-chart {
  width: 100%;
  min-height: 420px;
}

.replay .kline-chart {
  height: 420px;
  margin-top: 0;
}

.record-return {
  font-weight: 600;
}

.summary-reveal {
  display: grid;
  grid-template-columns: 60px 1fr 60px 1fr;
  gap: 8px;
  align-items: center;
  font-size: 13px;
  margin-bottom: 14px;
}

.reveal-label {
  color: var(--text-secondary, #8a94a6);
  font-size: 12px;
}

.summary-nums {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
  margin-bottom: 14px;
}

.summary-nums > div {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 11px;
  color: var(--text-secondary, #8a94a6);
  background: rgba(128, 128, 128, 0.08);
  border-radius: 6px;
  padding: 8px 10px;
}

.summary-nums b {
  font-size: 15px;
}

.forced-tip {
  font-size: 12px;
  color: #e6a23c;
  margin-bottom: 10px;
}

@media (max-width: 1080px) {
  .sense-body {
    flex-direction: column;
  }

  .side-panel {
    width: 100%;
    flex: 1 1 auto;
    flex-direction: row;
    flex-wrap: wrap;
  }

  .side-panel .card {
    flex: 1 1 260px;
  }
}
</style>
