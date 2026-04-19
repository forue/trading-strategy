<template>
  <div class="dashboard">
    <!-- 顶部统计卡片 -->
    <el-row :gutter="20" class="stat-row">
      <el-col :span="6" v-for="stat in stats" :key="stat.label">
        <div class="stat-card">
          <div class="stat-icon" :style="{ background: stat.bgColor }">
            <el-icon :size="28" :color="stat.color"><component :is="stat.icon" /></el-icon>
          </div>
          <div class="stat-info">
            <div class="stat-value">{{ stat.value }}</div>
            <div class="stat-label">{{ stat.label }}</div>
          </div>
        </div>
      </el-col>
    </el-row>

    <el-row :gutter="20">
      <!-- 板块资金流向热力图 -->
      <el-col :span="14">
        <div class="page-card" v-loading="heatmapLoading">
          <div class="card-header">
            <span class="card-title">板块资金流向热力图</span>
            <el-radio-group v-model="heatmapPeriod" size="small">
              <el-radio-button value="5d">5日</el-radio-button>
              <el-radio-button value="10d">10日</el-radio-button>
              <el-radio-button value="20d">20日</el-radio-button>
            </el-radio-group>
          </div>
          <v-chart :option="heatmapOption" style="height: 400px" autoresize />
        </div>
      </el-col>

      <!-- 今日三档策略信号 -->
      <el-col :span="10">
        <div class="page-card">
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
              <div class="signal-sector">
                <span class="sector-name">{{ signal.sector_name }}</span>
                <el-tag :type="signal.direction === 'BUY' ? 'danger' : 'success'" size="small">
                  {{ signal.direction === 'BUY' ? '买入' : '卖出' }}
                </el-tag>
              </div>
              <div class="signal-detail">
                <span v-if="signal.etf_code" class="etf-info">
                  <el-tag type="primary" effect="plain" size="small">{{ signal.etf_code }}</el-tag>
                  {{ signal.etf_name }}
                </span>
                <span>评分: {{ signal.score?.toFixed(2) }}</span>
                <span>仓位: {{ (signal.position_ratio * 100).toFixed(1) }}%</span>
              </div>
            </div>
            <el-empty v-if="todaySignals.length === 0" description="今日暂无信号" />
          </div>
        </div>
      </el-col>
    </el-row>

    <!-- 信号日历 -->
    <div class="page-card">
      <div class="card-header">
        <span class="card-title">策略信号日历</span>
        <el-date-picker v-model="calendarMonth" type="month" placeholder="选择月份" size="small" value-format="YYYY-MM" />
      </div>
      <v-chart :option="calendarOption" style="height: 300px" autoresize />
    </div>
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
import type { TradeSignal } from '@/api/signal'

use([HeatmapChart, ScatterChart, GridComponent, TooltipComponent, VisualMapComponent, CalendarComponent, LegendComponent, CanvasRenderer])

const heatmapPeriod = ref('5d')
const currentStrategy = ref('AGGRESSIVE')
const calendarMonth = ref(dayjs().format('YYYY-MM'))
const todaySignals = ref<TradeSignal[]>([])

const stats = ref([
  { label: '总资产', value: '--', icon: 'Wallet', color: '#409eff', bgColor: '#ecf5ff' },
  { label: '今日盈亏', value: '--', icon: 'TrendCharts', color: '#67c23a', bgColor: '#f0f9eb' },
  { label: '累计收益率', value: '--', icon: 'DataLine', color: '#e6a23c', bgColor: '#fdf6ec' },
  { label: '活跃信号', value: '0', icon: 'Bell', color: '#f56c6c', bgColor: '#fef0f0' },
])

// 热力图数据 - 从后端加载
const heatmapRawData = ref<any[]>([])
const sectorNames = ref<string[]>([])

