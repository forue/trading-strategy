<template>
  <div class="fund-page">
    <el-row :gutter="20" class="summary-row">
      <el-col :xs="12" :sm="12" :md="4" :lg="4" v-for="item in summaryItems" :key="item.label">
        <div class="summary-card">
          <div class="summary-label">{{ item.label }}</div>
          <div class="summary-value" :style="{ color: item.color }">{{ item.value }}</div>
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
            <el-col :span="6" v-for="s in profitStats" :key="s.label">
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

    <el-row :gutter="20" style="margin-top: 20px">
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

    <div class="page-card" style="margin-top: 20px">
      <div class="card-header">
        <span class="card-title">银证转账</span>
        <el-button type="primary" size="small" @click="showTransferDialog = true">
          <el-icon><Plus /></el-icon> 新增转账
        </el-button>
      </div>
      <el-table :data="transfers" stripe empty-text="暂无转账记录">
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
            <span :style="{ color: row.direction === 'DEPOSIT' ? '#67c23a' : '#f56c6c' }">
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
      </el-table>
    </div>

    <div class="page-card" style="margin-top: 20px">
      <div class="card-header">
        <span class="card-title">当前持仓</span>
        <el-select v-model="positionStrategy" size="small" style="width: 120px" @change="loadPositions">
          <el-option label="全部" value="" />
          <el-option label="激进" value="AGGRESSIVE" />
          <el-option label="稳健" value="MODERATE" />
          <el-option label="保守" value="CONSERVATIVE" />
        </el-select>
      </div>
      <el-table :data="positions" stripe empty-text="暂无持仓">
        <el-table-column prop="sector_name" label="板块" width="100" />
        <el-table-column prop="strategy_type" label="策略" width="80">
          <template #default="{ row }">
            <el-tag size="small">{{ { AGGRESSIVE: '激进', MODERATE: '稳健', CONSERVATIVE: '保守' }[row.strategy_type] || row.strategy_type }}</el-tag>
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
            <span v-if="row.current_price && row.avg_price" :style="{ color: row.current_price > row.avg_price ? '#f56c6c' : '#67c23a' }">
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
      </el-table>
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
import type { Position, NavRecord, DailyPnl, BankTransfer, ProfitCurveData } from '@/api/fund'
import dayjs from 'dayjs'
import { ElMessage, ElMessageBox } from 'element-plus'

use([LineChart, BarChart, PieChart, HeatmapChart, CalendarComponent, GridComponent, TooltipComponent, LegendComponent, VisualMapComponent, CanvasRenderer])

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

const summaryItems = ref([
  { label: '总资产', value: '--', color: '#303133' },
  { label: '可用资金', value: '--', color: '#409eff' },
  { label: '持仓市值', value: '--', color: '#e6a23c' },
  { label: '今日盈亏', value: '--', color: '#f56c6c' },
  { label: '累计收益率', value: '--', color: '#67c23a' },
])

const profitStats = computed(() => {
  const s = profitCurveData.value?.stats
  if (!s) return []
  return [
    { label: '累计收益', value: `${s.total_return_pct}%`, color: s.total_return_pct >= 0 ? '#f56c6c' : '#67c23a' },
    { label: '最大回撤', value: `${s.max_drawdown_pct}%`, color: '#e6a23c' },
    { label: '年化收益', value: `${s.annual_return_pct}%`, color: s.annual_return_pct >= 0 ? '#f56c6c' : '#67c23a' },
    { label: '夏普比率', value: `${s.sharpe_ratio}`, color: '#409eff' },
  ]
})

