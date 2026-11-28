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
              <em :style="{ color: 'var(--accent-danger)' }">{{ fmtSignedPct(perf.best_return) }}</em>
              <em :style="{ color: 'var(--accent-success)' }">{{ fmtSignedPct(perf.worst_return) }}</em>
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
            <!-- 手机端：五列表格在卡片内只剩 366px，改为「标题 + 指标网格」 -->
            <ul v-if="isMobile" class="m-metric-list">
              <li v-for="row in directionRows" :key="row.label" class="m-metric-card">
                <div class="m-metric-head">
                  <span class="m-metric-name">{{ row.label }}</span>
                  <span class="m-metric-hit">命中 {{ fmtPct(row.hit_rate) }}</span>
                </div>
                <div class="m-metric-grid">
                  <div><em>信号数</em><b>{{ row.count }}</b></div>
                  <div><em>平均净收益</em><b :style="{ color: signColor(row.avg_return) }">{{ fmtSignedPct(row.avg_return) }}</b></div>
                  <div><em>平均毛收益</em><b :style="{ color: signColor(row.avg_return_gross) }">{{ fmtSignedPct(row.avg_return_gross) }}</b></div>
                </div>
              </li>
            </ul>

            <div v-else class="responsive-table">
              <el-table :data="directionRows" stripe>
                <el-table-column prop="label" label="方向" width="80" />
                <el-table-column prop="count" label="信号数" width="80" align="right" />
                <el-table-column label="命中率" width="80" align="right">
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
          </div>

          <div class="detail-block">
            <div class="block-title">板块表现（按样本数降序）</div>
            <!-- 手机端：板块表现改为单行区块 -->
            <ul v-if="isMobile" class="m-sector-list">
              <li v-for="row in perf.sectors" :key="row.sector_name" class="m-sector-row">
                <span class="m-sector-name">{{ row.sector_name }}</span>
                <span class="m-sector-return" :style="{ color: signColor(row.avg_return) }">{{ fmtSignedPct(row.avg_return) }}</span>
                <span class="m-sector-meta">{{ row.evaluated }} 样本 · 命中 {{ fmtPct(row.hit_rate) }}</span>
              </li>
              <li v-if="!perf.sectors.length" class="m-list-empty">暂无板块样本</li>
            </ul>

            <div v-else class="responsive-table">
              <el-table :data="perf.sectors" stripe max-height="280">
                <el-table-column prop="sector_name" label="板块" min-width="96" />
                <el-table-column prop="evaluated" label="样本" width="64" align="right" />
                <el-table-column label="命中率" width="80" align="right">
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
import { useBreakpoint } from '@/composables/useBreakpoint'

const { isMobile } = useBreakpoint()

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
    grid: { left: 55, right: 20, top: 40, bottom: 40 },
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
      itemStyle: { color: '#4051E0' },
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
      data: items.map(m => ({ value: +((m.hit_rate || 0) * 100).toFixed(1), itemStyle: { color: '#4051E0', borderRadius: [4, 4, 0, 0] } })),
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
  if (v >= 0.5) return 'var(--accent-danger)'
  if (v >= 0.4) return 'var(--accent-warning)'
  return 'var(--accent-success)'
}

function signColor(v: number | null | undefined): string {
  if (v === null || v === undefined) return 'var(--text-primary)'
  return v >= 0 ? 'var(--accent-danger)' : 'var(--accent-success)'
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
.card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; flex-wrap: wrap; gap: 8px; }
.card-title { font-size: 18px; font-weight: 600; color: var(--text-primary); }
.header-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.ctrl-strategy { width: 120px; max-width: 100%; }
.ctrl-horizon { width: 140px; max-width: 100%; }
.ctrl-daterange { width: 260px; max-width: 100%; }
.meta-alert { margin-bottom: 16px; }

.stat-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  .stat-label { font-size: 12px; color: var(--text-tertiary); }
  .stat-value {
    font-family: var(--font-mono); font-size: 30px; font-weight: 600; letter-spacing: -.04em; color: var(--text-primary);
    em { font-family: var(--font-sans); font-size: 14px; font-style: normal; color: var(--text-secondary); margin-left: 4px; letter-spacing: 0; }
    &.sm { font-size: 15px; display: flex; gap: 12px; }
  }
}

