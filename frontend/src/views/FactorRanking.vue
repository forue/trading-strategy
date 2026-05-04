<template>
  <div class="factor-ranking">
    <div class="page-card">
      <div class="card-header">
        <span class="card-title">板块因子排名</span>
        <div class="header-actions">
          <el-select v-model="selectedStrategy" size="small" style="width: 100px">
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
            style="width: 160px"
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
          <v-chart :option="chartOption" style="height: 300px" autoresize />
        </div>

        <!-- 排名表格 -->
        <el-table :data="ranking" stripe size="small" :row-class-name="tableRowClassName">
          <el-table-column label="排名" width="60" align="center">
            <template #default="{ row }">
              <span :class="['rank-badge', getRankClass(row.rank)]">{{ row.rank }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="sector_name" label="板块名称" width="120" />
          <el-table-column prop="sector_code" label="板块代码" width="100" />
          <el-table-column label="综合评分" width="100" align="center" sortable sort-by="absolute_score">
            <template #default="{ row }">
              <span :style="{ color: getScoreColor(row.absolute_score), fontWeight: 600 }">
                {{ row.absolute_score?.toFixed(2) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="截面评分" width="100" align="center" sortable sort-by="rank_score">
            <template #default="{ row }">
              <span :style="{ color: getScoreColor(row.rank_score), fontWeight: 600 }">
                {{ row.rank_score?.toFixed(2) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="涨跌幅" width="80" align="center" sortable sort-by="change_pct">
            <template #default="{ row }">
              <span :style="{ color: row.change_pct >= 0 ? '#f56c6c' : '#67c23a' }">
                {{ row.change_pct >= 0 ? '+' : '' }}{{ row.change_pct?.toFixed(2) }}%
              </span>
            </template>
          </el-table-column>
          <el-table-column label="主力净流入" width="100" align="right" sortable sort-by="main_inflow">
            <template #default="{ row }">
              <span :style="{ color: row.main_inflow >= 0 ? '#f56c6c' : '#67c23a' }">
                {{ row.main_inflow?.toFixed(2) }}亿
              </span>
            </template>
          </el-table-column>
          <el-table-column label="北向净流入" width="100" align="right" sortable sort-by="north_inflow">
            <template #default="{ row }">
              <span :style="{ color: row.north_inflow >= 0 ? '#f56c6c' : '#67c23a' }">
                {{ row.north_inflow?.toFixed(2) }}亿
              </span>
            </template>
          </el-table-column>
          <el-table-column label="类别得分" min-width="200">
            <template #default="{ row }">
              <div class="category-scores">
                <span v-for="(cat, key) in row.category_scores" :key="key" class="cat-tag">
                  {{ getCategoryLabel(key) }}: {{ cat.score?.toFixed(1) }}
                </span>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <div v-else-if="!loading" style="padding: 40px; text-align: center; color: #909399">
        点击「查询排名」获取板块因子分析排名
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import VChart from 'vue-echarts'
import { strategyApi } from '@/api/strategy'

use([CanvasRenderer, BarChart, GridComponent, TooltipComponent])

const loading = ref(false)
const selectedStrategy = ref('MODERATE')
const selectedDate = ref('')
const actualDate = ref('')
const ranking = ref<any[]>([])

const strategyLabel = computed(() => {
  const map: Record<string, string> = { AGGRESSIVE: '激进', MODERATE: '稳健', CONSERVATIVE: '保守' }
  return map[selectedStrategy.value] || selectedStrategy.value
})

const chartOption = computed(() => {
  if (ranking.value.length === 0) return {}
  const top20 = ranking.value.slice(0, 20)
  return {
    tooltip: { trigger: 'axis' },
    grid: { left: 80, right: 20, top: 20, bottom: 30 },
    xAxis: {
      type: 'category',
      data: top20.map(r => r.sector_name),
      axisLabel: { rotate: 45, fontSize: 10 },
    },
    yAxis: { type: 'value', name: '综合评分' },
    series: [{
      type: 'bar',
      data: top20.map(r => ({
        value: r.absolute_score?.toFixed(2),
        itemStyle: { color: getScoreColor(r.absolute_score) },
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
  if (!score) return '#909399'
  if (score >= 7) return '#f56c6c'
  if (score >= 5) return '#e6a23c'
  if (score >= 3) return '#409eff'
  return '#67c23a'
}

function getRankClass(rank: number): string {
  if (rank <= 3) return 'top'
  if (rank <= 10) return 'good'
  return ''
}

function getCategoryLabel(key: string): string {
  const map: Record<string, string> = {
    capital_flow: '资金',
    momentum: '动量',
    technical: '技术',
    valuation: '估值',
    rotation: '轮动',
    sentiment: '情绪',
  }
  return map[key] || key
}

function tableRowClassName({ row }: { row: any }): string {
  if (row.rank <= 3) return 'top-row'
  if (row.rank <= 10) return 'good-row'
  return ''
}

onMounted(() => {
  fetchRanking()
})
</script>

<style lang="scss" scoped>
.factor-ranking { padding: 0; }
.page-card { background: #fff; border-radius: 12px; padding: 20px; box-shadow: 0 2px 12px rgba(0, 0, 0, 0.05); }
.card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.card-title { font-size: 16px; font-weight: 600; }
.header-actions { display: flex; gap: 8px; align-items: center; }
.chart-section { margin-bottom: 20px; }
.rank-badge {
  display: inline-block; width: 24px; height: 24px; line-height: 24px; text-align: center;
  border-radius: 50%; font-size: 12px; font-weight: 600;
  &.top { background: #fef0f0; color: #f56c6c; }
  &.good { background: #fdf6ec; color: #e6a23c; }
}
.category-scores { display: flex; flex-wrap: wrap; gap: 4px; }
.cat-tag { font-size: 11px; padding: 2px 6px; background: #f5f7fa; border-radius: 4px; color: #606266; }
:deep(.top-row) { background: #fef0f0 !important; }
:deep(.good-row) { background: #fdf6ec !important; }
</style>
