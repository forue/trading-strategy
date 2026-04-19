<template>
  <div class="fund-page">
    <!-- 账户概览 -->
    <el-row :gutter="20" class="summary-row">
      <el-col :span="6" v-for="item in summaryItems" :key="item.label">
        <div class="summary-card">
          <div class="summary-label">{{ item.label }}</div>
          <div class="summary-value" :style="{ color: item.color }">{{ item.value }}</div>
        </div>
      </el-col>
    </el-row>

    <el-row :gutter="20">
      <!-- 净值曲线 -->
      <el-col :span="16">
        <div class="page-card">
          <div class="card-header">
            <span class="card-title">账户净值曲线</span>
            <el-form :inline="true" size="small">
              <el-form-item>
                <el-select v-model="navStrategy" style="width: 120px">
                  <el-option label="激进" value="AGGRESSIVE" />
                  <el-option label="稳健" value="MODERATE" />
                  <el-option label="保守" value="CONSERVATIVE" />
                </el-select>
              </el-form-item>
              <el-form-item>
                <el-date-picker v-model="navDateRange" type="daterange" range-separator="至" start-placeholder="开始" end-placeholder="结束" value-format="YYYY-MM-DD" size="small" />
              </el-form-item>
            </el-form>
          </div>
          <v-chart :option="navChartOption" style="height: 380px" autoresize />
        </div>
      </el-col>

      <!-- 收益归因 -->
      <el-col :span="8">
        <div class="page-card">
          <div class="card-header">
            <span class="card-title">收益归因分析</span>
          </div>
          <v-chart :option="attributionChartOption" style="height: 380px" autoresize />
        </div>
      </el-col>
    </el-row>

    <!-- 当前持仓 -->
    <div class="page-card" style="margin-top: 20px">
      <div class="card-header">
        <span class="card-title">当前持仓</span>
        <el-select v-model="positionStrategy" size="small" style="width: 120px">
          <el-option label="全部" value="" />
          <el-option label="激进" value="AGGRESSIVE" />
          <el-option label="稳健" value="MODERATE" />
          <el-option label="保守" value="CONSERVATIVE" />
        </el-select>
      </div>
      <el-table :data="positions" stripe>
        <el-table-column prop="sector_name" label="板块" width="120" />
        <el-table-column prop="strategy_type" label="策略" width="100">
          <template #default="{ row }">
            <el-tag size="small">{{ row.strategy_type }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="direction" label="方向" width="80">
          <template #default="{ row }">
            <span :class="row.direction === 'BUY' ? 'signal-buy' : 'signal-sell'">{{ row.direction === 'BUY' ? '多' : '空' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="quantity" label="数量" width="100" />
        <el-table-column prop="avg_price" label="均价" width="100" />
        <el-table-column prop="current_price" label="现价" width="100" />
        <el-table-column label="盈亏" width="120">
          <template #default="{ row }">
            <span :style="{ color: row.current_price > row.avg_price ? '#f56c6c' : '#67c23a' }">
              {{ row.current_price && row.avg_price ? ((row.current_price - row.avg_price) / row.avg_price * 100).toFixed(2) + '%' : '--' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="position_ratio" label="仓位占比" width="100">
          <template #default="{ row }">{{ (row.position_ratio * 100).toFixed(1) }}%</template>
        </el-table-column>
        <el-table-column prop="opened_at" label="开仓时间" min-width="160" />
      </el-table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { LineChart, PieChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { fundApi } from '@/api/fund'
import type { Position, NavRecord, ReturnAttribution } from '@/api/fund'
import dayjs from 'dayjs'

use([LineChart, PieChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

const navStrategy = ref('MODERATE')
const positionStrategy = ref('')
const navDateRange = ref<[string, string]>([dayjs().subtract(3, 'month').format('YYYY-MM-DD'), dayjs().format('YYYY-MM-DD')])
const positions = ref<Position[]>([])
const navData = ref<NavRecord[]>([])
const attributionData = ref<ReturnAttribution[]>([])

const summaryItems = ref([
  { label: '总资产', value: '--', color: '#303133' },
  { label: '可用资金', value: '--', color: '#409eff' },
  { label: '持仓市值', value: '--', color: '#e6a23c' },
  { label: '累计收益率', value: '--', color: '#67c23a' },
])

const navChartOption = computed(() => {
  if (navData.value.length === 0) return {}
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['账户净值', '累计收益率'] },
    xAxis: { type: 'category', data: navData.value.map(d => d.nav_date) },
    yAxis: [
      { type: 'value', name: '净值', scale: true },
      { type: 'value', name: '收益率%', scale: true, axisLabel: { formatter: '{value}%' } },
    ],
    series: [
      { name: '账户净值', type: 'line', data: navData.value.map(d => d.total_assets), smooth: true, lineStyle: { width: 2 }, itemStyle: { color: '#409eff' }, areaStyle: { color: 'rgba(64,158,255,0.1)' } },
      { name: '累计收益率', type: 'line', yAxisIndex: 1, data: navData.value.map(d => (d.cumulative_return * 100).toFixed(2)), smooth: true, lineStyle: { width: 2, type: 'dashed' }, itemStyle: { color: '#67c23a' } },
    ],
  }
})

const attributionChartOption = computed(() => ({
  tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
  legend: { orient: 'vertical', left: 'left', top: 'middle' },
  series: [{
    type: 'pie', radius: ['40%', '70%'], center: ['60%', '50%'],
    data: attributionData.value.length > 0
      ? attributionData.value.map(a => ({ name: a.sector_name, value: +a.contribution.toFixed(4) }))
      : [{ name: '银行', value: 0.03 }, { name: '电子', value: 0.02 }, { name: '医药', value: -0.01 }, { name: '食品', value: 0.015 }],
    emphasis: { itemStyle: { shadowBlur: 10, shadowOffsetX: 0, shadowColor: 'rgba(0,0,0,0.3)' } },
  }],
}))

onMounted(async () => {
  try {
    const summary = await fundApi.getAccountSummary()
    summaryItems.value[0].value = `¥${(summary.total_assets / 10000).toFixed(2)}万`
    summaryItems.value[1].value = `¥${(summary.cash / 10000).toFixed(2)}万`
    summaryItems.value[2].value = `¥${(summary.market_value / 10000).toFixed(2)}万`
    summaryItems.value[3].value = `${((summary.cumulative_return || 0) * 100).toFixed(2)}%`
  } catch {}

  try {
    positions.value = await fundApi.getPositions(positionStrategy.value || undefined)
  } catch {}

  try {
    navData.value = await fundApi.getNavCurve({
      strategyType: navStrategy.value,
      startDate: navDateRange.value?.[0] || '',
      endDate: navDateRange.value?.[1] || '',
    })
  } catch {}

  try {
    attributionData.value = await fundApi.getReturnAttribution({
      strategyType: navStrategy.value,
      startDate: navDateRange.value?.[0] || '',
      endDate: navDateRange.value?.[1] || '',
    })
  } catch {}
})
</script>

<style lang="scss" scoped>
.summary-row { margin-bottom: 20px; }
.summary-card { background: #fff; border-radius: 8px; padding: 24px; text-align: center; box-shadow: 0 1px 4px rgba(0,0,0,0.05); .summary-label { font-size: 14px; color: #909399; margin-bottom: 8px; } .summary-value { font-size: 26px; font-weight: bold; } }
.card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; .card-title { font-size: 16px; font-weight: 600; } }
.signal-buy { color: #f56c6c; font-weight: bold; }
.signal-sell { color: #67c23a; font-weight: bold; }
</style>