const navChartOption = computed(() => {
  if (navData.value.length === 0) return {}
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['账户净值', '累计收益率'],
      selected: { '账户净值': true, '累计收益率': true } },
    grid: { top: 40, bottom: 20 },
    xAxis: { type: 'category', data: navData.value.map(d => d.nav_date), boundaryGap: false },
    yAxis: [
      { type: 'value', name: '净值', scale: true, splitLine: { lineStyle: { type: 'dashed' } } },
      { type: 'value', name: '收益率 %', scale: true, splitLine: { show: false }, axisLabel: { formatter: '{value}%' } },
    ],
    series: [
      { name: '账户净值', type: 'line', data: navData.value.map(d => d.total_assets), smooth: true, lineStyle: { width: 2 }, itemStyle: { color: '#409eff' }, areaStyle: { color: 'rgba(64,158,255,0.08)' } },
      { name: '累计收益率', type: 'line', yAxisIndex: 1, data: navData.value.map(d => (d.cumulative_return * 100).toFixed(2)), smooth: true, lineStyle: { width: 2, type: 'dashed' }, itemStyle: { color: '#67c23a' } },
    ],
  }
})

const monthlyBarOption = computed(() => {
  const monthly = profitCurveData.value?.monthly_returns || []
  const colors = monthly.map(m => m.return_pct >= 0 ? '#f56c6c' : '#67c23a')
  return {
    tooltip: { trigger: 'axis', formatter: (p: any) => `${p[0].name}: ${p[0].value}%` },
    grid: { top: 10, bottom: 30, left: 50, right: 20 },
    xAxis: { type: 'category', data: monthly.map(m => m.month.slice(5)) },
    yAxis: { type: 'value', axisLabel: { formatter: '{value}%' } },
    series: [{
      type: 'bar',
      data: monthly.map((m, i) => ({ value: m.return_pct, itemStyle: { color: colors[i] } })),
      barWidth: '60%',
      label: { show: true, position: 'top', formatter: (p: any) => `${p.value}%`, fontSize: 10 },
    }],
  }
})

const pnlCalendarOption = computed(() => {
  const data = dailyPnlData.value.map(d => [d.date, d.daily_return])
  if (data.length === 0) return {}
  return {
    tooltip: { formatter: (p: any) => `${p.data[0]}<br/>收益率: ${p.data[1]}%<br/>金额: ¥${pnlAmountMap.value[p.data[0]] || 0}` },
    visualMap: { min: -5, max: 5, show: true, orient: 'horizontal', left: 'center', bottom: 0, inRange: { color: ['#67c23a', '#fff', '#f56c6c'] }, text: ['亏损', '盈利'] },
    calendar: { top: 20, left: 30, right: 30, range: calendarMonth.value, cellSize: ['auto', 20], itemStyle: { borderWidth: 1, borderColor: '#dcdee0' }, dayLabel: { firstDay: 1, nameMap: 'cn' }, monthLabel: { nameMap: 'cn' } },
    series: [{ type: 'heatmap', coordinateSystem: 'calendar', data }],
  }
})

const pnlAmountMap = computed(() => {
  const m: Record<string, number> = {}
  dailyPnlData.value.forEach(d => { m[d.date] = d.daily_pnl_amount })
  return m
})

const attributionChartOption = computed(() => ({
  tooltip: { trigger: 'item', formatter: '{b}: ¥{c} ({d}%)' },
  legend: { orient: 'vertical', left: 'left', top: 'middle', type: 'scroll' },
  series: [{
    type: 'pie', radius: ['40%', '70%'], center: ['60%', '50%'],
    data: attributionData.value.length > 0
      ? attributionData.value.map((a: any) => ({ name: a.sector_name, value: +a.contribution }))
      : [{ name: '暂无数据', value: 1 }],
    emphasis: { itemStyle: { shadowBlur: 10 } },
    label: { formatter: '{b}\n¥{c}' },
  }],
}))

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
  &:hover { box-shadow: var(--shadow-card); }
  .summary-label { font-size: 12px; color: var(--text-tertiary); margin-bottom: 6px; }
  .summary-value { font-size: 20px; font-weight: 700; font-family: var(--font-mono); }
}
.stats-row { margin-top: 12px; }
.stat-item {
  text-align: center; padding: 8px;
  background: var(--bg-tertiary); border-radius: var(--radius-sm);
  .stat-label { font-size: 12px; color: var(--text-tertiary); display: block; }
  .stat-val { font-size: 15px; font-weight: 600; }
}
</style>