.chart-grid, .detail-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-bottom: 20px;
}
.chart-block, .detail-block {
  background: var(--bg-surface);
  border: 1px solid var(--border-primary);
  border-radius: var(--radius-md);
  padding: 16px;
  /* grid 项默认 min-width:auto，下界取内容 min-content。表格空态（新账号还没信号）时
     EP 会给 .el-table__empty-block 写内联 width（= 当前表格宽），而 index.scss 的
     .responsive-table .el-table{min-width:100%} 又要求表格宽 ≥ 容器宽 —— 表格宽与
     轨道宽互为输入，每次 ResizeObserver 回调都放大一次，表现为「板块表现」表格
     越撑越宽（实测 8 秒从 10725px 涨到 19827px），横向滚动条无限延伸。
     有数据时 empty-block 不渲染，所以只有空表的账号能复现。min-width:0 断开回环。 */
  min-width: 0;
}
.block-title {
  font-size: 14px; font-weight: 600; color: var(--text-primary);
  display: flex; align-items: center; gap: 8px; margin-bottom: 14px;
  &::before { content: ''; width: 2px; height: 13px; border-radius: 1px; background: var(--accent-primary); flex-shrink: 0; }
}
.review-chart { height: var(--chart-h-md); }

/* ─── 手机端指标块 / 板块列表（替代宽表格） ─── */
.m-metric-list, .m-sector-list {
  list-style: none;
  margin: 0;
  padding: 0;
}

.m-metric-card {
  padding: 7px 0;
  border-bottom: 1px solid var(--border-subtle);

  &:last-child { border-bottom: none; }
}

.m-metric-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;

  .m-metric-name { font-size: 12px; font-weight: 600; color: var(--text-primary); }
  .m-metric-hit { font-size: 11px; color: var(--text-secondary); font-family: var(--font-mono); }
}

.m-metric-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 4px;
  margin-top: 5px;

  & > div {
    display: flex;
    flex-direction: column;
    gap: 1px;
    min-width: 0;
    padding: 4px 5px;
    background: var(--bg-tertiary);
    border-radius: 4px;

    em { font-style: normal; font-size: 10px; color: var(--text-tertiary); }
    b { font-size: 11px; font-weight: 600; font-family: var(--font-mono); }
  }
}

.m-sector-row {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 1px 8px;
  padding: 7px 0;
  border-bottom: 1px solid var(--border-subtle);

  &:last-child { border-bottom: none; }

  .m-sector-name {
    font-size: 12px;
    color: var(--text-primary);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .m-sector-return { font-size: 12px; font-weight: 600; font-family: var(--font-mono); }
  .m-sector-meta { grid-column: 1 / -1; font-size: 10px; color: var(--text-tertiary); }
}

.m-list-empty {
  padding: 20px 0;
  text-align: center;
  font-size: 11px;
  color: var(--text-tertiary);
}

@media (max-width: 900px) {
  .chart-grid, .detail-grid { grid-template-columns: 1fr; }
}

@media (max-width: 768px) {
  .stat-value { font-size: 20px; overflow-wrap: anywhere; }
  .stat-value.sm { flex-wrap: wrap; gap: 6px; }
  .header-actions { width: 100%; display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
  /* el-date-picker 根节点丢了本组件的 data-v，也不接收 class，.ctrl-daterange 是死规则，
     只能用结构选择器；同时栅格里的 el-button 会带上 EP 的 margin-left:12px，
     表现为「回填收益」在行首仍然右移 12px */
  .header-actions > :deep(.el-date-editor) { grid-column: 1 / -1; width: 100% !important; }
  .header-actions > :deep(.el-button) { margin-left: 0 !important; }
  .ctrl-strategy, .ctrl-horizon { width: 100%; }
  .card-header { flex-direction: column; align-items: stretch; margin-bottom: 12px; }
  .chart-grid, .detail-grid { gap: 8px; margin-bottom: 8px; }
  .chart-block, .detail-block { padding: 10px; border-radius: 8px; }
}

@media (max-width: 480px) {
  .card-header { margin-bottom: 10px; gap: 6px; }
  .meta-alert { margin-bottom: 8px; }
  .stat-card {
    gap: 2px;
    padding: 8px;

    .stat-label { font-size: 10px; }
    .stat-value {
      font-size: 18px;
      em { font-size: 11px; margin-left: 2px; }
      &.sm { font-size: 12px; }
    }
  }
  .block-title { font-size: 12px; margin-bottom: 8px; &::before { height: 11px; } }
  .review-chart { height: var(--chart-h-sm); }
}
</style>
