<template>
  <div class="sense-page">
    <header class="sense-header page-card">
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
        <el-button v-else type="danger" :loading="busy" :disabled="!sid" @click="doFinish">结束训练</el-button>
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
            <el-button
              size="small"
              :type="adjustMode ? 'warning' : 'default'"
              :disabled="!lines.length || busy"
              @click="toggleAdjust"
            >
              微调
            </el-button>
            <el-button
              v-if="adjustMode"
              size="small"
              text
              :disabled="selectedLine === null || busy"
              @click="deleteSelectedLine"
            >
              删除选中线
            </el-button>
          </div>
        </div>
        <el-progress :percentage="progressPct" :show-text="false" :stroke-width="4" />
        <div class="kline-chart-scroll">
          <VChart ref="chartRef" class="kline-chart" :option="chartOption" autoresize @datazoom="onDataZoom" />
        </div>
        <div v-if="magnifier" class="magnifier">
          <div class="magnifier-title">
            局部放大 · 第{{ magnifier.no }}根 · {{ magnifier.price.toFixed(3) }}
          </div>
          <VChart class="magnifier-chart" :option="magnifierOption" autoresize />
        </div>
        <div class="chart-toolbar">
          <div class="indicator-toggles">
            <span class="trade-label">指标</span>
            <el-checkbox v-model="panels.ma" size="small">均线</el-checkbox>
            <el-checkbox v-model="panels.volume" size="small">成交量</el-checkbox>
            <el-checkbox v-model="panels.macd" size="small">MACD</el-checkbox>
          </div>
          <span class="chart-legend-tip">
            {{ legendTip }} · 空格/→ 下一根 · B 买 · S 卖 · P 自动播放 · 1/2/3 切周期 · H 建议点
          </span>
        </div>
        <div v-if="!state.ended" class="trade-bar">
          <span class="trade-label">仓位</span>
          <el-radio-group v-model="ratio" size="small" :disabled="busy">
            <el-radio-button :value="0.25">1/4</el-radio-button>
            <el-radio-button :value="1 / 3">1/3</el-radio-button>
            <el-radio-button :value="0.5">1/2</el-radio-button>
            <el-radio-button :value="1">全部</el-radio-button>
          </el-radio-group>
          <el-button type="danger" size="small" :loading="busy" :disabled="!state.can_buy" @click="doTrade('buy')">
            买入
          </el-button>
          <el-button type="success" size="small" :loading="busy" :disabled="!state.can_sell" @click="doTrade('sell')">
            卖出
          </el-button>
          <span class="trade-divider" />
          <!-- 播放类操作放在前段，高频的「下一根」独立放到末尾，避免夹在低频切换之间误触 -->
          <el-button
            size="small"
            :type="autoPlaying ? 'warning' : 'default'"
            :disabled="!state.can_step && !autoPlaying"
            @click="toggleAuto"
          >
            {{ autoPlaying ? '暂停' : '自动播放' }}
          </el-button>
          <el-radio-group v-model="speed" size="small">
            <el-radio-button :value="1200">慢</el-radio-button>
            <el-radio-button :value="600">中</el-radio-button>
            <el-radio-button :value="250">快</el-radio-button>
          </el-radio-group>
          <span class="trade-divider" />
          <el-radio-group v-model="unit" size="small" :disabled="busy" @change="onUnitChange">
            <el-radio-button value="day">按天</el-radio-button>
            <el-radio-button value="week">按周</el-radio-button>
          </el-radio-group>
          <el-button size="small" :loading="busy" :disabled="!state.can_step" @click="onManualStep">下一根</el-button>
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

    <el-dialog v-model="summaryVisible" title="训练结算" width="780px" :close-on-click-modal="false">
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

        <div v-if="summary.future && summary.future.bars" class="future-box">
          <div class="future-head">
            <span>训练区间之后的 {{ summary.future.bars }} 个交易日（{{ summary.future.start_date }} ~
              {{ summary.future.end_date }}）</span>
            <b :class="pnlClass(summary.future.change_pct)">{{ signed(summary.future.change_pct) }}%</b>
          </div>
          <VChart class="future-chart" :option="futureOption" autoresize />
          <div class="future-tip">浅色部分为后市，复盘图中以橙色竖线与训练区间分隔</div>
        </div>
        <div v-else-if="summary.future" class="empty-tip">该标的训练区间之后暂无行情数据</div>

        <SenseReviewPanel v-model:show-signals="showSuggestions" :review="summary.review" />

        <template v-if="summary.trades.length">
          <!-- 手机端：五列表格改为紧凑单行条目，避免横向滑动 -->
          <ul v-if="bp.isMobile.value" class="m-trade-list">
            <li class="m-trade-head">
              <span>方向</span><span>日期</span><span>价格</span><span>股数</span><span>费用</span>
            </li>
            <li v-for="(row, i) in summary.trades" :key="i">
              <span :class="row.action === 'BUY' ? 'tag-buy' : 'tag-sell'">
                {{ row.action === 'BUY' ? '买' : '卖' }}
              </span>
              <span>{{ row.date }}</span>
              <span class="m-trade-num">{{ row.price.toFixed(3) }}</span>
              <span class="m-trade-num">{{ row.shares }}</span>
              <span class="m-trade-num">{{ row.fee.toFixed(2) }}</span>
            </li>
          </ul>
          <div v-else class="responsive-table">
            <el-table :data="summary.trades" max-height="220">
              <el-table-column prop="action" label="方向" width="64">
                <template #default="{ row }">{{ row.action === 'BUY' ? '买入' : '卖出' }}</template>
              </el-table-column>
              <!-- 弹性列：结算弹窗内同样要铺满，全固定列会在右侧留一块空白 -->
              <el-table-column prop="date" label="日期" min-width="110" />
              <el-table-column prop="price" label="价格" width="96" align="right">
                <template #default="{ row }">{{ row.price.toFixed(3) }}</template>
              </el-table-column>
              <el-table-column prop="shares" label="股数" width="96" align="right" />
              <el-table-column prop="fee" label="费用" width="96" align="right">
                <template #default="{ row }">{{ row.fee.toFixed(2) }}</template>
              </el-table-column>
            </el-table>
          </div>
        </template>
      </div>
      <template #footer>
        <el-button v-if="summary" @click="replayCurrent">查看后续走势与复盘</el-button>
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
          你在 {{ replayRecord.end_date }} 结束训练；灰色虚线标出结束位置，橙色实线（{{
            replayRecord.window_end || replayRecord.end_date
          }}）之后是训练区间结束后的真实后市行情
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
          <el-switch v-model="showSuggestions" size="small" inline-prompt active-text="显示" inactive-text="隐藏" />
          <span class="replay-hint">建议点</span>
          <span class="replay-hint">
            B/S 为你的买卖点<template v-if="showSuggestions">，编号圆点为盘后总结的定向参考点</template>；
            橙色竖线与浅色K线是训练区间之后的后市
          </span>
          <span v-if="replayRecord.lines?.length" class="replay-hint">
            本轮划线 {{ replayRecord.lines.length }} 条
          </span>
        </div>

        <div v-loading="replayLoading" class="replay-chart">
          <VChart v-if="replayChart" class="kline-chart" :option="replayOption" autoresize />
        </div>

        <SenseReviewPanel v-model:show-signals="showSuggestions" :review="replayRecord.review" />

        <div class="card-title">逐笔交易</div>
        <template v-if="pairs.length">
          <!-- 手机端：九列配对表改为条目，避免横向滑动 -->
          <ul v-if="bp.isMobile.value" class="m-pair-list">
            <li v-for="(row, pi) in pairs" :key="pi" class="m-pair-row">
              <div class="m-pair-head">
                <span class="m-pair-range">{{ row.buy_date }} → {{ row.sell_date }}</span>
                <span class="m-pair-pnl" :class="pnlClass(row.pnl)">
                  {{ row.pnl > 0 ? '+' : '' }}{{ fmt(row.pnl) }}
                  <em :class="pnlClass(row.pnl_pct)">{{ signed(row.pnl_pct) }}%</em>
                </span>
              </div>
              <div class="m-pair-grid">
                <div><em>买入价</em><b>{{ row.buy_price.toFixed(3) }}</b></div>
                <div><em>卖出价</em><b>{{ row.sell_price.toFixed(3) }}</b></div>
                <div><em>股数</em><b>{{ row.shares }}</b></div>
                <div><em>持有</em><b>{{ row.days }}天</b></div>
              </div>
              <div v-if="row.forced" class="m-pair-tip">回放结束强制平仓</div>
            </li>
          </ul>
          <div v-else class="responsive-table">
            <el-table :data="pairs" max-height="240">
              <el-table-column prop="buy_date" label="买入日" width="110" />
              <el-table-column label="买入价" width="80" align="right">
                <template #default="{ row }">{{ row.buy_price.toFixed(3) }}</template>
              </el-table-column>
              <el-table-column prop="sell_date" label="卖出日" width="110" />
              <el-table-column label="卖出价" width="80" align="right">
                <template #default="{ row }">{{ row.sell_price.toFixed(3) }}</template>
              </el-table-column>
              <el-table-column prop="shares" label="股数" width="80" align="right" />
              <el-table-column label="盈亏" width="96" align="right">
                <template #default="{ row }">
                  <span :class="pnlClass(row.pnl)">{{ row.pnl > 0 ? '+' : '' }}{{ fmt(row.pnl) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="盈亏比" width="80" align="right">
                <template #default="{ row }">
                  <span :class="pnlClass(row.pnl_pct)">{{ signed(row.pnl_pct) }}%</span>
                </template>
              </el-table-column>
              <el-table-column prop="days" label="持有天数" width="80" align="right" />
              <el-table-column label="备注" min-width="160">
                <template #default="{ row }">{{ row.forced ? '回放结束强制平仓' : '—' }}</template>
              </el-table-column>
            </el-table>
          </div>
        </template>
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
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useBreakpoint } from '@/composables/useBreakpoint'
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
import SenseReviewPanel from '@/components/SenseReviewPanel.vue'
import { stockSenseApi } from '@/api/stockSense'
import type {
  ChartView,
  SenseChart,
  SenseLine,
  SenseLineType,
  SensePair,
  SenseReviewSignal,
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
const bp = useBreakpoint()
const userName = computed(() => userStore.userInfo?.username || 'default')

/** 当前训练会话 id 的本地记录，用于刷新页面后恢复训练（会话与划线都在后端） */
const SID_KEY = 'stock-sense-sid:'

/**
 * 用户捏合/拖动滑块后的可视K线根数，跨训练记住：下次开始训练按这个宽度显示。
 * 存根数而不是百分比——日/周/月切换、推进若干根之后每根K线的宽度都一样，
 * 存比例会在一年末把窗口撑到一半、K线又挤成一片。
 */
const ZOOM_BARS_KEY = 'stock-sense-zoom-bars:'
const MIN_ZOOM_BARS = 6
const MAX_ZOOM_BARS = 240
const userZoomBars = ref<number | null>(null)

function readZoomBars(): number | null {
  const raw = Number(localStorage.getItem(ZOOM_BARS_KEY + userName.value))
  return Number.isFinite(raw) && raw >= MIN_ZOOM_BARS && raw <= MAX_ZOOM_BARS ? Math.round(raw) : null
}

function saveZoomBars(bars: number) {
  const v = Math.round(bars)
  if (!Number.isFinite(v) || v < MIN_ZOOM_BARS || v > MAX_ZOOM_BARS) return
  if (userZoomBars.value === v) return
  userZoomBars.value = v
  localStorage.setItem(ZOOM_BARS_KEY + userName.value, String(v))
}

const busy = ref(false)
/** 自动播放的单步请求单独计数：不占用 busy，连续推进时按钮不会出现/消失 loading 图标 */
const stepping = ref(false)
let stepTask: Promise<boolean> | null = null
/** 任意会话请求进行中，用于手动操作与自动播放之间互斥 */
const inFlight = computed(() => busy.value || stepping.value)
const sid = ref('')
const state = ref<SenseState | null>(null)
const chart = ref<SenseChart | null>(null)
/** 训练图受控数据窗口（bars 下标）：随当前K线滑动，重渲染时保持不变 */
const zoomWin = ref<{ start: number; end: number } | null>(null)
const view = ref<ChartView>('day')
const unit = ref<StepUnit>('day')
const summary = ref<SenseSummary | null>(null)
const summaryVisible = ref(false)
const stats = ref<SenseStats | null>(null)

/** 本次交易使用的仓位比例 */
const ratio = ref(1)

/** 指标面板显隐，同时作用于主图与复盘图 */
const panels = reactive({ ma: true, volume: true, macd: true })
/** 盘后总结建议点（图上编号圆点 + 总结列表），关掉后复盘图只剩自己的 B/S 点 */
const showSuggestions = ref(true)
const autoPlaying = ref(false)
/** 自动播放每根K线之间的间隔（毫秒） */
const speed = ref(600)
let autoTimer: ReturnType<typeof setTimeout> | null = null

const legendTip = computed(() => {
  const parts: string[] = []
  if (panels.ma) parts.push(view.value === 'day' ? 'MA5 / MA10 / MA20 / MA60' : 'MA5 / MA10')
  if (panels.macd) parts.push('MACD(12,26,9)')
  parts.push('红涨绿跌')
  return parts.join(' · ')
})

// ─── 划线：锚点为「训练区间序号 + 价格」，随会话存在后端 ───
const chartRef = ref<any>(null)
const lines = ref<SenseLine[]>([])
const drawMode = ref<SenseLineType | ''>('')
const pendingPoints = ref<{ x: number; price: number }[]>([])
/** 微调模式：拖动已有划线的锚点，拖动时浮出局部放大K线 */
const adjustMode = ref(false)
const dragging = ref<{ line: number; point: number } | null>(null)
const magnifier = ref<{ idx: number; no: number; price: number } | null>(null)
const LINE_COLORS = ['#e6a23c', '#409eff', '#b18cf0', '#67c23a', '#f56c6c']
const drawTools: { type: SenseLineType; label: string; anchors: number }[] = [
  { type: 'hline', label: '水平', anchors: 1 },
  { type: 'trend', label: '趋势', anchors: 2 },
  { type: 'channel', label: '通道', anchors: 3 },
  { type: 'rect', label: '矩形', anchors: 2 },
  { type: 'fib', label: '斐波', anchors: 2 },
]

const drawHint = computed(() => {
  if (adjustMode.value) {
    return dragging.value
      ? '拖动中：右上角放大镜显示锚点附近的K线'
      : '微调：按住任一锚点拖动，松手自动保存'
  }
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

/** 训练区间序号 → 当前视图 bars 的下标（周/月视图取包含该序号的那根聚合K线） */
function anchorIndexIn(c: SenseChart, no: number): number {
  // 聚合K线的 no 是组内最后一根的序号，第一根 no 不小于目标的才是所属周期
  const idx = c.bars.findIndex((b) => (b.no ?? 0) >= no)
  return idx < 0 ? Math.max(0, c.bars.length - 1) : idx
}

interface ChartDecor {
  /** 后市第一根下标（回放用） */
  futureStart?: number
  /** 盘后总结的买卖参考点 */
  signals?: SenseReviewSignal[]
  /** 指标面板显隐，不传则全部显示 */
  panels?: { ma: boolean; volume: boolean; macd: boolean }
  /** 微调模式下显示可拖拽锚点 */
  anchorMode?: boolean
  activeAnchor?: { line: number; point: number } | null
  /** 受控数据窗口（bars 下标）；不传则显示整段 */
  zoom?: { start: number; end: number } | null
}

function buildChartOption(
  c: SenseChart | null,
  trades: SenseTrade[],
  endDate?: string,
  guides: SenseLine[] = [],
  pending: { x: number; price: number }[] = [],
  decor: ChartDecor = {},
) {
  if (!c || !c.bars.length) return {}
  const futureStart = decor.futureStart ?? c.future_start ?? -1
  const hasFuture = futureStart >= 0 && futureStart < c.bars.length
  const vis = decor.panels ?? { ma: true, volume: true, macd: true }
  // 主图固定占 grid 0，成交量/MACD 按显示顺序依次占后续 grid
  const subPanels: ('volume' | 'macd')[] = []
  if (vis.volume) subPanels.push('volume')
  if (vis.macd) subPanels.push('macd')
  const axisIdx = Array.from({ length: subPanels.length + 1 }, (_, i) => i)
  const volumeAxis = subPanels.indexOf('volume') + 1
  const macdAxis = subPanels.indexOf('macd') + 1
  // 视窗写进 option：每次重建 option 都带着同一窗口，买卖/推进不会跳回整段
  const zoomSpan = decor.zoom
    ? { startValue: decor.zoom.start, endValue: decor.zoom.end }
    : { start: 0, end: 100 }

  const rawDates = c.bars.map((b) => b.date)
  const dates = rawDates.map(dayLabel)
  const ohlc = c.bars.map((b) => [b.open, b.close, b.low, b.high])
  const colors = c.bars.map((b) => (b.close >= b.open ? '#ef232a' : '#14b143'))
  // 后市K线用淡色，与训练区间一眼可分（背景 + 竖线另在 markArea/markLine 中）
  const klineData: any[] = hasFuture
    ? ohlc.map((v, i) => i < futureStart ? v : {
        value: v,
        itemStyle: {
          color: '#f0a5a0', color0: '#9bd4b0',
          borderColor: '#f0a5a0', borderColor0: '#9bd4b0', opacity: 0.85,
        },
      })
    : ohlc
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
  const barIndexFor = (d: string, no?: number): number => {
    // 交易与参考点带训练区间序号时按序号锚定，不受日期脱敏/还原与周期聚合影响
    if (no !== undefined && no > 0) return anchorIndexIn(c, no)
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
    // 周/月视图首根聚合K线的日期是该组最后一个交易日，早于它的信号归到首根，
    // 否则区间开头的参考点会被丢掉
    return ans < 0 ? 0 : ans
  }
  for (const t of trades) {
    const i = barIndexFor(t.date, t.no)
    if (i < 0) continue
    marks.push({
      name: t.action === 'BUY' ? '买入' : '卖出',
      coord: [i, t.price],
      value: t.action === 'BUY' ? 'B' : 'S',
      itemStyle: { color: t.action === 'BUY' ? '#ef232a' : '#14b143' },
      symbol: 'pin',
      // 手机端图表宽度≈视口宽度，34px 的 pin 会把相邻K线的买卖点糊成一片
      symbolSize: bp.isMobile.value ? 20 : 26,
      label: { color: '#fff', fontSize: 11 },
    })
  }
  // 盘后总结的参考点：编号与总结面板一一对应
  for (const [n, s] of (decor.signals || []).entries()) {
    const i = barIndexFor(s.date, s.no)
    if (i < 0) continue
    marks.push({
      name: `参考点${n + 1}`,
      coord: [i, s.price],
      value: String(n + 1),
      symbol: 'circle',
      symbolSize: bp.isMobile.value ? 14 : 16,
      itemStyle: {
        color: s.action === 'buy' ? '#d81e06' : s.action === 'sell' ? '#0a9b45' : '#e6a23c',
        borderColor: '#fff',
        borderWidth: 1,
      },
      label: { color: '#fff', fontSize: 10, fontWeight: 'bold' },
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
  // 训练区间与后续走势的分界：竖线 + 后市背景，肉眼即可区分两段
  if (hasFuture) {
    markLineData.push({
      xAxis: futureStart - 0.5,
      lineStyle: { color: '#f59e0b', width: 2, type: 'solid' },
      label: {
        formatter: '训练区间结束 · 后市',
        color: '#fff',
        backgroundColor: '#d97706',
        padding: [2, 4],
        fontSize: 10,
        position: 'insideStartTop',
      },
    })
  }

  // 训练划线：锚点是训练区间序号，按当前视图的K线序号映射到索引
  const anchorIndex = (no: number): number => anchorIndexIn(c, no)
  const guideAreas: any[] = []
  if (hasFuture) {
    guideAreas.push([
      { xAxis: futureStart - 0.5, itemStyle: { color: 'rgba(245,158,11,0.09)' } },
      { xAxis: c.bars.length - 0.5 },
    ])
  }
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
      show: vis.ma,
      data: vis.ma ? Object.keys(c.ma).map((n) => n.toUpperCase()) : [],
      itemWidth: bp.isMobile.value ? 12 : 25,
      itemHeight: bp.isMobile.value ? 6 : 14,
      textStyle: { color: '#8a94a6', fontSize: bp.isMobile.value ? 9 : 11 },
    },
    tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
    // 手机端把价格轴的横向占位从 56px 压到 38px，把宽度让给 40 根K线
    grid: (subPanels.length === 2
      ? [
          { left: 56, right: 20, top: 30, height: '46%' },
          { left: 56, right: 20, top: '58%', height: '13%' },
          { left: 56, right: 20, top: '76%', height: '15%' },
        ]
      : subPanels.length === 1
        ? [
            { left: 56, right: 20, top: 30, height: '62%' },
            { left: 56, right: 20, top: '72%', height: '20%' },
          ]
        : [{ left: 56, right: 20, top: 30, height: '80%' }]
    ).map((g) => (bp.isMobile.value ? { ...g, left: 38, right: 6 } : g)),
    xAxis: axisIdx.map((i) => ({
      type: 'category',
      gridIndex: i,
      data: dates,
      boundaryGap: true,
      axisLine: { lineStyle: { color: '#2f3644' } },
      axisLabel: {
        show: i === axisIdx.length - 1,
        color: '#8a94a6',
        fontSize: bp.isMobile.value ? 9 : 10,
        ...(bp.isMobile.value ? { hideOverlap: true } : {}),
      },
      axisTick: { show: false },
      splitLine: { show: false },
    })),
    yAxis: [
      {
        scale: true,
        gridIndex: 0,
        splitLine: { lineStyle: { color: 'rgba(128,128,128,0.15)' } },
        axisLabel: { color: '#8a94a6', fontSize: bp.isMobile.value ? 9 : 10 },
      },
      ...subPanels.map((p, i) => ({
        scale: true,
        gridIndex: i + 1,
        splitNumber: 2,
        axisLabel: p === 'volume' ? { show: false } : { color: '#8a94a6', fontSize: bp.isMobile.value ? 9 : 10 },
        splitLine: { show: false },
      })),
    ],
    dataZoom: [
      { type: 'inside', xAxisIndex: axisIdx, ...zoomSpan },
      {
        type: 'slider', xAxisIndex: axisIdx,
        height: bp.isMobile.value ? 12 : 16,
        bottom: bp.isMobile.value ? 0 : 4,
        ...zoomSpan,
        showDetail: false,
      },
    ],
    series: [
      {
        name: 'K线',
        type: 'candlestick',
        data: klineData,
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
      ...(vis.ma ? maSeries : []),
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
      // 微调模式：把每条线的锚点画成可拖拽圆点（拖拽由 zrender 事件处理）
      ...(decor.anchorMode
        ? [{
            name: '可调整锚点',
            type: 'scatter',
            data: guides.flatMap((g, li) => g.points.map((p, pi) => {
              const active = decor.activeAnchor?.line === li && decor.activeAnchor?.point === pi
              return {
                value: [anchorIndex(p.x), p.price],
                symbolSize: active ? 15 : 10,
                itemStyle: {
                  color: g.color,
                  borderColor: active ? '#fff' : '#303133',
                  borderWidth: active ? 3 : 1,
                },
              }
            })),
            xAxisIndex: 0,
            yAxisIndex: 0,
            z: 12,
            silent: true,
            tooltip: { show: false },
          }]
        : []),
      ...(vis.volume
        ? [{
            name: '成交量',
            type: 'bar',
            xAxisIndex: volumeAxis,
            yAxisIndex: volumeAxis,
            data: c.bars.map((b, i) => ({
              value: b.volume,
              itemStyle: { color: colors[i], opacity: hasFuture && i >= futureStart ? 0.3 : 0.7 },
            })),
          }]
        : []),
      ...(vis.macd
        ? [
            {
              name: 'MACD',
              type: 'bar',
              xAxisIndex: macdAxis,
              yAxisIndex: macdAxis,
              data: c.macd.macd.map((v) => ({
                value: v,
                itemStyle: { color: v >= 0 ? '#ef232a' : '#14b143', opacity: 0.8 },
              })),
            },
            {
              name: 'DIF',
              type: 'line',
              xAxisIndex: macdAxis,
              yAxisIndex: macdAxis,
              data: c.macd.dif,
              showSymbol: false,
              lineStyle: { width: 1, color: '#e6a23c' },
              itemStyle: { color: '#e6a23c' },
            },
            {
              name: 'DEA',
              type: 'line',
              xAxisIndex: macdAxis,
              yAxisIndex: macdAxis,
              data: c.macd.dea,
              showSymbol: false,
              lineStyle: { width: 1, color: '#409eff' },
              itemStyle: { color: '#409eff' },
            },
          ]
        : []),
    ],
  }
}

const chartOption = computed(() =>
  buildChartOption(
    chart.value, state.value?.trades || [], undefined, lines.value, pendingPoints.value,
    { anchorMode: adjustMode.value, activeAnchor: dragging.value, panels, zoom: zoomWin.value },
  )
)
const replayOption = computed(() => {
  // 复盘按时间顺序看：视窗从训练区间开头起给一小段（整段压缩后 B/S、编号、结束线全糊在一起）；
  // 后续走势靠拖动滑块/捏合去看，不再默认停在末尾那段
  const total = replayChart.value?.bars?.length || 0
  const win = bp.isMobile.value ? 40 : 60
  return buildChartOption(
    replayChart.value,
    replayRecord.value?.trades || [],
    replayRecord.value?.end_date,
    replayRecord.value?.lines || [],
    [],
    {
      panels,
      zoom: total > win ? { start: 0, end: win - 1 } : null,
      // 图上只标有统计方向的点，编号与总结面板的定向列表一致；关掉开关后只剩自己的 B/S 点
      signals: showSuggestions.value
        ? (replayRecord.value?.review?.signals || []).filter((s) => s.action !== 'watch')
        : [],
    },
  )
})



/** 结算弹窗里的后市走势迷你图：以训练区间末收盘价为起点 */
const futureOption = computed(() => {
  const f = summary.value?.future
  if (!f || f.bars < 1) return {}
  const base = f.closes[0]
  return {
    animation: false,
    grid: { left: 44, right: 12, top: 12, bottom: 24 },
    xAxis: {
      type: 'category',
      data: f.dates,
      axisLabel: { color: '#8a94a6', fontSize: 9, interval: Math.max(0, Math.floor(f.dates.length / 5)) },
      axisLine: { lineStyle: { color: '#2f3644' } },
    },
    yAxis: {
      type: 'value', scale: true,
      axisLabel: { color: '#8a94a6', fontSize: 9 },
      splitLine: { lineStyle: { color: 'rgba(128,128,128,0.15)' } },
    },
    series: [{
      type: 'line', data: f.closes, smooth: false, showSymbol: false,
      lineStyle: { width: 2, color: f.change_pct >= 0 ? '#ef232a' : '#14b143' },
      areaStyle: { color: f.change_pct >= 0 ? 'rgba(239,35,42,0.12)' : 'rgba(20,177,67,0.12)' },
      markLine: {
        symbol: 'none', silent: true,
        data: [{ yAxis: base, lineStyle: { color: '#909399', type: 'dashed', width: 1 },
          label: { formatter: '训练末', color: '#909399', fontSize: 9 } }],
      },
    }],
  }
})

/** 微调时的局部放大镜：只取锚点附近 21 根K线，价格轴自适应，K线自然被放大 */
const MAGNIFIER_SPAN = 10
const magnifierOption = computed(() => {
  const m = magnifier.value
  const bars = chart.value?.bars
  if (!m || !bars?.length) return {}
  const from = Math.max(0, m.idx - MAGNIFIER_SPAN)
  const to = Math.min(bars.length, m.idx + MAGNIFIER_SPAN + 1)
  const part = bars.slice(from, to)
  const center = m.idx - from
  return {
    animation: false,
    grid: { left: 40, right: 8, top: 8, bottom: 18 },
    xAxis: {
      type: 'category', data: part.map((b, i) => dayLabel(b.date) + (i === center ? ' ●' : '')),
      axisLabel: { show: false }, axisTick: { show: false },
      axisLine: { lineStyle: { color: '#2f3644' } },
    },
    yAxis: {
      scale: true, axisLabel: { color: '#8a94a6', fontSize: 9 },
      splitLine: { lineStyle: { color: 'rgba(128,128,128,0.15)' } },
    },
    series: [{
      type: 'candlestick',
      data: part.map((b) => [b.open, b.close, b.low, b.high]),
      itemStyle: {
        color: '#ef232a', color0: '#14b143',
        borderColor: '#ef232a', borderColor0: '#14b143',
      },
      markLine: {
        symbol: 'none', silent: true, animation: false,
        data: [
          { xAxis: center, lineStyle: { color: '#409eff', type: 'dashed', width: 1 } },
          { yAxis: m.price, lineStyle: { color: '#409eff', type: 'dashed', width: 1 } },
        ],
      },
    }],
  }
})

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

/** 手动操作先接管：停掉自动播放并等正在飞的那一步结束，避免两个请求同时改同一会话 */
async function guardManual(): Promise<boolean> {
  stopAuto()
  if (stepTask) await stepTask
  return !inFlight.value
}

function canAutoStep(): boolean {
  return autoPlaying.value && !!sid.value && !state.value?.ended
    && !!state.value?.can_step && !summaryVisible.value
}

function stopAuto() {
  autoPlaying.value = false
  if (autoTimer !== null) {
    clearTimeout(autoTimer)
    autoTimer = null
  }
}

function toggleAuto() {
  if (autoPlaying.value) {
    stopAuto()
    return
  }
  if (inFlight.value || !sid.value || state.value?.ended || !state.value?.can_step) return
  autoPlaying.value = true
  void autoLoop()
}

/** 串行推进：等本次 step 返回再排下一根，结算/报错/暂停都会停下来 */
async function autoLoop() {
  if (!canAutoStep()) {
    stopAuto()
    return
  }
  stepTask = doStep(true)
  const ok = await stepTask
  stepTask = null
  if (!ok || !canAutoStep()) {
    stopAuto()
    return
  }
  autoTimer = setTimeout(() => {
    autoTimer = null
    void autoLoop()
  }, speed.value)
}

async function onManualStep() {
  if (!(await guardManual())) return
  await doStep()
}

/** 键盘快捷键：文本输入与弹窗内不拦截；弹窗里只保留建议点开关与停止播放 */
function onKeyDown(e: KeyboardEvent) {
  if (e.repeat || e.ctrlKey || e.altKey || e.metaKey) return
  const el = e.target as HTMLElement | null
  const tag = el?.tagName
  const typing = !!el && (
    el.isContentEditable || tag === 'TEXTAREA' || tag === 'SELECT'
    || (tag === 'INPUT' && !/^(radio|checkbox|button|submit|reset)$/i.test((el as HTMLInputElement).type))
  )
  if (typing) return
  const k = e.key.toLowerCase()
  if (summaryVisible.value || replayVisible.value || historyVisible.value) {
    if (k === 'h') {
      e.preventDefault()
      showSuggestions.value = !showSuggestions.value
    } else if (k === 'escape') {
      stopAuto()
    }
    return
  }
  if (!sid.value || state.value?.ended) return
  if (k === ' ' || k === 'arrowright') {
    e.preventDefault()
    void onManualStep()
  } else if (k === 'b' || k === 's') {
    e.preventDefault()
    void doTrade(k === 'b' ? 'buy' : 'sell')
  } else if (k === 'p') {
    e.preventDefault()
    toggleAuto()
  } else if (k === 'escape') {
    stopAuto()
  } else if (k === 'h') {
    e.preventDefault()
    showSuggestions.value = !showSuggestions.value
  } else if (k === '1' || k === '2' || k === '3') {
    e.preventDefault()
    const v: ChartView = k === '1' ? 'day' : k === '2' ? 'week' : 'month'
    if (view.value !== v) {
      view.value = v
      void onViewChange(v)
    }
  }
}

async function start() {
  if (!(await guardManual())) return
  busy.value = true
  try {
    const res = await stockSenseApi.start(userName.value)
    sid.value = res.session.session_id
    state.value = res.session
    resetViewWindow()
    chart.value = res.chart
    lines.value = res.session.lines || []
    drawMode.value = ''
    pendingPoints.value = []
    summary.value = null
    summaryVisible.value = false
    localStorage.setItem(SID_KEY + userName.value, sid.value)
    ensureCurrentBarVisible()
  } catch {
    // 错误提示由请求拦截器统一给出
  } finally {
    busy.value = false
  }
}

async function onViewChange(v: string | number | boolean | undefined) {
  if (!sid.value || !state.value || !(await guardManual())) return
  busy.value = true
  try {
    const res = await stockSenseApi.chart(sid.value, v as ChartView)
    chart.value = res.chart
    state.value = res.session
    // 切周/月线后 bars 数量变化，旧视窗下标失效：按记住的根数重新定位
    resetViewWindow()
    ensureCurrentBarVisible()
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

/** silent=true 是自动播放的单步：只置 stepping，不触发按钮 loading，操作条不会闪 */
async function doStep(silent = false): Promise<boolean> {
  if (inFlight.value || !sid.value || state.value?.ended || !state.value?.can_step) return false
  const flag = silent ? stepping : busy
  flag.value = true
  let ok = false
  try {
    const res = await stockSenseApi.step(sid.value, unit.value, view.value)
    state.value = res.session
    chart.value = res.chart
    ok = true
    if (res.summary) {
      await finishUp(res.summary)
      return false
    }
    // 规则7.5.4：下一根后自动前移视窗，保证当前K线可见
    ensureCurrentBarVisible()
  } catch {
    // 错误提示由请求拦截器统一给出
  } finally {
    flag.value = false
  }
  return ok
}

async function doTrade(action: 'buy' | 'sell') {
  if (!(await guardManual())) return
  busy.value = true
  try {
    const res = await stockSenseApi.trade(sid.value, action, ratio.value, view.value)
    state.value = res.session
    chart.value = res.chart
    lines.value = res.session.lines || lines.value
    // 买卖同样会整体替换图表数据，视窗必须跟着重算，否则缩回整段
    ensureCurrentBarVisible()
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

/**
 * 用户手势缩放（捏合 / 拖动滑块）后把窗口写回 option（zoomWin）：
 * 之后买卖、划线、微调、推进重建 option 时仍带着同一窗口，不再跳回整段。
 * 手势过程中不立刻改 option（会打断捏合），停手 160ms 后写回；按钮操作前会先 flush。
 */
let pendingZoom: { start: number; end: number } | null = null
let zoomTimer: ReturnType<typeof setTimeout> | undefined

function applyPendingZoom() {
  if (zoomTimer) {
    clearTimeout(zoomTimer)
    zoomTimer = undefined
  }
  if (!pendingZoom) return
  zoomWin.value = pendingZoom
  pendingZoom = null
}

/** 换标的/换周期时旧窗口下标作废，连同未落地的缩放一起清掉 */
function resetViewWindow() {
  if (zoomTimer) {
    clearTimeout(zoomTimer)
    zoomTimer = undefined
  }
  pendingZoom = null
  zoomWin.value = null
}

function onDataZoom(e: any) {
  const total = chart.value?.bars?.length || 0
  if (!total) return
  const b = e?.batch?.[0] || e
  let start = Number(b?.startValue)
  let end = Number(b?.endValue)
  // 部分渲染器只给百分比，按根数换算
  if (!Number.isFinite(start) || !Number.isFinite(end)) {
    start = Math.round(((Number(b?.start) || 0) / 100) * (total - 1))
    end = Math.round(((Number(b?.end) ?? 100) / 100) * (total - 1))
  }
  start = Math.max(0, Math.min(Math.round(start), total - 1))
  end = Math.max(start, Math.min(Math.round(end), total - 1))
  saveZoomBars(end - start + 1)
  const cur = zoomWin.value
  if (cur && cur.start === start && cur.end === end) return
  pendingZoom = { start, end }
  if (zoomTimer) clearTimeout(zoomTimer)
  zoomTimer = setTimeout(applyPendingZoom, 160)
}

/**
 * 规则7.5.4：保证当前K线可见，但**不重设用户缩放后的窗口宽度**。
 * - 当前根仍在窗口内：原样保留（买卖、划线、微调都不动视窗）
 * - 推进一根后当前根越出右边界：窗口整体右移一根，宽度不变
 * - 没有用户窗口时：按上次记住的根数（userZoomBars）恢复，没记录过则移动端 40 根、桌面整段
 */
function ensureCurrentBarVisible() {
  applyPendingZoom()
  const c = chart.value
  if (!c?.bars?.length) return
  const total = c.bars.length
  const current = Math.min(Math.max((state.value?.progress?.current ?? total) - 1, 0), total - 1)
  const prev = zoomWin.value
  if (prev && current >= prev.start && current <= prev.end) return
  const want = prev
    ? prev.end - prev.start + 1
    : (userZoomBars.value ?? (bp.isMobile.value ? 40 : total))
  const size = Math.min(want, total)
  if (size >= total) {
    zoomWin.value = null
    return
  }
  let start = current - size + 1
  if (start < 0) start = 0
  zoomWin.value = { start, end: start + size - 1 }
}

function setDrawMode(t: SenseLineType) {
  adjustMode.value = false
  drawMode.value = drawMode.value === t ? '' : t
  pendingPoints.value = []
}

const selectedLine = ref<number | null>(null)
let dragSnapshot: SenseLine[] | null = null

function toggleAdjust() {
  adjustMode.value = !adjustMode.value
  drawMode.value = ''
  pendingPoints.value = []
  if (!adjustMode.value) {
    dragging.value = null
    magnifier.value = null
    selectedLine.value = null
  }
}

/** 找出鼠标附近 18px 内的划线锚点（锚点好抓，周线视图也不会点空） */
type AnchorHit = { line: number; point: number; idx: number }
function nearestAnchor(px: number, py: number): AnchorHit | null {
  const inst = chartInstance()
  const c = chart.value
  if (!inst || !c) return null
  let best: AnchorHit | null = null
  let dist = 18
  lines.value.forEach((g, li) => g.points.forEach((p, pi) => {
    const idx = anchorIndexIn(c, p.x)
    const pix = inst.convertToPixel({ gridIndex: 0 }, [idx, p.price])
    if (!pix) return
    const d = Math.hypot(pix[0] - px, pix[1] - py)
    if (d < dist) {
      dist = d
      best = { line: li, point: pi, idx }
    }
  }))
  return best
}

function startDrag(px: number, py: number) {
  const hit = nearestAnchor(px, py)
  if (!hit || state.value?.ended) return
  dragSnapshot = JSON.parse(JSON.stringify(lines.value)) as SenseLine[]
  dragging.value = { line: hit.line, point: hit.point }
  selectedLine.value = hit.line
  const p = lines.value[hit.line].points[hit.point]
  magnifier.value = { idx: hit.idx, no: p.x, price: p.price }
}

function moveDrag(px: number, py: number) {
  const d = dragging.value
  const inst = chartInstance()
  const c = chart.value
  if (!d || !inst || !c || !inst.containPixel({ gridIndex: 0 }, [px, py])) return
  const pt = inst.convertFromPixel({ gridIndex: 0 }, [px, py]) as number[]
  if (!pt) return
  const idx = Math.max(0, Math.min(c.bars.length - 1, Math.round(pt[0])))
  const bar = c.bars[idx]
  const price = Math.round(Number(pt[1]) * 1000) / 1000
  if (!bar || !(price > 0)) return
  const no = bar.no ?? idx + 1
  // 拖动过程中只更新本地视图，松手才落库，避免每个 mousemove 都打接口
  lines.value = lines.value.map((g, li) => li === d.line
    ? { ...g, points: g.points.map((p, pi) => pi === d.point ? { x: no, price } : p) }
    : g)
  magnifier.value = { idx, no, price }
}

function endDrag() {
  if (!dragging.value) return
  const next = lines.value
  dragging.value = null
  magnifier.value = null
  if (dragSnapshot) {
    lines.value = dragSnapshot
    dragSnapshot = null
  }
  void persistLines(next)
}

function deleteSelectedLine() {
  if (selectedLine.value === null) return
  const idx = selectedLine.value
  selectedLine.value = null
  void persistLines(lines.value.filter((_, i) => i !== idx))
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

// 用 zrender 事件（而不是 series 的 click）：K线之间的空白天区也能取点，
// 微调模式下同一套事件负责锚点拖拽。同一个 zrender 实例只绑一次，避免重复触发。
let zrBound: any = null
const zrHandlers: { name: string; fn: (e: any) => void }[] = []
function bindZrEvents(retry = 0) {
  const zr = chartInstance()?.getZr?.()
  if (!zr) {
    if (retry < 20) setTimeout(() => bindZrEvents(retry + 1), 200)
    return
  }
  if (zrBound === zr) return
  if (zrBound) zrHandlers.forEach((h) => zrBound.off(h.name, h.fn))
  zrHandlers.length = 0
  const add = (name: string, fn: (e: any) => void) => {
    zr.on(name, fn)
    zrHandlers.push({ name, fn })
  }
  add('click', (e: any) => {
    if (!drawMode.value || adjustMode.value) return
    handlePointAt(e.offsetX, e.offsetY)
  })
  add('mousedown', (e: any) => {
    if (adjustMode.value) startDrag(e.offsetX, e.offsetY)
  })
  add('mousemove', (e: any) => {
    if (adjustMode.value && dragging.value) moveDrag(e.offsetX, e.offsetY)
  })
  add('mouseup', () => { if (dragging.value) endDrag() })
  zrBound = zr
}

watch(
  chart,
  () => { void nextTick(bindZrEvents) },
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
  if (!sid.value || !(await guardManual())) return
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
  if (!(await guardManual())) return
  busy.value = true
  try {
    const res = await stockSenseApi.finish(sid.value, view.value)
    state.value = res.session
    chart.value = res.chart
    await finishUp(res.summary)
  } catch {
    // 错误提示由请求拦截器统一给出
  } finally {
    busy.value = false
  }
}

async function finishUp(s: SenseSummary) {
  stopAuto()
  summary.value = s
  summaryVisible.value = true
  localStorage.removeItem(SID_KEY + userName.value)
  sid.value = ''
  lines.value = []
  drawMode.value = ''
  pendingPoints.value = []
  adjustMode.value = false
  dragging.value = null
  magnifier.value = null
  selectedLine.value = null
  await loadStats()
}

// 鼠标在图表外松开时也要结束拖拽，否则锚点会一直跟着鼠标
const onWindowMouseUp = () => { if (dragging.value) endDrag() }

onMounted(async () => {
  window.addEventListener('mouseup', onWindowMouseUp)
  window.addEventListener('keydown', onKeyDown)
  userZoomBars.value = readZoomBars()
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
    ensureCurrentBarVisible()
  } catch {
    localStorage.removeItem(SID_KEY + userName.value)
  }
})

onUnmounted(() => {
  stopAuto()
  if (zoomTimer) clearTimeout(zoomTimer)
  window.removeEventListener('mouseup', onWindowMouseUp)
  window.removeEventListener('keydown', onKeyDown)
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
  position: relative;
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
  color: var(--accent-primary, #4051E0);
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

/* busy 时 Element Plus 会插入 14px 的 loading 图标并给文字加 6px 左边距，
   按钮随之变宽 20px，连续点「下一根」会让操作条抖动。
   loading 态的按钮是 relative，把图标叠到左侧内边距上即可保持宽度不变。 */
.sense-page :deep(.el-button.is-loading > .el-icon.is-loading) {
  position: absolute;
  left: 1px;
  margin: 0;
}

.sense-page :deep(.el-button.is-loading > .el-icon.is-loading + span) {
  margin-left: 0;
}

.masked {
  color: var(--text-primary, #1a1d2e);
  font-weight: 500;
}

.revealed {
  color: var(--accent-primary, #4051E0);
  font-weight: 600;
}

.kline-chart {
  width: 100%;
  height: 520px;
  margin-top: 8px;
}

/* 微调时浮在图表右上角的局部放大镜 */
.magnifier {
  position: absolute;
  top: 52px;
  right: 26px;
  z-index: 5;
  width: 330px;
  padding: 6px 8px 4px;
  border: 1px solid var(--accent-primary);
  border-radius: var(--radius-lg);
  background: var(--bg-secondary, #ffffff);
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.18);
  pointer-events: none;
}

.magnifier-title {
  font-size: 11px;
  color: #409eff;
  margin-bottom: 2px;
}

.magnifier-chart {
  width: 100%;
  height: 180px;
}

.future-box {
  margin: 10px 0;
  padding: 8px 10px;
  border: 1px solid var(--border-primary, #e4e7ed);
  border-radius: 8px;
}

.future-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
  color: var(--text-secondary, #8a94a6);
}

.future-head b {
  font-size: 15px;
}

.future-chart {
  width: 100%;
  height: 130px;
}

.future-tip {
  font-size: 11px;
  color: var(--text-tertiary, #9499a6);
}

.chart-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
  margin-top: 2px;
}

.indicator-toggles {
  display: flex;
  align-items: center;
  gap: 10px;
}

/* 勾选框自带的右外边距交给 flex gap 统一控制 */
.chart-toolbar :deep(.el-checkbox) {
  margin-right: 0;
  height: 22px;
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
  padding: 16px 0;
  border-bottom: 1px solid var(--border-primary);
}

.card-title {
  font-size: 15px;
  font-weight: 600;
  margin-bottom: 10px;
  color: var(--text-primary);
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
  transition: background-color var(--dur-fast) var(--ease);
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

/* ─── 手机端：逐笔交易配对条目（替代九列表格的横向滑动） ─── */
.m-pair-list {
  list-style: none;
  margin: 0;
  padding: 0;
}

.m-pair-row {
  padding: 8px 0;
  border-bottom: 1px solid var(--border-subtle, var(--border-primary, #e4e7ed));
  font-size: 12px;
}

.m-pair-row:last-child {
  border-bottom: none;
}

.m-pair-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
}

.m-pair-range {
  min-width: 0;
  font-size: 11px;
  color: var(--text-secondary, #8a94a6);
  font-family: var(--font-mono, monospace);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.m-pair-pnl {
  flex: none;
  font-weight: 600;
  font-family: var(--font-mono, monospace);
}

.m-pair-pnl em {
  margin-left: 6px;
  font-style: normal;
  font-size: 11px;
}

.m-pair-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 4px;
  margin-top: 5px;
}

.m-pair-grid > div {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
  padding: 4px 5px;
  background: var(--bg-tertiary, #f5f6f8);
  border-radius: 4px;
}

.m-pair-grid em {
  font-style: normal;
  font-size: 9px;
  color: var(--text-tertiary, #9499a6);
}

.m-pair-grid b {
  font-size: 11px;
  font-weight: 600;
  font-family: var(--font-mono, monospace);
}

.m-pair-tip {
  margin-top: 4px;
  font-size: 10px;
  color: var(--text-tertiary, #9499a6);
}

/* ─── 手机端：结算弹窗的平铺成交流水（五列压成一行） ─── */
.m-trade-list {
  list-style: none;
  margin: 0;
  padding: 0;
  font-size: 11px;
  font-family: var(--font-mono, monospace);
}

.m-trade-list li {
  display: grid;
  grid-template-columns: 24px minmax(0, 1fr) 54px 38px 44px;
  gap: 6px;
  align-items: center;
  padding: 5px 0;
  border-bottom: 1px solid var(--border-subtle, var(--border-primary, #e4e7ed));
}

.m-trade-list li:last-child {
  border-bottom: none;
}

.m-trade-list .m-trade-head {
  font-size: 9px;
  color: var(--text-tertiary, #9499a6);
  padding-bottom: 3px;
}

.m-trade-num {
  text-align: right;
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

@media (max-width: 768px) {
  /* 绘图工具区：提示独占整行，按钮横向排列可换行，杜绝竖排错乱 */
  .draw-tools {
    flex-wrap: wrap;
    width: 100%;
    gap: 8px;
  }
  .draw-hint {
    flex: 1 1 100%;
    line-height: 1.5;
    white-space: normal;
  }
  .draw-tools :deep(.el-button-group) {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    width: 100%;
    .el-button {
      flex: 1 1 auto;
      margin-left: 0 !important;
      border-radius: 4px !important;
    }
  }
  .draw-tools :deep(.el-button) { margin-left: 0; }

  /* 元信息分行展示 */
  .meta-text { flex-direction: column; gap: 4px; }

  /* 移动端：K线宽度贴合视口，可视窗口由 dataZoom 控制（见 ensureCurrentBarVisible） */
  .kline-chart-scroll {
    width: 100%;
    max-width: 100%;
    overflow: hidden;
  }
  .kline-chart { height: 320px; width: 100%; max-width: 100%; }
  .replay .kline-chart { height: 280px; width: 100%; }
  /* 容器高度必须跟着图表一起降：.replay-chart 桌面 min-height 420，只改图表 280
     就会在图表与盘后总结之间留出 140px 空白 */
  .replay-chart { min-height: 280px; }

  /* 局部放大镜收窄到视口内 */
  .magnifier {
    width: calc(100vw - 48px);
    max-width: 330px;
    right: 12px;
  }

  /* 指标开关与快捷键提示分行 */
  .chart-toolbar { flex-direction: column; align-items: flex-start; }
  .chart-legend-tip { text-align: left; line-height: 1.5; }

  /* 复盘长文区：允许换行，避免横向溢出 */
  .replay :deep(p), .replay :deep(.summary-reveal) { overflow-wrap: anywhere; word-break: break-word; }
  .summary-reveal { grid-template-columns: 1fr !important; }
}

@media (max-width: 480px) {
  /* 页面自身不再叠加内边距，避免与全局 10px 双重留白 */
  .sense-page { padding: 0; }
  .kline-chart { height: 300px; }

  .sense-header,
  .chart-panel {
    padding: 10px;
    border-radius: 8px;
  }
  .sense-header { flex-direction: column; gap: 8px; margin-bottom: 8px; }
  .title-block {
    h2 { font-size: 16px; margin-bottom: 0; }
    p { display: none; }
  }
  .header-actions {
    width: 100%;
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 6px;

    .el-button { width: 100%; margin-left: 0 !important; }
  }

  .chart-meta { font-size: 10px; gap: 6px; margin-bottom: 4px; }
  .meta-text { gap: 4px 8px; }
  .draw-tools { gap: 4px; }
  .draw-hint { font-size: 9px; }

  /* 交易栏：从单行长条改为 4 行网格，主操作占满整行，符合触屏点击习惯 */
  .trade-bar {
    display: grid;
    grid-template-columns: repeat(6, minmax(0, 1fr));
    gap: 6px;
    padding-top: 8px;
    margin-top: 4px;

    .trade-label,
    .trade-divider { display: none; }
  }
  .trade-bar > :deep(.el-button) { width: 100%; margin-left: 0 !important; grid-column: span 3; }

  /* 卡在本文件的坑：本组件的样式块是纯 CSS（无 lang="scss"），浏览器原生嵌套不参与
     作用域改写，把 :deep() 写进 .a { } 内部会编译成 ".a[data-v] [data-v] .b"（双 data-v
     后代选择器），永远匹配不到，规则静默失效。所以本文件所有 :deep() 一律写在顶层。
     分段选择器必须显式跨 3 列：el-radio-group 是 inline-flex，宽度会塌缩成内容宽（53px），
     "按天/按周"、"慢/中/快" 因此被挤成竖排。 */
  .header-actions :deep(.el-radio-group) { grid-column: 1 / -1; display: flex; min-width: 0; }
  .header-actions :deep(.el-radio-button) { flex: 1 1 0; min-width: 0; }
  .header-actions :deep(.el-radio-button__inner) { width: 100%; }
  .trade-bar > :deep(.el-radio-group) { display: flex; min-width: 0; grid-column: span 3; }
  .trade-bar > :deep(.el-radio-group):first-of-type { grid-column: span 6; }
  .trade-bar :deep(.el-radio-button) { flex: 1 1 0; min-width: 0; }
  /* 控件尺寸（高 36 / 内边距 0 8 / 字号 12）由 mobile.scss 的分段规范统一，这里只管铺满 */
  .trade-bar :deep(.el-radio-button__inner) { width: 100%; }

  /* 划线工具：5 个工具用 6 列栅格排版 —— 第一行 3 个各占 2 列、第二行 2 个各占 3 列。
     原先用 flex 换行 + flex:1 1 30%，两行各自的伸缩基数不同，第一行整体比第二行
     右移 4px（113×3 / 171×2），左右边距对不齐。
     这里必须逐个指定 grid-area 而不用 span 自动排布：组内存在占位元素时，
     首行会被顶到第 2 列开始，反而把 3 个按钮挤成 2 行。 */
  .draw-tools :deep(.el-button-group) {
    display: grid;
    grid-template-columns: repeat(6, minmax(0, 1fr));
    gap: 4px;
  }
  .draw-tools :deep(.el-button-group > .el-button) {
    margin-left: 0 !important;
    font-size: 11px;
  }
  .draw-tools :deep(.el-button-group > .el-button:nth-child(1)) { grid-area: 1 / 1 / 2 / 3; }
  .draw-tools :deep(.el-button-group > .el-button:nth-child(2)) { grid-area: 1 / 3 / 2 / 5; }
  .draw-tools :deep(.el-button-group > .el-button:nth-child(3)) { grid-area: 1 / 5 / 2 / 7; }
  .draw-tools :deep(.el-button-group > .el-button:nth-child(4)) { grid-area: 2 / 1 / 3 / 4; }
  .draw-tools :deep(.el-button-group > .el-button:nth-child(5)) { grid-area: 2 / 4 / 3 / 7; }

  .chart-toolbar { gap: 4px; }
  .chart-legend-tip { display: none; }
  .indicator-toggles { gap: 2px; }
  .indicator-toggles :deep(.el-checkbox) { margin-right: 8px; }

  .side-panel { gap: 8px; }
  .side-panel .card { padding: 8px 0; }
  .card-title { font-size: 12px; }
  .kv { font-size: 11px; padding: 3px 0; }
  .trade-row { font-size: 10px; }

  /* 规则7.5.2：抽屉全宽、内容单列；规则7.5.1：字号压到12px */
  :deep(.el-drawer) { width: 100vw !important; }
  :deep(.el-drawer__body) { padding: 12px; }
  .stat-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .stat-grid b { font-size: 16px; }
  .record-row { font-size: 12px; }
  .record-return { font-size: 13px; }
  .summary-reveal { font-size: 12px; }
  .summary-nums { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  /* 复盘的周期按钮与开关横向排列，禁止竖排 */
  .replay-toolbar { flex-wrap: wrap; gap: 8px; }
  .shape-box { font-size: 12px; }
}
</style>