const heatmapOption = computed(() => {
  const sectors = sectorNames.value.length > 0 ? sectorNames.value : [
    '银行', '非银金融', '食品饮料', '医药生物', '电子', '计算机',
    '传媒', '通信', '电气设备', '化工', '有色金属', '采掘',
    '钢铁', '房地产', '交通运输', '公用事业', '建筑材料', '汽车',
    '机械设备', '国防军工', '家用电器', '休闲服务', '农林牧渔', '纺织服装',
  ]
  const displaySectors = sectors.slice(0, 12)
  return {
    tooltip: { position: 'top', formatter: (p: any) => {
      const sector = displaySectors[p.value[0]]
      const metrics = ['资金强度', '资金斜率', '相对强弱']
      return `${sector} - ${metrics[p.value[1]]}: ${p.value[2]?.toFixed(2)}`
    }},
    grid: { top: 10, bottom: 60, left: 80, right: 20 },
    xAxis: { type: 'category', data: displaySectors, axisLabel: { rotate: 45, fontSize: 11 } },
    yAxis: { type: 'category', data: ['资金强度', '资金斜率', '相对强弱'] },
    visualMap: { min: -3, max: 3, calculable: true, orient: 'horizontal', left: 'center', bottom: 0,
      inRange: { color: ['#313695', '#4575b4', '#74add1', '#abd9e9', '#ffffbf', '#fee090', '#fdae61', '#f46d43', '#d73027'] },
      text: ['强', '弱'],
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
  // 如果有真实数据，从中提取指标
  if (heatmapRawData.value.length > 0) {
    const sectorMap = new Map<string, any>()
    for (const item of heatmapRawData.value) {
      sectorMap.set(item.sector_name, item)
    }

    // 先收集原始值用于归一化
    const rawStrength: number[] = [], rawSlope: number[] = []
    sectors.forEach(name => {
      const item = sectorMap.get(name)
      if (item) {
        rawStrength.push(item.main_net_inflow / 1e8)
        rawSlope.push(item.index_change_pct)
      }
    })

    // 归一化函数：映射到 [-3, 3]
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
        const strength = normalize(item.main_net_inflow / 1e8, rawStrength)
        const slope = normalize(item.index_change_pct, rawSlope)
        const relative = normalize(item.index_change_pct - avgChange, rawSlope)
        data.push([xi, 0, strength], [xi, 1, slope], [xi, 2, relative])
      } else {
        data.push([xi, 0, 0], [xi, 1, 0], [xi, 2, 0])
      }
    })
    return data
  }
  // 回退到随机数据
  return generateHeatmapData(sectors)
}

function generateHeatmapData(sectors: string[]): any[] {
  const data: any[] = []
  sectors.forEach((_, xi) => {
    for (let yi = 0; yi < 3; yi++) {
      data.push([xi, yi, +(Math.random() * 10 - 5).toFixed(2)])
    }
  })
  return data
}

// 加载热力图数据
const heatmapLoading = ref(false)
async function loadHeatmapData() {
  heatmapLoading.value = true
  try {
    const end = dayjs().format('YYYY-MM-DD')
    const start = dayjs().subtract(parseInt(heatmapPeriod.value), 'day').format('YYYY-MM-DD')
    const dates = await settingsApi.getReplayDates(start, end)
    if (dates && dates.length > 0) {
      // 使用最近一个交易日的数据
      const latestDate = dates[dates.length - 1]
      const dayData = await settingsApi.getReplayDayData(latestDate)
      if (dayData?.sectors) {
        heatmapRawData.value = dayData.sectors
        sectorNames.value = dayData.sectors.map((s: any) => s.sector_name)
      }
    } else {
      // 无数据时清空，让 computed 回退到随机数据
      heatmapRawData.value = []
      sectorNames.value = []
    }
  } catch {
    // 加载失败使用随机数据
    heatmapRawData.value = []
    sectorNames.value = []
  } finally {
    heatmapLoading.value = false
  }
}

// 监听周期切换
watch(heatmapPeriod, () => { loadHeatmapData() })

