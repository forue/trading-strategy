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
        <v-chart :option="heatmapOption" style="height: 380px" autoresize />
      </div>

      <!-- Today's Signals -->
      <div class="page-card signals-card">
        <div class="card-header">
          <span class="card-title">今日策略信号</span>
          <el-select v-model="currentStrategy" size="small" style="width: 120px">
            <el-option label="激进轮动" value="AGGRESSIVE" />
            <el-option label="稳健轮动" value="MODERATE" />
            <el-option label="保守轮动" value="CONSERVATIVE" />
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
        <el-table :data="selectedDateSignals" max-height="200">
          <el-table-column prop="sector_name" label="板块" />
          <el-table-column prop="direction" label="方向">
            <template #default="{ row }">
              <span :class="row.direction === 'BUY' ? 'signal-buy' : 'signal-sell'">
                {{ row.direction === 'BUY' ? '买入' : '卖出' }}
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="etf_code" label="ETF" />
          <el-table-column prop="score" label="评分">
            <template #default="{ row }">{{ row.score?.toFixed(2) }}</template>
          </el-table-column>
          <el-table-column prop="position_ratio" label="仓位">
            <template #default="{ row }">{{ ((row.position_ratio || 0) * 100).toFixed(1) }}%</template>
          </el-table-column>
        </el-table>

        <!-- AI 分析回放 -->
        <div v-if="selectedAnalysis.length > 0" class="analysis-section">
          <div class="analysis-title">AI 分析回放</div>
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
        <div v-else-if="selectedDateSignals.length > 0" class="analysis-empty">该日期暂无AI分析记录</div>
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
import { useBreakpoint } from '@/composables/useBreakpoint'
import type { TradeSignal } from '@/api/signal'

const bp = useBreakpoint()

use([HeatmapChart, ScatterChart, GridComponent, TooltipComponent, VisualMapComponent, CalendarComponent, LegendComponent, CanvasRenderer])

const themeStore = useThemeStore()

const heatmapPeriod = ref('5d')
const currentStrategy = ref('AGGRESSIVE')
const calendarMonth = ref(dayjs().format('YYYY-MM'))
const todaySignals = ref<TradeSignal[]>([])

