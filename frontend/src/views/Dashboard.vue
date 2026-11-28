<template>
  <div class="dashboard">
    <!-- Stat Cards -->
    <div class="stat-grid">
      <div v-for="stat in stats" :key="stat.label" class="stat-card">
        <div class="stat-icon" :style="{ background: stat.bgColor, color: stat.color }">
          <el-icon :size="22"><component :is="stat.icon" /></el-icon>
        </div>
        <div class="stat-body">
          <div class="stat-value">{{ stat.value }}</div>
          <div class="stat-label">{{ stat.label }}</div>
        </div>
      </div>
    </div>

    <div class="dashboard-grid">
      <!-- Heatmap -->
      <div class="page-card heatmap-card" v-loading="heatmapLoading">
        <div class="card-header">
          <span class="card-title">板块资金流向热力图</span>
          <el-radio-group v-model="heatmapPeriod" size="small">
            <el-radio-button value="5d">5日</el-radio-button>
            <el-radio-button value="10d">10日</el-radio-button>
            <el-radio-button value="20d">20日</el-radio-button>
          </el-radio-group>
        </div>
        <v-chart :option="heatmapOption" class="heatmap-chart" autoresize />
      </div>

      <!-- Today's Signals -->
      <div class="page-card signals-card">
        <div class="card-header">
          <span class="card-title">今日策略信号</span>
          <el-select v-model="currentStrategy" size="small" style="width: 120px">
            <el-option v-for="o in STRATEGY_OPTIONS" :key="o.value" :label="o.label" :value="o.value" />
          </el-select>
        </div>
        <div class="signal-list">
          <div v-for="signal in todaySignals" :key="signal.id" class="signal-item">
            <div class="signal-top">
              <span class="sector-name">{{ signal.sector_name }}</span>
              <span class="signal-direction" :class="signal.direction === 'BUY' ? 'signal-buy' : 'signal-sell'">
                {{ signal.direction === 'BUY' ? '买入' : '卖出' }}
              </span>
            </div>
            <div class="signal-meta">
              <span v-if="signal.etf_code" class="meta-tag">{{ signal.etf_code }} {{ signal.etf_name }}</span>
              <span>评分 {{ signal.score?.toFixed(2) }}</span>
              <span>仓位 {{ ((signal.position_ratio || 0) * 100).toFixed(1) }}%</span>
            </div>
          </div>
          <div v-if="todaySignals.length === 0" class="signal-empty">
            <el-icon :size="36" color="var(--text-tertiary)"><Bell /></el-icon>
            <p>今日暂无信号</p>
          </div>
        </div>
      </div>
    </div>

    <!-- Calendar -->
    <div class="page-card">
      <div class="card-header calendar-header">
        <span class="card-title">策略信号日历</span>
        <el-date-picker v-model="calendarMonth" type="month" placeholder="选择月份" size="small" value-format="YYYY-MM" class="calendar-picker" />
      </div>
      <v-chart :option="calendarOption" class="calendar-chart" autoresize @click="handleCalendarClick" />
    </div>

    <!-- AI Panels -->
    <div class="dashboard-grid" style="margin-top: 0">
      <AiAnalysisPanel :strategy-type="currentStrategy" />
      <RiskAlertPanel ref="riskPanel" />
    </div>

    <!-- Signal Detail Dialog -->
    <el-dialog v-model="signalDialogVisible" :title="`${selectedDate} 信号详情`" width="640px" class="signal-dialog" :style="{ '--dialog-max-h': 'min(75vh, 600px)' }">
      <div class="signal-dialog-body">
        <!-- 空仓/清仓状态必须显式标注，避免"无信号"被误解为"没计算" -->
        <el-alert
          v-if="selectedDateIsEmpty || selectedDateSignals.length === 0"
          type="info"
          :closable="false"
          show-icon
          style="margin-bottom: 12px"
          title="该交易日空仓"
          :description="selectedDateIsEmpty ? selectedDateEmptyReason : '当日未生成任何持仓信号（可能为市场转弱触发空仓，或信号已重新计算）。'"
        />
        <el-alert
          v-else-if="selectedDateIsClear"
          type="warning"
          :closable="false"
          show-icon
          style="margin-bottom: 12px"
          title="已清仓"
          :description="`当日信号为清仓卖出，持仓已全部离场（${selectedDateClearReason}）`"
        />

        <!-- 手机端：五列表格在 390px 下必然被挤压，改为两行信息块 -->
        <ul v-if="bp.isMobile.value" class="m-signal-list">
          <li v-for="(row, ri) in selectedDateSignals" :key="ri" class="m-signal-row">
            <div class="m-row-head">
              <span class="m-row-name">{{ row.sector_name }}</span>
              <el-tag v-if="isClearSignal(row)" type="warning" size="small">清仓</el-tag>
              <span v-else :class="row.direction === 'BUY' ? 'signal-buy' : 'signal-sell'">
                {{ row.direction === 'BUY' ? '买入' : '卖出' }}
              </span>
            </div>
            <div class="m-row-meta">
              <span>{{ row.etf_code || '—' }}</span>
              <span>评分 {{ row.score != null ? row.score.toFixed(2) : '—' }}</span>
              <span>仓位 {{ ((row.position_ratio || 0) * 100).toFixed(1) }}%</span>
            </div>
          </li>
        </ul>

        <div v-else class="responsive-table">
          <el-table :data="selectedDateSignals" max-height="200">
            <el-table-column prop="sector_name" label="板块" />
            <el-table-column prop="direction" label="方向">
              <template #default="{ row }">
                <el-tag v-if="isClearSignal(row)" type="warning" size="small">清仓</el-tag>
                <span v-else :class="row.direction === 'BUY' ? 'signal-buy' : 'signal-sell'">
                  {{ row.direction === 'BUY' ? '买入' : '卖出' }}
                </span>
              </template>
            </el-table-column>
            <el-table-column prop="etf_code" label="ETF" />
            <el-table-column prop="score" label="评分" align="right">
              <template #default="{ row }">{{ row.score?.toFixed(2) ?? '—' }}</template>
            </el-table-column>
            <el-table-column prop="position_ratio" label="仓位" align="right">
              <template #default="{ row }">{{ ((row.position_ratio || 0) * 100).toFixed(1) }}%</template>
            </el-table-column>
          </el-table>
        </div>

        <!-- AI 分析回放：信号已清空/清仓时，历史解读必须标注为快照，避免误导 -->
        <div v-if="selectedAnalysis.length > 0" class="analysis-section">
          <div class="analysis-title">
            AI 分析回放
            <el-tag v-if="selectedDateStaleAnalysis" type="warning" size="small" style="margin-left: 8px">
              历史快照
            </el-tag>
          </div>
          <el-alert
            v-if="selectedDateStaleAnalysis"
            type="warning"
            :closable="false"
            show-icon
            style="margin-bottom: 8px"
            :title="(selectedDateSignals.length === 0 || selectedDateIsEmpty) ? '该交易日已空仓，以下为历史分析快照' : '信号已变更，以下为历史分析快照'"
            description="仅作回顾参考，不可作为当前持仓依据。"
          />
          <div v-for="(a, idx) in selectedAnalysis" :key="idx" class="analysis-card">
            <div class="analysis-header">
              <span class="analysis-sector">{{ a.sector_name }} ({{ a.direction === 'BUY' ? '买入' : '卖出' }})</span>
              <span class="analysis-conf">信心度 {{ (a.confidence * 100).toFixed(0) }}%</span>
            </div>
            <div class="analysis-text">{{ a.interpretation }}</div>
            <div v-if="a.risk_factors?.length" class="analysis-risks">
              <div v-for="(r, ri) in a.risk_factors" :key="ri">- {{ r }}</div>
            </div>
            <div v-if="a.suggestion" class="analysis-suggest">建议: {{ a.suggestion }}</div>
          </div>
        </div>
        <div v-else-if="analysisLoading" class="analysis-empty">加载AI分析中...</div>
        <div v-else-if="selectedDateSignals.length > 0 || selectedDateIsEmpty" class="analysis-empty">该日期暂无AI分析记录</div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { HeatmapChart, ScatterChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, VisualMapComponent, CalendarComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import dayjs from 'dayjs'
import { signalApi } from '@/api/signal'
import { fundApi } from '@/api/fund'
import { settingsApi } from '@/api/settings'
import { aiApi } from '@/api/ai'
import AiAnalysisPanel from '@/components/AiAnalysisPanel.vue'
import RiskAlertPanel from '@/components/RiskAlertPanel.vue'
import { useThemeStore } from '@/stores/theme'
import { useStrategyStore, STRATEGY_OPTIONS } from '@/stores/strategy'
import { useBreakpoint } from '@/composables/useBreakpoint'
import { useTradeCalendar } from '@/composables/useTradeCalendar'
import { CAL_DATE_FONT, calendarItemStyle, calendarLabelBase, calendarSurfaceColor, calendarCellPalette, calendarEmphasisItemStyle } from '@/utils/calendarStyle'
import { storeToRefs } from 'pinia'
import type { TradeSignal } from '@/api/signal'

const bp = useBreakpoint()
const { ensureTradeDates, isTradeDay } = useTradeCalendar()

use([HeatmapChart, ScatterChart, GridComponent, TooltipComponent, VisualMapComponent, CalendarComponent, LegendComponent, CanvasRenderer])

const themeStore = useThemeStore()

// 全局策略：与头部选择器、其他页面共用同一状态
const strategyStore = useStrategyStore()
const { currentStrategy } = storeToRefs(strategyStore)

const heatmapPeriod = ref('5d')
const calendarMonth = ref(dayjs().format('YYYY-MM'))
const todaySignals = ref<TradeSignal[]>([])

const stats = ref([
  { label: '总资产', value: '--', icon: 'Wallet', color: 'var(--accent-primary)', bgColor: 'var(--accent-primary-light)' },
  { label: '今日盈亏', value: '--', icon: 'TrendCharts', color: 'var(--accent-success)', bgColor: 'var(--accent-success-light)' },
  { label: '累计收益率', value: '--', icon: 'DataLine', color: 'var(--accent-warning)', bgColor: 'var(--accent-warning-light)' },
  { label: '活跃信号', value: '0', icon: 'Bell', color: 'var(--accent-danger)', bgColor: 'var(--accent-danger-light)' },
])

const heatmapRawData = ref<any[]>([])
const sectorNames = ref<string[]>([])

const heatmapOption = computed(() => {
  const sectors = sectorNames.value.length > 0 ? sectorNames.value : [
    '银行', '非银金融', '食品饮料', '医药生物', '电子', '计算机',
    '传媒', '通信', '电气设备', '化工', '有色金属', '采掘',
  ]
  const heatmapSectorCount = bp.isMobile.value ? 8 : bp.isTablet.value ? 10 : 12
  const displaySectors = sectors.slice(0, heatmapSectorCount)

  // Detect theme for text colors
  const isDark = themeStore.mode === 'dark'
  const textColor = isDark ? '#9da1b0' : '#5a5f6e'
  const axisLabelColor = isDark ? '#646878' : '#9499a6'

  return {
    tooltip: {
      // 手机端没有 hover：改点击触发，并用 confine 把提示框限制在图内，避免盖住标题或溢出屏幕
      position: 'top',
      confine: true,
      triggerOn: bp.isMobile.value ? 'click' : 'mousemove|click',
      enterable: false,
      textStyle: { fontSize: bp.isMobile.value ? 11 : 12 },
      extraCssText: 'max-width:220px;white-space:normal;line-height:1.5;',
      formatter: (p: any) => {
        const sector = displaySectors[p.value[0]]
        const metrics = ['资金强度', '资金斜率', '相对强弱']
        return `${sector} - ${metrics[p.value[1]]}: ${p.value[2]?.toFixed(2)}`
      },
    },
    // 手机端纵向空间紧张：压缩标题/色阶占位，把高度留给格子本身
    // left 从 62 收到 26：纵轴 4 字标签改成竖排后横向只占一个字的宽度
    grid: bp.isMobile.value
      ? { top: 18, bottom: 52, left: 26, right: 8 }
      : { top: 40, bottom: 96, left: 80, right: 20 },
    xAxis: {
      type: 'category',
      data: displaySectors,
      axisLabel: {
        rotate: bp.isMobile.value ? 45 : 45,
        fontSize: bp.isMobile.value ? 9 : 11,
        color: axisLabelColor,
        interval: bp.labelInterval(displaySectors.length),
        // 手机上长板块名截断，避免竖排占位过高、相互遮挡
        formatter: (value: string) => bp.isMobile.value && value.length > 4 ? value.slice(0, 4) + '…' : value,
      },
    },
    yAxis: {
      type: 'category',
      data: ['资金强度', '资金斜率', '相对强弱'],
      // 手机端隐藏轴名：轴名会占用本就紧张的横向空间并压到格子上
      name: bp.isMobile.value ? '' : '热度排行指标',
      nameLocation: 'end',
      nameGap: 20,
      nameTextStyle: { fontSize: 12, fontWeight: 'bold', color: textColor },
      axisLabel: {
        fontSize: bp.isMobile.value ? 9 : 11,
        color: axisLabelColor,
        // 手机端 4 字标签横排要吃 50 多像素，格子上方本来就窄：改竖排，一字一行
        formatter: (v: string) => (bp.isMobile.value ? v.split('').join('\n') : v),
        lineHeight: bp.isMobile.value ? 10 : 14,
        margin: bp.isMobile.value ? 4 : 8,
      },
    },
    visualMap: {
      min: -3, max: 3, calculable: !bp.isMobile.value, orient: 'horizontal', left: 'center', bottom: 0,
      itemWidth: bp.isMobile.value ? 8 : 20,
      itemHeight: bp.isMobile.value ? 100 : 140,
      // 平滑发散色阶：蓝(流出/弱) → 中性灰(0) → 红(流入/强)，避免突兀的棕黄过渡
      inRange: {
        color: isDark
          ? ['#2E5A8C', '#3D72A6', '#5A90BC', '#7CABC9', '#4A5560', '#A86B61', '#AE5846', '#B64635', '#B03E2E']
          : ['#537DB4', '#7FA3CC', '#ACC5DF', '#D7E3EE', '#EDEFF1', '#F3D5CB', '#EDB29E', '#E28A6E', '#D86247'],
      },
      text: ['强', '弱'],
      textStyle: { color: textColor, fontSize: bp.isMobile.value ? 9 : 12 },
    },
    series: [{
      type: 'heatmap',
      data: buildHeatmapData(displaySectors),
      label: {
        show: true,
        fontFamily: CAL_DATE_FONT,
        fontWeight: 700,
        fontSize: bp.isMobile.value ? 10 : 12,
        // 深色模式强制白字并加轻微阴影：否则 ECharts 按底色自动切黑字，浅蓝格上会参差
        ...(isDark ? { color: '#FFFFFF', textShadowColor: 'rgba(0,0,0,0.55)', textShadowBlur: 3 } : {}),
        formatter: (p: any) => p.value[2]?.toFixed(1),
      },
      emphasis: { itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.3)' } },
    }],
  }
})

function buildHeatmapData(sectors: string[]): any[] {
  if (heatmapRawData.value.length > 0) {
    const sectorMap = new Map<string, any>()
    for (const item of heatmapRawData.value) sectorMap.set(item.sector_name, item)
    const rawStrength: number[] = [], rawSlope: number[] = []
    sectors.forEach(name => {
      const item = sectorMap.get(name)
      if (item) {
        rawStrength.push(item.main_net_inflow / 1e8)
        rawSlope.push(item.index_change_pct)
      }
    })
    const normalize = (val: number, arr: number[]): number => {
      if (arr.length === 0) return 0
      const maxAbs = Math.max(...arr.map(Math.abs), 0.01)
      return +(val / maxAbs * 3).toFixed(2)
    }
    const avgChange = rawSlope.length > 0 ? rawSlope.reduce((a, b) => a + b, 0) / rawSlope.length : 0
    const data: any[] = []
    sectors.forEach((name, xi) => {
      const item = sectorMap.get(name)
      if (item) {
        data.push([xi, 0, normalize(item.main_net_inflow / 1e8, rawStrength)])
        data.push([xi, 1, normalize(item.index_change_pct, rawSlope)])
        data.push([xi, 2, normalize(item.index_change_pct - avgChange, rawSlope)])
      } else {
        data.push([xi, 0, 0], [xi, 1, 0], [xi, 2, 0])
      }
    })
    return data
  }
  return []
}

const heatmapLoading = ref(false)
async function loadHeatmapData() {
  heatmapLoading.value = true
  try {
    // 一次请求拿回区间聚合结果：原来按交易日逐日串行拉取，20 日要发 15 个请求
    const data = await settingsApi.getReplayHeatmap(parseInt(heatmapPeriod.value))
    const sectors = data?.sectors || []
    heatmapRawData.value = sectors
    sectorNames.value = sectors.map(s => s.sector_name)
  } catch { heatmapRawData.value = []; sectorNames.value = [] }
  finally { heatmapLoading.value = false }
}

watch(heatmapPeriod, () => loadHeatmapData())

const calendarRealData = ref<any[]>([])

// 空仓标记：后端 /signals/calendar 对"已计算但空仓"的日期输出
// direction=EMPTY / is_empty_position=true 的标记记录
function isEmptyPositionSignal(sig: any): boolean {
  return sig?.is_empty_position === true || sig?.direction === 'EMPTY'
}

const calendarOption = computed(() => {
  const dateSignalsMap: Record<string, any[]> = {}
  const emptyDateMap: Record<string, string> = {}
  for (const sig of calendarRealData.value) {
    const d = sig.signal_date || sig.created_at?.substring(0, 10)
    if (!d) continue
    if (isEmptyPositionSignal(sig)) {
      emptyDateMap[d] = String(sig.reason || '当日空仓，无持仓信号')
      continue
    }
    if (!dateSignalsMap[d]) dateSignalsMap[d] = []
    dateSignalsMap[d].push(sig)
  }
  const calData = Object.entries(dateSignalsMap).map(([date, signals]) => [date, signals.length])
  // 固定 6 周（42 格）网格，周日为一周起点：消除不同月份 5/6 周导致的行数抖动
  const firstOfMonth = dayjs(calendarMonth.value + '-01')
  const rangeStart = firstOfMonth.subtract(firstOfMonth.day(), 'day')
  const rangeEnd = rangeStart.add(41, 'day')
  const calRange: [string, string] = [rangeStart.format('YYYY-MM-DD'), rangeEnd.format('YYYY-MM-DD')]
  const monthPrefix = calendarMonth.value
  const filledData: any[] = []
  const outsideDates: string[] = []
  const closedDates: string[] = []
  for (let i = 0; i < 42; i++) {
    const d = rangeStart.add(i, 'day').format('YYYY-MM-DD')
    if (!d.startsWith(monthPrefix)) { outsideDates.push(d); continue }
    if (emptyDateMap[d]) continue // 空仓日由下方独立蓝色系列渲染
    const existing = calData.find(item => item[0] === d)
    if (existing) filledData.push(existing)
    // 真实交易日历判定：休市日单独渲染，避免与「交易日无信号」混成一片灰格
    else if (!isTradeDay(d)) closedDates.push(d)
    // 未来交易日也要有格子，否则月中会出现一块空白（如 30 号）
    else filledData.push([d, 0])
  }
  const cellLabel = (badge?: string) => (p: any) => {
    const date = Array.isArray(p.data) ? p.data[0] : p.data?.value?.[0]
    const day = date ? String(Number(String(date).slice(-2))) : ''
    if (!badge) return day
    const rich = badge === '休' ? 'rest' : badge === '空' ? 'empty' : 'rebalance'
    return `${day}\n{${rich}|${badge}}`
  }
  const signalLabel = (p: any) => {
    const date = Array.isArray(p.data) ? p.data[0] : p.data?.value?.[0]
    return dateSignalsMap[date] ? cellLabel('调')(p) : cellLabel()(p)
  }
  const isDark = themeStore.mode === 'dark'
  const mobile = bp.isMobile.value
  const cellStyle = calendarItemStyle(isDark, mobile)
  // 三档底色与文字色走共用 palette，和盈亏日历保持同一套观感
  const palette = calendarCellPalette(isDark)
  const emphasisStyle = calendarEmphasisItemStyle(isDark)
  const calTextColor = palette.axisText
  const calEmptyColor = palette.neutral
  const calClosedColor = palette.closed
  const calOutsideColor = palette.outside
  const calEmptyPositionColor = isDark ? '#2b4a7d' : '#a0cfff'
  const labelBase = calendarLabelBase(isDark, mobile, {
    rest: { color: palette.closedSub },
    empty: { color: isDark ? '#dbeafe' : '#1d4ed8' },
    rebalance: { color: isDark ? '#bbf7d0' : '#166534' },
  })
  const emptyDates = Object.keys(emptyDateMap)
  return {
    tooltip: {
      confine: true,
      // 手指没有 hover：移动端改为点击格子后弹出，提示框不再跟指针跑到屏幕外
      triggerOn: bp.isMobile.value ? 'click' : 'mousemove|click',
      enterable: false,
      textStyle: { fontSize: bp.isMobile.value ? 11 : 12 },
      extraCssText: 'max-width:240px;white-space:normal;line-height:1.5;',
      formatter: (p: any) => {
        const date = p.data[0]
        if (!String(date).startsWith(monthPrefix)) return `${date}<br/>非本月`
        const count = p.data[1]
        if (closedDates.includes(date)) return `${date}<br/>休市`
        if (emptyDateMap[date]) {
          return `${date}: 空仓<br/>${emptyDateMap[date]}`
        }
        if (count > 0 && dateSignalsMap[date]) {
          const signals = dateSignalsMap[date]
          const details = signals.slice(0, 5).map((s: any) =>
            `<br/>${s.sector_name} - ${s.direction === 'BUY' ? '买入' : '卖出'}`
          ).join('')
          const more = signals.length > 5 ? `<br/>...还有${signals.length - 5}个信号` : ''
          return `${date}: 调仓 · ${count}个信号${details}${more}`
        }
        return `${date}: ${count}个信号`
      },
    },
    visualMap: {
      // 仅作用于真实的信号数量系列，空仓标记系列不参与着色
      seriesIndex: 0,
      min: 0, max: 10, orient: 'horizontal', left: 'center', bottom: 0,
      itemWidth: bp.isMobile.value ? 8 : 20,
      itemHeight: bp.isMobile.value ? 80 : 140,
      inRange: { color: [calEmptyColor, '#9be9a8', '#40c463', '#30a14e', '#216e39'] },
      textStyle: { color: calTextColor, fontSize: bp.isMobile.value ? 9 : 12 },
    },
    calendar: {
      top: 30, left: 12, right: 12, range: calRange,
      // vertical = 七天横向排成 7 列、周向下排；horizontal 是 6 列周视图，格子会被拉宽
      orient: 'vertical',
      // 列宽交给容器自适应（左右留 12px），行高固定，手机上也能铺满卡片宽度
      cellSize: ['auto', mobile ? 36 : bp.isTablet.value ? 34 : 44],
      // 底层格子必须与卡片同色：否则圆角缺口会露出中性色，在格子交叉处形成杂色斑点
      itemStyle: { ...cellStyle, color: calendarSurfaceColor(isDark) },
      splitLine: { show: false },
      yearLabel: { show: false },
      dayLabel: {
        firstDay: 0, nameMap: ['日', '一', '二', '三', '四', '五', '六'],
        color: calTextColor, margin: mobile ? 8 : 10, fontSize: mobile ? 10 : 12,
      },
      monthLabel: { show: false },
    },
    series: [
      {
        // 调仓日 / 交易日无信号：颜色由 visualMap 决定，日期下方标「调」
        type: 'heatmap',
        coordinateSystem: 'calendar',
        data: filledData,
        // 每个系列都必须显式带 itemStyle，否则会走 ECharts 默认样式，圆角和间隙与其他系列不一致
        itemStyle: { ...cellStyle },
        emphasis: { itemStyle: emphasisStyle },
        label: { ...labelBase, color: palette.neutralDate, formatter: signalLabel },
      },
      {
        // 空仓日：固定蓝色，区别于"未计算/无数据"的灰色底
        type: 'heatmap',
        coordinateSystem: 'calendar',
        data: emptyDates.map(d => [d, 0]),
        itemStyle: { ...cellStyle, color: calEmptyPositionColor },
        emphasis: { itemStyle: emphasisStyle },
        label: { ...labelBase, color: isDark ? '#dbeafe' : '#1d4ed8', formatter: cellLabel('空') },
      },
      {
        // 休市日：真实交易日历判定，非交易日标「休」
        type: 'heatmap',
        coordinateSystem: 'calendar',
        data: closedDates.map(d => [d, 0]),
        itemStyle: { ...cellStyle, color: calClosedColor },
        emphasis: { itemStyle: emphasisStyle },
        label: { ...labelBase, color: palette.closedDate, formatter: cellLabel('休') },
      },
      {
        // 非本月：单独一个系列，visualMap 的 seriesIndex 只作用于 0，这里不会被染色
        type: 'heatmap',
        coordinateSystem: 'calendar',
        data: outsideDates.map(d => [d, 0]),
        itemStyle: { ...cellStyle, color: calOutsideColor },
        emphasis: { itemStyle: emphasisStyle },
        label: { ...labelBase, color: palette.outsideDate, formatter: cellLabel() },
      },
    ],
  }
})

const signalDialogVisible = ref(false)
const selectedDate = ref('')
const selectedDateSignals = ref<any[]>([])
const selectedDateEmptyReason = ref('')
const selectedAnalysis = ref<any[]>([])
const analysisLoading = ref(false)

// 清仓信号：卖出且理由含"清仓"（如"市场不景气，空仓清仓"）
function isClearSignal(sig: any): boolean {
  return sig?.direction === 'SELL' && String(sig?.reason || '').includes('清仓')
}

// 当日是否为空仓日（后端标记记录，symbol: direction=EMPTY / is_empty_position=true）
const selectedDateIsEmpty = computed(() => selectedDateEmptyReason.value !== '')

// 当日信号是否全部为清仓
const selectedDateIsClear = computed(
  () => selectedDateSignals.value.length > 0 && selectedDateSignals.value.every(isClearSignal)
)
const selectedDateClearReason = computed(() => {
  const first = selectedDateSignals.value.find(isClearSignal)
  return String(first?.reason || '').replace(/^[^:]*:\s*/, '')
})
// 是否处于"有历史AI分析，但信号已清空、空仓或已清仓"的状态
const selectedDateStaleAnalysis = computed(
  () => selectedAnalysis.value.length > 0
    && (selectedDateSignals.value.length === 0 || selectedDateIsEmpty.value || selectedDateIsClear.value)
)

async function handleCalendarClick(params: any) {
  if (params.data) {
    const date = params.data[0]
    // 非本月格子只作月份边界提示，点了不该弹明细
    if (!String(date).startsWith(calendarMonth.value)) return
    selectedDate.value = date
    const dayRecords = calendarRealData.value.filter((sig: any) => {
      const d = sig.signal_date || sig.created_at?.substring(0, 10)
      return d === date
    })
    // 空仓标记单独提取，避免作为一条"信号"出现在明细表中
    const emptyMarker = dayRecords.find(isEmptyPositionSignal)
    selectedDateEmptyReason.value = emptyMarker
      ? String(emptyMarker.reason || '当日空仓，无持仓信号')
      : ''
    selectedDateSignals.value = dayRecords.filter((sig: any) => !isEmptyPositionSignal(sig))
    // 获取AI分析
    analysisLoading.value = true
    selectedAnalysis.value = []
    try {
      const res = await aiApi.getAnalysisHistory(currentStrategy.value, date, date)
      if (res?.history?.length > 0) {
        selectedAnalysis.value = res.history[0].analyses || []
      }
    } catch { /* ignore */ }
    analysisLoading.value = false
    signalDialogVisible.value = true
  }
}

onMounted(async () => {
  try {
    const summary = await fundApi.getAccountSummary()
    stats.value[0].value = `¥${(summary.total_assets / 10000).toFixed(2)}万`
    stats.value[1].value = `¥${(summary.today_pnl || 0).toFixed(0)}`
    stats.value[2].value = `${((summary.cumulative_return || 0) * 100).toFixed(2)}%`
  } catch { /* empty */ }
  try {
    todaySignals.value = await signalApi.getTodaySignals(currentStrategy.value)
    stats.value[3].value = String(todaySignals.value.length)
  } catch { /* empty */ }
  loadHeatmapData()
  loadCalendarData()
})

async function loadCalendarData() {
  ensureTradeDates()
  try {
    const data = await signalApi.getSignalCalendar({
      strategyType: currentStrategy.value,
      month: calendarMonth.value,
    })
    if (data?.length > 0) calendarRealData.value = data
  } catch { /* ignore */ }
}

watch(currentStrategy, async () => {
  loadCalendarData()
  try {
    todaySignals.value = await signalApi.getTodaySignals(currentStrategy.value)
    stats.value[3].value = String(todaySignals.value.length)
  } catch { /* empty */ }
})
watch(calendarMonth, () => loadCalendarData())
</script>

<style lang="scss" scoped>
.dashboard-grid {
  display: grid;
  grid-template-columns: 1.4fr 1fr;
  gap: 32px;
  margin-bottom: 48px;
}

.heatmap-card { margin-bottom: 0; }
.signals-card { margin-bottom: 0; }

.calendar-header {
  flex-wrap: wrap; gap: 8px;
}
.calendar-picker {
  max-width: 100%;
}
.calendar-chart {
  height: var(--chart-h-lg); width: 100%;
}

.signal-list {
  max-height: 340px;
  overflow-y: auto;
}

.signal-item {
  padding: 12px 0;
  border-bottom: 1px solid var(--border-subtle);

  &:last-child { border-bottom: none; padding-bottom: 0; }
  &:first-child { padding-top: 0; }

  .signal-top {
    display: flex;
    justify-content: space-between;
    align-items: center;

    .sector-name {
      font-weight: 600;
      font-size: 14px;
      color: var(--text-primary);
    }

    .signal-direction {
      font-size: 12px;
      padding: 2px 10px;
      border-radius: 12px;
    }
  }

  .signal-meta {
    margin-top: 6px;
    display: flex;
    gap: 14px;
    font-size: 12px;
    color: var(--text-tertiary);
    align-items: center;

    .meta-tag {
      color: var(--accent-primary);
      font-weight: 500;
    }
  }
}

.signal-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px 0;
  gap: 8px;

  p {
    margin: 0;
    color: var(--text-tertiary);
    font-size: 13px;
  }
}

