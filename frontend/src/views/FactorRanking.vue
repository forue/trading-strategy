<template>
  <div class="factor-ranking">
    <div class="page-card">
      <div class="card-header">
        <span class="card-title">板块因子排名</span>
        <div class="header-actions">
          <el-select v-model="selectedStrategy" size="small" class="rank-strategy-select">
            <el-option label="激进" value="AGGRESSIVE" />
            <el-option label="稳健" value="MODERATE" />
            <el-option label="保守" value="CONSERVATIVE" />
          </el-select>
          <el-date-picker
            v-model="selectedDate"
            type="date"
            size="small"
            value-format="YYYY-MM-DD"
            placeholder="选择日期（默认最新）"
            class="rank-date-picker"
          />
          <el-button type="primary" size="small" @click="fetchRanking" :loading="loading">
            查询排名
          </el-button>
        </div>
      </div>

      <el-alert v-if="actualDate" type="info" :closable="false" show-icon style="margin-bottom: 16px">
        <template #title>
          数据日期: {{ actualDate }} | 策略: {{ strategyLabel }} | 共 {{ ranking.length }} 个板块
        </template>
      </el-alert>

      <div v-if="loading" style="padding: 40px; text-align: center">
        <el-skeleton :rows="10" animated />
      </div>

      <div v-else-if="ranking.length > 0">
        <!-- 评分分布图 -->
        <div class="chart-section">
          <v-chart :option="chartOption" class="rank-chart" autoresize />
        </div>

        <!-- 手机端：九列排名表改为排名条目 -->
        <ul v-if="bp.isMobile.value" class="m-rank-list">
          <li v-for="row in ranking" :key="row.sector_code || row.sector_name" class="m-rank-row">
            <span :class="['rank-badge', getRankClass(row.rank)]">{{ row.rank }}</span>
            <div class="m-rank-main">
              <div class="m-rank-top">
                <span class="m-rank-name">{{ row.sector_name }}</span>
                <span class="m-rank-score" :style="{ color: getScoreColor(row.composite_score) }">
                  {{ row.composite_score?.toFixed(2) }}
                </span>
              </div>
              <div class="m-rank-sub">
                <span :style="{ color: row.change_pct >= 0 ? 'var(--accent-danger)' : 'var(--accent-success)' }">
                  {{ row.change_pct >= 0 ? '+' : '' }}{{ row.change_pct?.toFixed(2) }}%
                </span>
                <span :style="{ color: row.main_inflow >= 0 ? 'var(--accent-danger)' : 'var(--accent-success)' }">
                  主力 {{ row.main_inflow?.toFixed(2) }}亿
                </span>
                <span v-if="row.abs_composite_score != null">绝对 {{ row.abs_composite_score?.toFixed(2) }}</span>
              </div>
              <div class="category-scores">
                <span
                  v-for="(score, key) in row.category_scores"
                  :key="key"
                  class="cat-tag"
                  :style="catScoreStyle(score)"
                >
                  {{ getCategoryLabel(key) }}: {{ catScoreValue(score)?.toFixed(1) }}
                </span>
              </div>
            </div>
          </li>
        </ul>

        <!-- 排名表格（桌面端） -->
        <div v-else class="responsive-table"><el-table :data="ranking" stripe size="small">
          <el-table-column label="排名" width="64" align="center">
            <template #default="{ row }">
              <span :class="['rank-badge', getRankClass(row.rank)]">{{ row.rank }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="sector_name" label="板块名称" width="120" />
          <el-table-column prop="sector_code" label="板块代码" width="96" class-name="hide-mobile" label-class-name="hide-mobile" />
          <el-table-column label="综合评分" width="96" align="right" sortable sort-by="composite_score">
            <template #default="{ row }">
              <span :style="{ color: getScoreColor(row.composite_score), fontWeight: 600 }">
                {{ row.composite_score?.toFixed(2) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="绝对评分" width="96" align="right" sortable sort-by="abs_composite_score" class-name="hide-mobile" label-class-name="hide-mobile">
            <template #default="{ row }">
              <span :style="{ color: getScoreColor(row.abs_composite_score), fontWeight: 600 }">
                {{ row.abs_composite_score?.toFixed(2) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="截面评分" width="96" align="right" sortable sort-by="rank_composite_score" class-name="hide-mobile" label-class-name="hide-mobile">
            <template #default="{ row }">
              <span :style="{ color: getScoreColor(row.rank_composite_score), fontWeight: 600 }">
                {{ row.rank_composite_score?.toFixed(2) || '—' }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="涨跌幅" width="80" align="right" sortable sort-by="change_pct">
            <template #default="{ row }">
              <span :style="{ color: row.change_pct >= 0 ? 'var(--accent-danger)' : 'var(--accent-success)' }">
                {{ row.change_pct >= 0 ? '+' : '' }}{{ row.change_pct?.toFixed(2) }}%
              </span>
            </template>
          </el-table-column>
          <el-table-column label="主力净流入" width="96" align="right" sortable sort-by="main_inflow" class-name="hide-mobile" label-class-name="hide-mobile">
            <template #default="{ row }">
              <span :style="{ color: row.main_inflow >= 0 ? 'var(--accent-danger)' : 'var(--accent-success)' }">
                {{ row.main_inflow?.toFixed(2) }}亿
              </span>
            </template>
          </el-table-column>
          <!-- 北向资金数据源已停止披露，列置灰停用 -->
          <el-table-column label="北向净流入" width="120" align="right" sortable sort-by="north_inflow" label-class-name="col-disabled hide-mobile" class-name="col-disabled hide-mobile">
            <template #header>
              <el-tooltip content="沪深港通自 2024-08-19 起停止披露北向资金净买额，该列已停用" placement="top">
                <span>北向净流入<el-tag size="small" type="info" effect="plain">已停用</el-tag></span>
              </el-tooltip>
            </template>
            <template #default="{ row }">
              <span class="disabled-text">{{ row.north_inflow?.toFixed(2) }}亿</span>
            </template>
          </el-table-column>
          <el-table-column label="类别得分" min-width="200">
            <template #default="{ row }">
              <div class="category-scores">
                <span
                  v-for="(score, key) in row.category_scores"
                  :key="key"
                  class="cat-tag"
                  :style="catScoreStyle(score)"
                >
                  {{ getCategoryLabel(key) }}: {{ catScoreValue(score)?.toFixed(1) }}
                </span>
              </div>
            </template>
          </el-table-column>
        </el-table></div>
      </div>

      <div v-else-if="!loading" style="padding: 40px; text-align: center; color: #909399">
        点击「查询排名」获取板块因子分析排名
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import VChart from 'vue-echarts'
import { strategyApi } from '@/api/strategy'
import { useThemeStore } from '@/stores/theme'
import { useStrategyStore } from '@/stores/strategy'
import { useBreakpoint } from '@/composables/useBreakpoint'

use([CanvasRenderer, BarChart, GridComponent, TooltipComponent])

const bp = useBreakpoint()
const themeStore = useThemeStore()
const strategyStore = useStrategyStore()

const loading = ref(false)
const selectedStrategy = ref(strategyStore.currentStrategy as string)
const selectedDate = ref('')
const actualDate = ref('')
const ranking = ref<any[]>([])

const strategyLabel = computed(() => {
  const map: Record<string, string> = { AGGRESSIVE: '激进', MODERATE: '稳健', CONSERVATIVE: '保守' }
  return map[selectedStrategy.value] || selectedStrategy.value
})

const chartOption = computed(() => {
  if (ranking.value.length === 0) return {}
  const topCount = bp.isMobile.value ? 12 : bp.isTablet.value ? 16 : 20
  const topN = ranking.value.slice(0, topCount)
  const isDark = themeStore.mode === 'dark'
  return {
    tooltip: {
      trigger: 'axis',
      formatter: (params: any) => {
        const p = params[0]
        return `${p.name}<br/>综合评分: ${p.value}`
      }
    },
    grid: { left: 60, right: 20, top: 40, bottom: 80 },
    xAxis: {
      type: 'category',
      data: topN.map(r => r.sector_name),
      axisLabel: { rotate: bp.isMobile.value ? 90 : 45, fontSize: bp.isMobile.value ? 10 : 11, interval: bp.labelInterval(topN.length), color: isDark ? '#9da1b0' : '#5a5f6e' },
      axisLine: { lineStyle: { color: isDark ? '#2a2d38' : '#e4e7ed' } },
    },
    yAxis: {
      type: 'value', name: '综合评分', min: 0, max: 10,
      nameTextStyle: { color: isDark ? '#9da1b0' : '#5a5f6e' },
      axisLabel: { color: isDark ? '#646878' : '#9499a6' },
      splitLine: { lineStyle: { color: isDark ? '#2a2d38' : '#ebeef5' } },
    },
    series: [{
      type: 'bar',
      data: topN.map(r => ({
        value: r.composite_score?.toFixed(2),
        itemStyle: { color: getScoreColor(r.composite_score) },
      })),
    }],
  }
})

async function fetchRanking() {
  loading.value = true
  try {
    const body: any = {
      strategy_type: selectedStrategy.value,
    }
    if (selectedDate.value) body.date = selectedDate.value
    const data = await strategyApi.analyzeFactorsBatch(body)
    actualDate.value = data?.date || ''
    ranking.value = data?.rankings || []
  } catch (e: any) {
    console.error('批量因子分析失败:', e)
  } finally {
    loading.value = false
  }
}

function getScoreColor(score: number): string {
  if (!score) return 'var(--text-tertiary)'
  // 蓝色单色系深浅表达评分高低，避免红黄绿混杂；
  // 色阶整体压在白底 4.5:1 以上，浅色主题不能再用 #C3CCF7 这类 1.6:1 的淡蓝
  const dark = themeStore.mode === 'dark'
  if (dark) {
    if (score >= 7) return '#A9BCFF'
    if (score >= 5) return '#93A8F5'
    if (score >= 3) return '#7B8FD8'
    return '#7A85A0'
  }
  if (score >= 7) return '#2E4FA8'
  if (score >= 5) return '#3E5FC4'
  if (score >= 3) return '#5468CE'
  return '#6B7595'
}

function catScoreValue(score: any): number | undefined {
  return typeof score === 'object' ? score?.score : score
}

// 类别得分按高低分级着色：与综合评分一致用蓝色单色系，高分深蓝醒目、低分浅色收敛
function catScoreStyle(score: any): Record<string, string> {
  const v = catScoreValue(score)
  const dark = themeStore.mode === 'dark'
  if (v === undefined || v === null) return { color: 'var(--text-secondary)', background: 'var(--bg-tertiary)' }
  if (v >= 7) return { color: dark ? '#A9BCFF' : '#2E4FA8', background: dark ? 'rgba(99,126,232,.22)' : '#E4EAFB' }
  if (v >= 5) return { color: dark ? '#9BB0F8' : '#3E5FC4', background: dark ? 'rgba(99,126,232,.16)' : '#EDF1FD' }
  if (v >= 3) return { color: dark ? '#8A93A6' : '#5468CE', background: dark ? 'rgba(99,126,232,.1)' : '#F4F6FE' }
  return { color: 'var(--text-secondary)', background: 'var(--bg-tertiary)' }
}

function getRankClass(rank: number): string {
  if (rank <= 3) return 'top'
  if (rank <= 10) return 'good'
  return ''
}

function getCategoryLabel(key: string | number): string {
  const map: Record<string, string> = {
    capital_flow: '资金',
    momentum: '动量',
    technical: '技术',
    valuation: '估值',
    rotation: '轮动',
    sentiment: '情绪',
  }
  return map[String(key)] || String(key)
}

// 全局策略切换时联动刷新排名
watch(() => strategyStore.currentStrategy, (v) => {
  selectedStrategy.value = v
  fetchRanking()
})

onMounted(() => {
  fetchRanking()
})
</script>

<style lang="scss" scoped>
.factor-ranking { padding: 0; }
.card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; flex-wrap: wrap; gap: 8px; }
.card-title { font-size: 18px; font-weight: 600; color: var(--text-primary); }
.header-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.rank-strategy-select { width: 100px; max-width: 100%; }
.rank-date-picker { width: 160px; max-width: 100%; }
.chart-section { margin-bottom: 20px; }
.rank-chart { height: var(--chart-h-lg); width: 100%; }
.rank-badge {
  display: inline-block; width: 24px; height: 24px; line-height: 24px; text-align: center;
  border-radius: 50%; font-size: 12px; font-weight: 600;
  &.top { background: var(--accent-danger-light); color: var(--accent-danger); }
  &.good { background: var(--accent-warning-light); color: var(--accent-warning); }
}
.category-scores { display: flex; flex-wrap: wrap; gap: 4px; }
.disabled-text { color: var(--text-tertiary); }
::deep(.col-disabled) { color: var(--text-tertiary) !important; }
::deep(.col-disabled .el-tag) { margin-left: 4px; transform: scale(0.85); }
.cat-tag {
  display: inline-block;
  min-width: 72px;
  box-sizing: border-box;
  text-align: center;
  font-size: 11px; padding: 2px 6px;
  border-radius: var(--radius-sm);
  font-weight: 500;
  white-space: nowrap;
}
/* ─── 手机端排名条目 ─── */
.m-rank-list {
  list-style: none;
  margin: 0;
  padding: 0;
}

.m-rank-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 8px 0;
  border-bottom: 1px solid var(--border-subtle);

  &:last-child { border-bottom: none; }

  .rank-badge {
    flex: none;
    width: 20px;
    height: 20px;
    line-height: 20px;
    font-size: 10px;
  }
}

.m-rank-main { flex: 1; min-width: 0; }

.m-rank-top {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;

  .m-rank-name {
    font-size: 12px;
    font-weight: 600;
    color: var(--text-primary);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .m-rank-score { font-size: 13px; font-weight: 600; font-family: var(--font-mono); }
}

.m-rank-sub {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 2px;
  font-size: 11px;
  color: var(--text-tertiary);
  font-family: var(--font-mono);
}

@media (max-width: 768px) {
  .card-header { flex-direction: column; align-items: stretch; margin-bottom: 12px; }
  .header-actions { width: 100%; display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
  .rank-strategy-select,
  .rank-date-picker { width: 100%; }
  .header-actions .el-button { grid-column: 1 / -1; }
  .rank-chart { height: var(--chart-h-md); }
  .chart-section { margin-bottom: 8px; }
}

@media (max-width: 480px) {
  .rank-chart { height: var(--chart-h-sm); }
  .rank-badge { width: 22px; height: 22px; line-height: 22px; font-size: 11px; }
  .cat-tag { min-width: 0; font-size: 11px; padding: 1px 5px; }
  .category-scores { gap: 3px; margin-top: 4px; }
}
</style>
