<template>
  <div class="review-page">
    <!-- 概览 -->
    <div class="page-card">
      <div class="card-header">
        <span class="card-title">策略复盘</span>
        <div class="header-actions">
          <el-select v-model="currentStrategy" size="small" class="ctrl-strategy">
            <el-option v-for="o in STRATEGY_OPTIONS" :key="o.value" :label="o.label" :value="o.value" />
          </el-select>
          <el-select v-model="horizonDays" size="small" class="ctrl-horizon">
            <el-option v-for="h in horizons" :key="h" :label="`持有 ${h} 交易日`" :value="h" />
          </el-select>
          <el-date-picker
            v-model="dateRange"
            type="daterange"
            size="small"
            value-format="YYYY-MM-DD"
            start-placeholder="开始日期"
            end-placeholder="结束日期"
            class="ctrl-daterange"
          />
          <el-button type="primary" size="small" :loading="loading" @click="loadPerformance">查询</el-button>
          <el-button size="small" :loading="backfilling" @click="runBackfill">回填收益</el-button>
        </div>
      </div>

      <el-alert v-if="perf" type="info" :closable="false" show-icon class="meta-alert">
        <template #title>
          策略: {{ strategyStore.strategyLabel }} |
          口径: T+1 开盘价买入，第 {{ perf.horizon_days }} 个交易日收盘价结算 |
          成本: 往返 {{ fmtPct(perf.cost_rate) }}（取自策略配置） |
          信号区间: {{ perf.first_signal_date || '—' }} ~ {{ perf.last_signal_date || '—' }}
        </template>
      </el-alert>

      <el-alert
        v-if="perf && perf.evaluated_count === 0 && perf.pending_count > 0"
        type="warning"
        :closable="false"
        show-icon
        class="meta-alert"
      >
        <template #title>
          {{ perf.pending_count }} 条信号尚未走完 {{ perf.horizon_days }} 个交易日的持有期（或次日开盘价缺失无法结算），暂无评估结果；可切换持有周期查看已评估数据
        </template>
      </el-alert>

      <div v-if="loading" style="padding: 40px; text-align: center">
        <el-skeleton :rows="6" animated />
      </div>

      <template v-else-if="perf">
        <div class="stat-grid">
          <div class="stat-card">
            <span class="stat-label">信号总数</span>
            <span class="stat-value">{{ perf.signal_count }}</span>
          </div>
          <div class="stat-card">
            <span class="stat-label">已评估 / 待评估</span>
            <span class="stat-value">{{ perf.evaluated_count }} <em>/ {{ perf.pending_count }}</em></span>
          </div>
          <div class="stat-card">
            <span class="stat-label">命中率</span>
            <span class="stat-value" :style="{ color: rateColor(perf.hit_rate) }">{{ fmtPct(perf.hit_rate) }}</span>
          </div>
          <div class="stat-card">
            <span class="stat-label">平均净收益</span>
            <span class="stat-value" :style="{ color: signColor(perf.avg_return) }">{{ fmtSignedPct(perf.avg_return) }}</span>
          </div>
          <div class="stat-card">
            <span class="stat-label">平均毛收益</span>
            <span class="stat-value" :style="{ color: signColor(perf.avg_return_gross) }">{{ fmtSignedPct(perf.avg_return_gross) }}</span>
          </div>
          <div class="stat-card">
            <span class="stat-label">盈亏比（净）</span>
            <span class="stat-value">{{ perf.profit_factor ?? '—' }}</span>
          </div>
          <div class="stat-card">
            <span class="stat-label">最佳 / 最差</span>
            <span class="stat-value sm">
              <em :style="{ color: '#f56c6c' }">{{ fmtSignedPct(perf.best_return) }}</em>
              <em :style="{ color: '#67c23a' }">{{ fmtSignedPct(perf.worst_return) }}</em>
            </span>
          </div>
        </div>

        <div class="chart-grid">
          <div class="chart-block">
            <div class="block-title">累计净收益（按结算日算术累计）</div>
            <v-chart v-if="perf.equity_curve.length" class="review-chart" :option="equityOption" autoresize />
            <el-empty v-else description="暂无已评估信号" :image-size="70" />
          </div>
          <div class="chart-block">
            <div class="block-title">月度命中率</div>
            <v-chart v-if="perf.monthly.length" class="review-chart" :option="monthlyOption" autoresize />
            <el-empty v-else description="暂无月度数据" :image-size="70" />
          </div>
        </div>

        <div class="detail-grid">
          <div class="detail-block">
            <div class="block-title">方向拆分</div>
            <el-table :data="directionRows" size="small" stripe>
              <el-table-column prop="label" label="方向" width="80" />
              <el-table-column prop="count" label="信号数" width="80" align="center" />
              <el-table-column label="命中率" width="80" align="center">
                <template #default="{ row }">{{ fmtPct(row.hit_rate) }}</template>
              </el-table-column>
              <el-table-column label="平均净收益" align="right">
                <template #default="{ row }">
                  <span :style="{ color: signColor(row.avg_return) }">{{ fmtSignedPct(row.avg_return) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="平均毛收益" align="right">
                <template #default="{ row }">
                  <span :style="{ color: signColor(row.avg_return_gross) }">{{ fmtSignedPct(row.avg_return_gross) }}</span>
                </template>
              </el-table-column>
            </el-table>
          </div>

          <div class="detail-block">
            <div class="block-title">板块表现（按样本数降序）</div>
            <el-table :data="perf.sectors" size="small" stripe max-height="280">
              <el-table-column prop="sector_name" label="板块" min-width="100" />
              <el-table-column prop="evaluated" label="样本" width="70" align="center" />
              <el-table-column label="命中率" width="80" align="center">
                <template #default="{ row }">{{ fmtPct(row.hit_rate) }}</template>
              </el-table-column>
              <el-table-column label="平均净收益" width="110" align="right">
                <template #default="{ row }">
                  <span :style="{ color: signColor(row.avg_return) }">{{ fmtSignedPct(row.avg_return) }}</span>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { storeToRefs } from 'pinia'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart, BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import VChart from 'vue-echarts'
import { ElMessage } from 'element-plus'
import { strategyApi, type SignalPerformance } from '@/api/strategy'
import { useThemeStore } from '@/stores/theme'
import { useStrategyStore, STRATEGY_OPTIONS } from '@/stores/strategy'

use([CanvasRenderer, LineChart, BarChart, GridComponent, TooltipComponent, LegendComponent])

const themeStore = useThemeStore()
const strategyStore = useStrategyStore()
const { currentStrategy } = storeToRefs(strategyStore)

const loading = ref(false)
const backfilling = ref(false)
const perf = ref<SignalPerformance | null>(null)
const horizonDays = ref(5)
const horizons = ref<number[]>([1, 3, 5, 10])
const dateRange = ref<string[]>([])

const directionRows = computed(() => {
  if (!perf.value) return []
  return [
    { label: '买入', ...perf.value.buy },
    { label: '卖出', ...perf.value.sell },
  ]
})

const isDark = computed(() => themeStore.mode === 'dark')
const axisColor = computed(() => (isDark.value ? '#9da1b0' : '#5a5f6e'))
const splitColor = computed(() => (isDark.value ? '#2a2d38' : '#ebeef5'))

const equityOption = computed(() => {
  const points = perf.value?.equity_curve || []
  return {
    tooltip: {
      trigger: 'axis',
      formatter: (params: any) => {
        const p = params[0]
        return `${p.name}<br/>累计净收益: ${p.value}%`
      },
    },
    grid: { left: 55, right: 20, top: 20, bottom: 40 },
    xAxis: {
      type: 'category',
      data: points.map(p => p.date),
      axisLabel: { color: axisColor.value, fontSize: 11 },
      axisLine: { lineStyle: { color: splitColor.value } },
    },
    yAxis: {
      type: 'value',
      name: '累计 %',
      nameTextStyle: { color: axisColor.value },
      axisLabel: { color: axisColor.value },
      splitLine: { lineStyle: { color: splitColor.value } },
    },
    series: [{
      type: 'line',
      smooth: true,
      showSymbol: false,
      areaStyle: { opacity: 0.12 },
      data: points.map(p => +(p.cum_return * 100).toFixed(2)),
      itemStyle: { color: '#409eff' },
    }],
  }
})

const monthlyOption = computed(() => {
  const items = perf.value?.monthly || []
  return {
    tooltip: {
      trigger: 'axis',
      formatter: (params: any) => {
        const p = params[0]
        return `${p.name}<br/>命中率: ${p.value}%`
      },
    },
    grid: { left: 45, right: 20, top: 20, bottom: 40 },
    xAxis: {
      type: 'category',
      data: items.map(m => m.month),
      axisLabel: { color: axisColor.value, fontSize: 11 },
      axisLine: { lineStyle: { color: splitColor.value } },
    },
    yAxis: {
      type: 'value',
      max: 100,
      axisLabel: { color: axisColor.value, formatter: '{value}%' },
      splitLine: { lineStyle: { color: splitColor.value } },
    },
    series: [{
      type: 'bar',
      barMaxWidth: 28,
      data: items.map(m => ({ value: +((m.hit_rate || 0) * 100).toFixed(1), itemStyle: { color: '#67c23a' } })),
    }],
  }
})

function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—'
  return `${(v * 100).toFixed(2)}%`
}

function fmtSignedPct(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—'
  const pct = v * 100
  return `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`
}

function rateColor(v: number | null | undefined): string {
  if (v === null || v === undefined) return 'var(--text-primary)'
  if (v >= 0.5) return '#f56c6c'
  if (v >= 0.4) return '#e6a23c'
  return '#67c23a'
}

function signColor(v: number | null | undefined): string {
  if (v === null || v === undefined) return 'var(--text-primary)'
  return v >= 0 ? '#f56c6c' : '#67c23a'
}

async function loadPerformance() {
  loading.value = true
  try {
    const data = await strategyApi.getSignalPerformance({
      strategyType: currentStrategy.value,
      horizonDays: horizonDays.value,
      startDate: dateRange.value?.[0],
      endDate: dateRange.value?.[1],
    })
    perf.value = data
    if (data?.horizons?.length) horizons.value = data.horizons
  } catch (e: any) {
    console.error('获取复盘统计失败:', e)
  } finally {
    loading.value = false
  }
}

async function runBackfill() {
  backfilling.value = true
  try {
    await strategyApi.backfillSignalOutcomes()
    ElMessage.success('收益回填完成')
    await loadPerformance()
  } catch (e: any) {
    console.error('回填收益失败:', e)
  } finally {
    backfilling.value = false
  }
}

// 全局策略切换时自动刷新复盘数据
watch(currentStrategy, () => loadPerformance())
watch(horizonDays, () => loadPerformance())

onMounted(() => {
  loadPerformance()
})
</script>

<style lang="scss" scoped>
.review-page { padding: 0; }
.card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; flex-wrap: wrap; gap: 8px; }
.card-title { font-size: 16px; font-weight: 600; color: var(--text-primary); }
.header-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.ctrl-strategy { width: 120px; max-width: 100%; }
.ctrl-horizon { width: 140px; max-width: 100%; }
.ctrl-daterange { width: 260px; max-width: 100%; }
.meta-alert { margin-bottom: 16px; }

.stat-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 12px;
  margin-bottom: 20px;
}
.stat-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 14px 16px;
  border-radius: var(--radius-md, 8px);
  background: var(--bg-tertiary);
  border: 1px solid var(--border-primary);
  .stat-label { font-size: 12px; color: var(--text-secondary); }
  .stat-value {
    font-size: 22px; font-weight: 600; color: var(--text-primary);
    em { font-size: 14px; font-style: normal; color: var(--text-secondary); margin-left: 4px; }
    &.sm { font-size: 15px; display: flex; gap: 12px; }
  }
}

.chart-grid, .detail-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-bottom: 20px;
}
.block-title { font-size: 14px; font-weight: 600; color: var(--text-primary); margin-bottom: 10px; }
.review-chart { height: 280px; }

@media (max-width: 900px) {
  .chart-grid, .detail-grid { grid-template-columns: 1fr; }
}

@media (max-width: 480px) {
  .card-header { flex-direction: column; align-items: flex-start; }
  .header-actions { width: 100%; }
  .ctrl-strategy, .ctrl-horizon, .ctrl-daterange { width: 100%; }
}
</style>