@media (max-width: 1024px) {
  .dashboard-grid { grid-template-columns: 1fr; }
}

.heatmap-chart {
  height: var(--chart-h-lg);
  width: 100%;
}

@media (max-width: 768px) {
  .stat-grid { gap: 12px; }
  .heatmap-chart { height: var(--chart-h-md); }
  .signal-list { max-height: 240px; }
  /* 34px 格子 × 6 行 = 204 + top 18 + 星期头 18 + 色阶 20 ≈ 260 */
  .calendar-chart { height: var(--chart-h-md); }
}

/* 手机端 36px 格子 × 6 行 = 216 + top 18 + 星期头 18 + 色阶 8 ≈ 260，留 20px 余量 */
@media (max-width: 480px) {
  .calendar-chart { height: 280px; }
}

/* 手机端：热力图沿用 ≤768 的 260px，信号列表改为不限高，卡片间距压缩到 8px */
@media (max-width: 480px) {
  .dashboard-grid { gap: 8px; margin-bottom: 8px; }
  .signal-list { max-height: none; }

  .signal-item {
    padding: 8px 0;

    .signal-top .sector-name { font-size: 12px; }
    .signal-top .signal-direction { font-size: 10px; padding: 1px 7px; }
    .signal-meta {
      margin-top: 4px;
      gap: 8px;
      font-size: 10px;
      flex-wrap: wrap;
    }
  }

  .signal-empty {
    padding: 20px 0;
    p { font-size: 11px; }
  }

  .signal-dialog-body { padding: 0; }
  .analysis-section { margin-top: 10px; padding-top: 8px; }
  .analysis-title { font-size: 12px; margin-bottom: 6px; }
  .analysis-card { margin-bottom: 8px; padding: 8px; }
  .analysis-header { margin-bottom: 4px; }
}