const stats = ref([
  { label: '总资产', value: '--', icon: 'Wallet', color: '#637ee8', bgColor: 'var(--accent-primary-light)' },
  { label: '今日盈亏', value: '--', icon: 'TrendCharts', color: '#2da55a', bgColor: 'var(--accent-success-light)' },
  { label: '累计收益率', value: '--', icon: 'DataLine', color: '#e6a23c', bgColor: 'var(--accent-warning-light)' },
  { label: '活跃信号', value: '0', icon: 'Bell', color: '#e04a4a', bgColor: 'var(--accent-danger-light)' },
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
      position: 'top',
      formatter: (p: any) => {
        const sector = displaySectors[p.value[0]]
        const metrics = ['资金强度', '资金斜率', '相对强弱']
        return `${sector} - ${metrics[p.value[1]]}: ${p.value[2]?.toFixed(2)}`
      },
    },
    grid: { top: 10, bottom: 60, left: 80, right: 20 },
    xAxis: {
      type: 'category',
      data: displaySectors,
      axisLabel: { rotate: bp.isMobile.value ? 90 : 45, fontSize: bp.isMobile.value ? 10 : 11, color: axisLabelColor },
    },
    yAxis: {
      type: 'category',
      data: ['资金强度', '资金斜率', '相对强弱'],
      name: '热度排行指标',
      nameLocation: 'end',
      nameGap: 20,
      nameTextStyle: { fontSize: 12, fontWeight: 'bold', color: textColor },
    },
    visualMap: {
      min: -3, max: 3, calculable: true, orient: 'horizontal', left: 'center', bottom: 0,
      inRange: { color: isDark ? ['#1b3a5c', '#2d5280', '#3f6aa4', '#5182c4', '#505050', '#906040', '#b04030', '#d03020', '#e84838'] : ['#313695', '#4575b4', '#74add1', '#abd9e9', '#ffffbf', '#fee090', '#fdae61', '#f46d43', '#d73027'] },
      text: ['强', '弱'],
      textStyle: { color: textColor },
    },
    series: [{
      type: 'heatmap',
      data: buildHeatmapData(displaySectors),
      label: { show: true, fontSize: 10, formatter: (p: any) => p.value[2]?.toFixed(1) },
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
    const end = dayjs().format('YYYY-MM-DD')
    const start = dayjs().subtract(parseInt(heatmapPeriod.value), 'day').format('YYYY-MM-DD')
    const dates = await settingsApi.getReplayDates(start, end)
    if (dates && dates.length > 0) {
      const sectorDataMap = new Map<string, { mainNetInflow: number[], indexChangePct: number[] }>()
      for (const date of dates) {
        const dayData = await settingsApi.getReplayDayData(date)
        if (dayData?.sectors) {
          for (const sector of dayData.sectors) {
            const name = sector.sector_name
            if (!sectorDataMap.has(name)) sectorDataMap.set(name, { mainNetInflow: [], indexChangePct: [] })
            const d = sectorDataMap.get(name)!
            d.mainNetInflow.push(sector.main_net_inflow || 0)
            d.indexChangePct.push(sector.index_change_pct || 0)
          }
        }
      }
      const aggregated = Array.from(sectorDataMap.entries()).map(([name, data]) => ({
        sector_name: name,
        main_net_inflow: data.mainNetInflow.reduce((a, b) => a + b, 0) / data.mainNetInflow.length,
        index_change_pct: data.indexChangePct.reduce((a, b) => a + b, 0) / data.indexChangePct.length,
      }))
      if (aggregated.length > 0) {
        heatmapRawData.value = aggregated.sort((a: any, b: any) => (b.main_net_inflow || 0) - (a.main_net_inflow || 0))
        sectorNames.value = heatmapRawData.value.map((s: any) => s.sector_name)
      } else { heatmapRawData.value = []; sectorNames.value = [] }
    } else { heatmapRawData.value = []; sectorNames.value = [] }
  } catch { heatmapRawData.value = []; sectorNames.value = [] }
  finally { heatmapLoading.value = false }
}

watch(heatmapPeriod, () => loadHeatmapData())

const calendarRealData = ref<any[]>([])
const calendarOption = computed(() => {
  const dateSignalsMap: Record<string, any[]> = {}
  for (const sig of calendarRealData.value) {
    const d = sig.signal_date || sig.created_at?.substring(0, 10)
    if (d) {
      if (!dateSignalsMap[d]) dateSignalsMap[d] = []
      dateSignalsMap[d].push(sig)
    }
  }
  const calData = Object.entries(dateSignalsMap).map(([date, signals]) => [date, signals.length])
  const start = dayjs(calendarMonth.value + '-01')
  const daysInMonth = start.daysInMonth()
  const filledData: any[] = []
  for (let i = 1; i <= daysInMonth; i++) {
    const d = start.date(i).format('YYYY-MM-DD')
    const existing = calData.find(item => item[0] === d)
    if (existing) filledData.push(existing)
    else if (dayjs(d).isBefore(dayjs()) || dayjs(d).isSame(dayjs(), 'day')) filledData.push([d, 0])
  }
  const isDark = themeStore.mode === 'dark'
  const calTextColor = isDark ? '#9da1b0' : '#5a5f6e'
  const calBorderColor = isDark ? '#2a2d38' : '#dcdee0'
  const calEmptyColor = isDark ? '#1e2130' : '#f5f5f5'
  return {
    tooltip: {
      formatter: (p: any) => {
        const date = p.data[0]
        const count = p.data[1]
        if (count > 0 && dateSignalsMap[date]) {
          const signals = dateSignalsMap[date]
          const details = signals.slice(0, 5).map((s: any) =>
            `<br/>${s.sector_name} - ${s.direction === 'BUY' ? '买入' : '卖出'}`
          ).join('')
          const more = signals.length > 5 ? `<br/>...还有${signals.length - 5}个信号` : ''
          return `${date}: ${count}个信号${details}${more}`
        }
        return `${date}: ${count}个信号`
      },
    },
    visualMap: {
      min: 0, max: 10, orient: 'horizontal', bottom: 0,
      inRange: { color: [calEmptyColor, '#9be9a8', '#40c463', '#30a14e', '#216e39'] },
      textStyle: { color: calTextColor },
    },
    calendar: {
      top: 16, left: 60, right: 30, range: calendarMonth.value,
      cellSize: ['auto', 18],
      itemStyle: { borderWidth: 1, borderColor: calBorderColor, color: calEmptyColor },
      splitLine: { show: true, lineStyle: { color: isDark ? '#333848' : '#d0d0d0' } },
      yearLabel: { show: false },
      dayLabel: { firstDay: 1, nameMap: 'cn', color: calTextColor },
      monthLabel: { nameMap: 'cn', color: calTextColor },
    },
    series: [{
      type: 'heatmap',
      coordinateSystem: 'calendar',
      data: filledData,
    }],
  }
})

const signalDialogVisible = ref(false)
const selectedDate = ref('')
const selectedDateSignals = ref<any[]>([])
const selectedAnalysis = ref<any[]>([])
const analysisLoading = ref(false)

async function handleCalendarClick(params: any) {
  if (params.data) {
    const date = params.data[0]
    selectedDate.value = date
    selectedDateSignals.value = calendarRealData.value.filter((sig: any) => {
      const d = sig.signal_date || sig.created_at?.substring(0, 10)
      return d === date
    })
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
.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 16px;
}

.dashboard-grid {
  display: grid;
  grid-template-columns: 1.4fr 1fr;
  gap: 16px;
  margin-bottom: 16px;
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
  height: 240px; width: 100%;
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
  .dashboard-grid {
    grid-template-columns: 1fr;
  }
  .stat-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 768px) {
  .stat-grid { gap: 10px; }
  .stat-card { padding: 14px 16px; }
  .heatmap-card :deep(.echarts) { height: 280px !important; }
  .signal-list { max-height: 240px; }
  .calendar-chart { height: 200px; }
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

@media (max-width: 480px) {
  .stat-grid {
    grid-template-columns: 1fr;
    gap: 8px;
  }
  .stat-card { padding: 10px 12px; }
  .stat-value { font-size: 16px; }
  :deep(.el-dialog) { width: 90% !important; }
  .calendar-chart { height: 180px; }
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
