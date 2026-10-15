<template>
  <div class="fund-page">
    <el-row :gutter="20" class="summary-row">
      <el-col :xs="12" :sm="12" :md="4" :lg="4" v-for="item in summaryItems" :key="item.label">
        <div class="summary-card">
          <div class="summary-label">{{ item.label }}</div>
          <div class="summary-value" :style="{ color: themeColors[item.colorKey] }">{{ item.value }}</div>
        </div>
      </el-col>
    </el-row>

    <el-row :gutter="20">
      <el-col :xs="24" :md="16">
        <div class="page-card">
          <div class="card-header">
            <span class="card-title">净值 / 累计收益率曲线</span>
            <el-form :inline="true" size="small">
              <el-form-item>
                <el-select v-model="curveMonths" style="width: 90px" @change="loadProfitCurve">
                  <el-option label="1月" value="1" />
                  <el-option label="3月" value="3" />
                  <el-option label="6月" value="6" />
                  <el-option label="1年" value="12" />
                </el-select>
              </el-form-item>
            </el-form>
          </div>
          <v-chart :option="navChartOption" style="height: 350px" autoresize />
          <el-row :gutter="12" class="stats-row">
            <el-col :xs="12" :sm="6" v-for="s in profitStats" :key="s.label">
              <div class="stat-item">
                <span class="stat-label">{{ s.label }}</span>
                <span class="stat-val" :style="{ color: s.color }">{{ s.value }}</span>
              </div>
            </el-col>
          </el-row>
        </div>
      </el-col>
      <el-col :xs="24" :md="8">
        <div class="page-card">
          <div class="card-header">
            <span class="card-title">月度收益率</span>
          </div>
          <v-chart :option="monthlyBarOption" style="height: 350px" autoresize />
        </div>
      </el-col>
    </el-row>

    <el-row :gutter="20" class="page-section">
      <el-col :xs="24" :md="16">
        <div class="page-card">
          <div class="card-header">
            <span class="card-title">每日盈亏日历</span>
            <el-date-picker v-model="calendarMonth" type="month" placeholder="选择月份" size="small" value-format="YYYY-MM" @change="loadDailyPnl" />
          </div>
          <v-chart :option="pnlCalendarOption" style="height: 260px" autoresize />
        </div>
      </el-col>
      <el-col :xs="24" :md="8">
        <div class="page-card">
          <div class="card-header">
            <span class="card-title">收益归因分析</span>
          </div>
          <v-chart :option="attributionChartOption" style="height: 350px" autoresize />
        </div>
      </el-col>
    </el-row>

    <div class="page-card page-section">
      <div class="card-header">
        <span class="card-title">银证转账</span>
        <el-button type="primary" size="small" @click="showTransferDialog = true">
          <el-icon><Plus /></el-icon> 新增转账
        </el-button>
      </div>
      <div class="responsive-table"><el-table :data="transfers" stripe empty-text="暂无转账记录">
        <el-table-column prop="transfer_date" label="日期" width="110" />
        <el-table-column label="方向" width="80">
          <template #default="{ row }">
            <el-tag :type="row.direction === 'DEPOSIT' ? 'success' : 'danger'" size="small">
              {{ row.direction === 'DEPOSIT' ? '入金' : '出金' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="金额" width="150">
          <template #default="{ row }">
            <span :style="{ color: row.direction === 'DEPOSIT' ? themeColors.loss : themeColors.profit }">
              {{ row.direction === 'DEPOSIT' ? '+' : '-' }}¥{{ row.amount.toLocaleString() }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="remark" label="备注" min-width="120" />
        <el-table-column label="操作" width="80">
          <template #default="{ row }">
            <el-button type="danger" size="small" link @click="deleteTransfer(row.id)">删除</el-button>
          </template>
        </el-table-column>
      </el-table></div>
    </div>

    <div class="page-card page-section">
      <div class="card-header">
        <span class="card-title">当前持仓</span>
        <el-select v-model="positionStrategy" size="small" style="width: 120px" @change="loadPositions">
          <el-option label="全部" value="" />
          <el-option label="激进" value="AGGRESSIVE" />
          <el-option label="稳健" value="MODERATE" />
          <el-option label="保守" value="CONSERVATIVE" />
        </el-select>
      </div>
      <div class="responsive-table"><el-table :data="positions" stripe empty-text="暂无持仓">
        <el-table-column prop="sector_name" label="板块" width="100" />
        <el-table-column prop="strategy_type" label="策略" width="80">
          <template #default="{ row }">
            <el-tag size="small">{{ STRATEGY_LABELS[row.strategy_type] ?? row.strategy_type }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="direction" label="方向" width="60">
          <template #default="{ row }">
            <span :class="row.direction === 'BUY' ? 'signal-buy' : 'signal-sell'">{{ row.direction === 'BUY' ? '多' : '空' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="quantity" label="数量" width="90" />
        <el-table-column prop="avg_price" label="均价" width="90">
          <template #default="{ row }">¥{{ row.avg_price?.toFixed(4) }}</template>
        </el-table-column>
        <el-table-column prop="current_price" label="现价" width="90">
          <template #default="{ row }">¥{{ row.current_price?.toFixed(4) }}</template>
        </el-table-column>
        <el-table-column label="盈亏" width="130">
          <template #default="{ row }">
            <span v-if="row.current_price && row.avg_price" :style="{ color: row.current_price > row.avg_price ? themeColors.profit : themeColors.loss }">
              {{ ((row.current_price - row.avg_price) / row.avg_price * 100).toFixed(2) }}%
              (¥{{ ((row.current_price - row.avg_price) * row.quantity).toFixed(2) }})
            </span>
            <span v-else class="text-muted">--</span>
          </template>
        </el-table-column>
        <el-table-column prop="position_ratio" label="仓位" width="80">
          <template #default="{ row }">{{ (row.position_ratio * 100).toFixed(1) }}%</template>
        </el-table-column>
        <el-table-column prop="opened_at" label="开仓时间" min-width="150" />
      </el-table></div>
    </div>

    <el-dialog v-model="showTransferDialog" title="新增银证转账" width="420px">
      <el-form :model="transferForm" label-width="70px">
        <el-form-item label="日期">
          <el-date-picker v-model="transferForm.date" type="date" placeholder="选择日期" value-format="YYYY-MM-DD"
            style="width: 100%" />
        </el-form-item>
        <el-form-item label="方向">
          <el-radio-group v-model="transferForm.direction">
            <el-radio value="DEPOSIT">入金（银行→证券）</el-radio>
            <el-radio value="WITHDRAW">出金（证券→银行）</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="金额">
          <el-input-number v-model="transferForm.amount" :min="0" :step="10000" style="width: 100%" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="transferForm.remark" placeholder="可选" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showTransferDialog = false">取消</el-button>
        <el-button type="primary" @click="submitTransfer">确认</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { LineChart, BarChart, PieChart, HeatmapChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent, VisualMapComponent, CalendarComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { fundApi } from '@/api/fund'
import { useThemeStore } from '@/stores/theme'
import type { Position, NavRecord, DailyPnl, BankTransfer, ProfitCurveData } from '@/api/fund'
import dayjs from 'dayjs'
import { ElMessage, ElMessageBox } from 'element-plus'

use([LineChart, BarChart, PieChart, HeatmapChart, CalendarComponent, GridComponent, TooltipComponent, LegendComponent, VisualMapComponent, CanvasRenderer])

const themeStore = useThemeStore()
const isDark = computed(() => themeStore.mode === 'dark')

// 语义色随主题切换：暗色下需提高明度、改用暗色网格/边框，
// 否则深色文字（#303133）与浅灰边框（#dcdee0）在 --bg-secondary(#1a1d24) 上不可读或刺眼。
const themeColors = computed(() => (isDark.value ? {
  profit: '#ff6f61', loss: '#357a5c', text: '#e8eaef', textSub: '#9da1b0',
  primary: '#7b93f5', warning: '#e6a23c', grid: '#2a2d38', axis: '#2a2d38',
  tooltipBg: '#252832', tooltipBorder: '#2a2d38',
} : {
  profit: '#f56c6c', loss: '#67c23a', text: '#303133', textSub: '#5a5f6e',
  primary: '#409eff', warning: '#e6a23c', grid: '#ebeef5', axis: '#e4e7ed',
  tooltipBg: '#fff', tooltipBorder: '#ebeef5',
}))

// 策略类型中文名：集中定义为 Record，修复模板中用 any 索引对象字面量导致的 TS7053
const STRATEGY_LABELS: Record<string, string> = {
  AGGRESSIVE: '激进',
  MODERATE: '稳健',
  CONSERVATIVE: '保守',
}

const curveMonths = ref('3')
const calendarMonth = ref(dayjs().format('YYYY-MM'))
const positionStrategy = ref('')
const showTransferDialog = ref(false)

const positions = ref<Position[]>([])
const navData = ref<NavRecord[]>([])
const dailyPnlData = ref<DailyPnl[]>([])
const transfers = ref<BankTransfer[]>([])
const attributionData = ref<any[]>([])
const profitCurveData = ref<ProfitCurveData | null>(null)

const transferForm = reactive({
  date: dayjs().format('YYYY-MM-DD'),
  direction: 'DEPOSIT',
  amount: 100000,
  remark: '',
})

type ColorKey = 'text' | 'primary' | 'warning' | 'profit' | 'loss'
const summaryItems = ref<{ label: string; value: string; colorKey: ColorKey }[]>([
  { label: '总资产', value: '--', colorKey: 'text' },
  { label: '可用资金', value: '--', colorKey: 'primary' },
  { label: '持仓市值', value: '--', colorKey: 'warning' },
  { label: '今日盈亏', value: '--', colorKey: 'profit' },
  { label: '累计收益率', value: '--', colorKey: 'loss' },
])

const profitStats = computed(() => {
  const s = profitCurveData.value?.stats
  if (!s) return []
  return [
    { label: '累计收益', value: `${s.total_return_pct}%`, color: s.total_return_pct >= 0 ? themeColors.value.profit : themeColors.value.loss },
    { label: '最大回撤', value: `${s.max_drawdown_pct}%`, color: themeColors.value.warning },
    { label: '年化收益', value: `${s.annual_return_pct}%`, color: s.annual_return_pct >= 0 ? themeColors.value.profit : themeColors.value.loss },
    { label: '夏普比率', value: `${s.sharpe_ratio}`, color: themeColors.value.primary },
  ]
})

const navChartOption = computed(() => {
  if (navData.value.length === 0) return {}
  const c = themeColors.value
  return {
    tooltip: {
      trigger: 'axis',
      backgroundColor: c.tooltipBg, borderColor: c.tooltipBorder, textStyle: { color: c.text },
    },
    legend: {
      data: ['账户净值', '累计收益率'],
      selected: { '账户净值': true, '累计收益率': true },
      textStyle: { color: c.textSub },
    },
    grid: { top: 40, bottom: 20 },
    xAxis: {
      type: 'category', data: navData.value.map(d => d.nav_date), boundaryGap: false,
      axisLabel: { color: c.textSub }, axisLine: { lineStyle: { color: c.axis } },
    },
    yAxis: [
      { type: 'value', name: '净值', scale: true, nameTextStyle: { color: c.textSub }, axisLabel: { color: c.textSub }, axisLine: { lineStyle: { color: c.axis } }, splitLine: { lineStyle: { type: 'dashed', color: c.grid } } },
      { type: 'value', name: '收益率 %', scale: true, nameTextStyle: { color: c.textSub }, axisLabel: { formatter: '{value}%', color: c.textSub }, axisLine: { lineStyle: { color: c.axis } }, splitLine: { show: false } },
    ],
    series: [
      { name: '账户净值', type: 'line', data: navData.value.map(d => d.total_assets), smooth: true, lineStyle: { width: 2 }, itemStyle: { color: c.primary }, areaStyle: { color: isDark.value ? 'rgba(123,147,245,0.12)' : 'rgba(64,158,255,0.08)' } },
      { name: '累计收益率', type: 'line', yAxisIndex: 1, data: navData.value.map(d => (d.cumulative_return * 100).toFixed(2)), smooth: true, lineStyle: { width: 2, type: 'dashed' }, itemStyle: { color: c.loss } },
    ],
  }
})

const monthlyBarOption = computed(() => {
  const monthly = profitCurveData.value?.monthly_returns || []
  const c = themeColors.value
  const colors = monthly.map(m => m.return_pct >= 0 ? c.profit : c.loss)
  return {
    tooltip: {
      trigger: 'axis', formatter: (p: any) => `${p[0].name}: ${p[0].value}%`,
      backgroundColor: c.tooltipBg, borderColor: c.tooltipBorder, textStyle: { color: c.text },
    },
    grid: { top: 10, bottom: 30, left: 50, right: 20 },
    xAxis: {
      type: 'category', data: monthly.map(m => m.month.slice(5)),
      axisLabel: { color: c.textSub }, axisLine: { lineStyle: { color: c.axis } },
    },
    yAxis: {
      type: 'value', axisLabel: { formatter: '{value}%', color: c.textSub },
      axisLine: { lineStyle: { color: c.axis } }, splitLine: { lineStyle: { color: c.grid } },
    },
    series: [{
      type: 'bar',
      data: monthly.map((m, i) => ({ value: m.return_pct, itemStyle: { color: colors[i] } })),
      barWidth: '60%',
      label: { show: true, position: 'top', formatter: (p: any) => `${p.value}%`, fontSize: 10, color: c.textSub },
    }],
  }
})

const pnlCalendarOption = computed(() => {
  const data = dailyPnlData.value.map(d => [d.date, d.daily_return])
  if (data.length === 0) return {}
  // 暗色配色：中位色改用暗灰（不可用纯白，否则在暗背景上过亮且与盈利红混淆），
  // 亏损绿/盈利红按暗背景调整明度，保证与卡片底色（--bg-secondary #1a1d24）的对比度。
  // 暗色下刻意拉开红绿明度差：两者亮度接近（对比度仅 1.28）时难以区分，
  // 故选「亮红 + 中绿」，互差提升至 1.88，色觉障碍用户也更易分辨。
  const profitColor = isDark.value ? '#ff6f61' : '#f56c6c'
  const lossColor = isDark.value ? '#357a5c' : '#67c23a'
  const neutralColor = isDark.value ? '#4a4f5c' : '#fff'
  const borderColor = isDark.value ? '#2a2d38' : '#dcdee0'
  const labelColor = isDark.value ? '#9da1b0' : '#5a5f6e'
  const monthLabelColor = isDark.value ? '#e8eaef' : '#303133'

  return {
    tooltip: {
      formatter: (p: any) => `${p.data[0]}<br/>收益率: ${p.data[1]}%<br/>金额: ¥${pnlAmountMap.value[p.data[0]] || 0}`,
      backgroundColor: isDark.value ? '#252832' : '#fff',
      borderColor: isDark.value ? '#2a2d38' : '#ebeef5',
      textStyle: { color: isDark.value ? '#e8eaef' : '#303133' },
    },
    visualMap: {
      min: -5, max: 5, show: true, orient: 'horizontal', left: 'center', bottom: 0,
      // visualMap.text 为 [高端, 低端]：高端是 +5%（盈利），低端是 -5%（亏损）
      inRange: { color: [lossColor, neutralColor, profitColor] },
      text: ['盈利', '亏损'],
      textStyle: { color: labelColor },
    },
    calendar: {
      top: 20, left: 30, right: 30, range: calendarMonth.value, cellSize: ['auto', 20],
      itemStyle: {
        borderWidth: 1,
        borderColor,
        // 无数据格子透明（露出卡片底色），与「0 收益」的中性灰区分开
        color: isDark.value ? 'transparent' : '#fff',
      },
      dayLabel: { firstDay: 1, nameMap: 'cn', color: labelColor },
      monthLabel: { nameMap: 'cn', color: monthLabelColor },
    },
    series: [{ type: 'heatmap', coordinateSystem: 'calendar', data }],
  }
})

const pnlAmountMap = computed(() => {
  const m: Record<string, number> = {}
  dailyPnlData.value.forEach(d => { m[d.date] = d.daily_pnl_amount })
  return m
})

const attributionChartOption = computed(() => {
  const c = themeColors.value
  return {
    tooltip: {
      trigger: 'item', formatter: '{b}: ¥{c} ({d}%)',
      backgroundColor: c.tooltipBg, borderColor: c.tooltipBorder, textStyle: { color: c.text },
    },
    legend: {
      orient: 'vertical', left: 'left', top: 'middle', type: 'scroll',
      textStyle: { color: c.textSub },
    },
    series: [{
      type: 'pie', radius: ['40%', '70%'], center: ['60%', '50%'],
      data: attributionData.value.length > 0
        ? attributionData.value.map((a: any) => ({ name: a.sector_name, value: +a.contribution }))
        : [{ name: '暂无数据', value: 1 }],
      emphasis: { itemStyle: { shadowBlur: 10 } },
      label: { formatter: '{b}\n¥{c}', color: c.textSub },
      labelLine: { lineStyle: { color: c.axis } },
    }],
  }
})

function loadSummary() {
  fundApi.getAccountSummary().then(summary => {
    summaryItems.value[0].value = `¥${(summary.total_assets / 10000).toFixed(2)}万`
    summaryItems.value[1].value = `¥${(summary.cash / 10000).toFixed(2)}万`
    summaryItems.value[2].value = `¥${(summary.market_value / 10000).toFixed(2)}万`
    summaryItems.value[3].value = `¥${summary.today_pnl?.toFixed(0) || 0}`
    summaryItems.value[4].value = `${((summary.cumulative_return || 0) * 100).toFixed(2)}%`
  }).catch(() => {})
}

function loadPositions() {
  fundApi.getPositions(positionStrategy.value || undefined).then(data => {
    positions.value = data
  }).catch(() => {})
}

function loadProfitCurve() {
  fundApi.getProfitCurve(parseInt(curveMonths.value)).then(data => {
    profitCurveData.value = data
    navData.value = data.nav_curve
  }).catch(() => {})
}

function loadDailyPnl() {
  fundApi.getDailyPnl(calendarMonth.value).then(data => {
    dailyPnlData.value = data
  }).catch(() => {})
}

function loadAttribution() {
  const end = dayjs().format('YYYY-MM-DD')
  const start = dayjs().subtract(3, 'month').format('YYYY-MM-DD')
  fundApi.getReturnAttribution({ strategyType: '', startDate: start, endDate: end }).then(data => {
    attributionData.value = data
  }).catch(() => {})
}

function loadTransfers() {
  fundApi.getTransfers().then(data => {
    transfers.value = data
  }).catch(() => {})
}

function submitTransfer() {
  if (!transferForm.date || !transferForm.amount) {
    ElMessage.warning('请填写完整信息')
    return
  }
  fundApi.createTransfer({
    transfer_date: transferForm.date,
    direction: transferForm.direction,
    amount: transferForm.amount,
    remark: transferForm.remark,
  }).then(() => {
    ElMessage.success('转账记录已添加')
    showTransferDialog.value = false
    transferForm.amount = 100000
    transferForm.remark = ''
    loadTransfers()
    loadSummary()
  }).catch((e) => {
    ElMessage.error(e?.message || '创建失败')
  })
}

function deleteTransfer(id: number) {
  ElMessageBox.confirm('确认删除此转账记录？', '提示', { type: 'warning' }).then(() => {
    fundApi.deleteTransfer(id).then(() => {
      ElMessage.success('已删除')
      loadTransfers()
      loadSummary()
    }).catch(() => {})
  }).catch(() => {})
}

onMounted(() => {
  loadSummary()
  loadPositions()
  loadProfitCurve()
  loadDailyPnl()
  loadAttribution()
  loadTransfers()
})
</script>

<style lang="scss" scoped>
.summary-row { margin-bottom: 16px; }
.summary-card {
  background: var(--bg-secondary); border: 1px solid var(--border-secondary);
  border-radius: var(--radius-md); padding: 18px 12px; text-align: center;
  box-shadow: var(--shadow-sm);
  transition: all var(--transition-base);
  overflow: hidden;
  &:hover { box-shadow: var(--shadow-card); }
  .summary-label { font-size: 12px; color: var(--text-tertiary); margin-bottom: 6px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .summary-value { font-size: 20px; font-weight: 700; font-family: var(--font-mono); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
}
.stats-row { margin-top: 12px; }
.stat-item {
  text-align: center; padding: 8px;
  background: var(--bg-tertiary); border-radius: var(--radius-sm);
  .stat-label { font-size: 12px; color: var(--text-tertiary); display: block; }
  .stat-val { font-size: 15px; font-weight: 600; }
}

@media (max-width: 768px) {
  .summary-card {
    padding: 12px 8px;
    .summary-value { font-size: 16px; }
    .summary-label { font-size: 11px; }
  }
  .summary-row :deep(.el-col) { margin-bottom: 8px; }
  .stat-item { padding: 6px; .stat-val { font-size: 13px; } }
  .stats-row :deep(.el-col) { margin-bottom: 6px; }
  :deep(.el-row) { margin-left: -8px !important; margin-right: -8px !important; }
  :deep(.el-col) { padding-left: 8px !important; padding-right: 8px !important; }
}

@media (max-width: 480px) {
  .summary-card {
    padding: 10px 6px;
    .summary-value { font-size: 14px; }
    .summary-label { font-size: 10px; }
  }
  .stat-item { padding: 6px 4px; .stat-val { font-size: 12px; } .stat-label { font-size: 11px; } }
  :deep(.el-row) { margin-left: -4px !important; margin-right: -4px !important; }
  :deep(.el-col) { padding-left: 4px !important; padding-right: 4px !important; }
}
</style>