.signal-dialog-body {
  padding: 16px;
}
.analysis-section {
  margin-top: 16px;
  border-top: 1px solid var(--border-secondary);
  padding-top: 12px;
}
.analysis-title {
  font-weight: 600;
  font-size: 14px;
  margin-bottom: 10px;
}
.analysis-card {
  margin-bottom: 12px;
  padding: 10px;
  background: var(--bg-tertiary);
  border-radius: 8px;
}
.analysis-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}
.analysis-sector {
  font-weight: 600;
}
.analysis-conf {
  font-size: 12px;
  color: var(--text-tertiary);
}
.analysis-text {
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-secondary);
}
.analysis-risks {
  margin-top: 6px;
  font-size: 12px;
  color: var(--accent-danger);
}
.analysis-suggest {
  margin-top: 6px;
  font-size: 12px;
  color: var(--accent-primary);
}
.analysis-empty {
  margin-top: 16px;
  text-align: center;
  color: var(--text-tertiary);
  font-size: 13px;
}

/* ─── 手机端信号列表（替代五列表格） ─── */
.m-signal-list {
  list-style: none;
  margin: 0 0 8px;
  padding: 0;
}

.m-signal-row {
  padding: 7px 0;
  border-bottom: 1px solid var(--border-subtle);

  &:last-child { border-bottom: none; }
}

.m-row-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 12px;

  .m-row-name {
    font-weight: 600;
    color: var(--text-primary);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

.m-row-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 3px;
  font-size: 10px;
  color: var(--text-tertiary);
  font-family: var(--font-mono);
}

/* ─── 手机端：热力图/日历降高，弹窗内容靠边 ─── */
@media (max-width: 480px) {
  .stat-grid { gap: 8px; }
  .analysis-text { font-size: 12px; }
  .analysis-risks, .analysis-suggest { font-size: 11px; }
  .analysis-empty { font-size: 11px; margin-top: 10px; }
}
</style>

<style lang="scss">
.signal-dialog .el-dialog__body {
  padding: 0 !important;
  max-height: min(75vh, 600px);
  overflow-y: auto;
}
.signal-dialog .el-dialog {
  max-height: 80vh;
  display: flex;
  flex-direction: column;
}
.signal-dialog .el-dialog__header {
  flex-shrink: 0;
}
.signal-dialog .el-dialog__body {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
}
</style>