const calendarOption = computed(() => {
  // 优先使用真实信号数据
  let calData: any[] = []
  if (calendarRealData.value.length > 0) {
    const dateCount: Record<string, number> = {}
    for (const sig of calendarRealData.value) {
      const d = sig.signal_date || sig.created_at?.substring(0, 10)
      if (d) dateCount[d] = (dateCount[d] || 0) + 1
    }
    calData = Object.entries(dateCount).map(([date, count]) => [date, count])
  } else {
    calData = generateCalendarData()
  }
  return {
    tooltip: { formatter: (p: any) => `${p.data[0]}: ${p.data[1]}个信号` },
    visualMap: { min: 0, max: 10, show: true, orient: 'horizontal', bottom: 0, inRange: { color: ['#ebedf0', '#9be9a8', '#40c463', '#30a14e', '#216e39'] } },
    calendar: { top: 20, left: 60, right: 30, range: calendarMonth.value, cellSize: ['auto', 18], itemStyle: { borderWidth: 3, borderColor: '#fff' }, yearLabel: { show: false } },
    series: [{ type: 'heatmap', coordinateSystem: 'calendar', data: calData }],
  }
})

function generateCalendarData(): any[] {
  const data: any[] = []
  const start = dayjs(calendarMonth.value + '-01')
  const daysInMonth = start.daysInMonth()
  for (let i = 1; i <= daysInMonth; i++) {
    const d = start.date(i).format('YYYY-MM-DD')
    if (dayjs(d).isBefore(dayjs())) {
      data.push([d, Math.floor(Math.random() * 8)])
    }
  }
  return data
}

onMounted(async () => {
  try {
    const summary = await fundApi.getAccountSummary()
    stats.value[0].value = `¥${(summary.total_assets / 10000).toFixed(2)}万`
    stats.value[1].value = `¥${summary.today_pnl?.toFixed(0) || 0}`
    stats.value[2].value = `${((summary.cumulative_return || 0) * 100).toFixed(2)}%`
  } catch {}

  try {
    todaySignals.value = await signalApi.getTodaySignals(currentStrategy.value)
    stats.value[3].value = String(todaySignals.value.length)
  } catch {}

  // 加载热力图真实数据
  loadHeatmapData()

  // 加载日历真实信号数据
  loadCalendarData()
})

async function loadCalendarData() {
  try {
    const data = await signalApi.getSignalCalendar({
      strategyType: currentStrategy.value,
      month: calendarMonth.value,
    })
    if (data && data.length > 0) {
      calendarRealData.value = data
    }
  } catch { /* ignore */ }
}
const calendarRealData = ref<any[]>([])

watch(currentStrategy, () => { loadCalendarData() })
watch(calendarMonth, () => { loadCalendarData() })
</script>

<style lang="scss" scoped>
.stat-row { margin-bottom: 20px; }
.stat-card {
  background: #fff; border-radius: 8px; padding: 20px;
  display: flex; align-items: center; gap: 16px;
  box-shadow: 0 1px 4px rgba(0,0,0,0.05);
  .stat-icon { width: 56px; height: 56px; border-radius: 12px; display: flex; align-items: center; justify-content: center; }
  .stat-value { font-size: 22px; font-weight: bold; color: #303133; }
  .stat-label { font-size: 13px; color: #909399; margin-top: 4px; }
}
.card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; .card-title { font-size: 16px; font-weight: 600; } }
.signal-list { max-height: 360px; overflow-y: auto; }
.signal-item { padding: 12px; border-bottom: 1px solid #f0f0f0; &:last-child { border-bottom: none; } .signal-sector { display: flex; justify-content: space-between; align-items: center; .sector-name { font-weight: 500; } } .signal-detail { margin-top: 6px; display: flex; gap: 16px; font-size: 13px; color: #909399; .etf-info { display: inline-flex; align-items: center; gap: 4px; color: #409eff; } } }
</style>
