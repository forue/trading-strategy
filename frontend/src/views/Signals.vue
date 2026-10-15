<template>
  <div class="signals-page">
    <!-- 筛选条件 -->
    <div class="page-card">
      <el-form :inline="true" :model="filterForm" size="default" class="filter-form">
        <el-form-item label="策略类型">
          <el-select v-model="filterForm.strategyType" style="width: 140px" placeholder="请选择策略">
            <el-option label="全部" value="ALL" />
            <el-option label="激进轮动" value="AGGRESSIVE" />
            <el-option label="稳健轮动" value="MODERATE" />
            <el-option label="保守轮动" value="CONSERVATIVE" />
          </el-select>
        </el-form-item>
        <el-form-item label="信号方向">
          <el-select v-model="filterForm.direction" style="width: 100px" placeholder="请选择方向">
            <el-option label="全部" value="ALL" />
            <el-option label="买入" value="BUY" />
            <el-option label="卖出" value="SELL" />
          </el-select>
        </el-form-item>
        <el-form-item label="日期范围">
          <el-date-picker v-model="dateRange" type="daterange" range-separator="至" start-placeholder="开始日期" end-placeholder="结束日期" value-format="YYYY-MM-DD" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="fetchSignals">查询</el-button>
        </el-form-item>
      </el-form>
    </div>

    <!-- 实时信号推送状态 -->
    <div class="page-card" style="margin-bottom: 20px">
      <div class="card-header">
        <span class="card-title">实时信号推送</span>
        <div class="ws-status">
          <el-badge :type="signalStore.isConnected ? 'success' : 'danger'" is-dot />
          <span>{{ signalStore.isConnected ? '已连接' : '未连接' }}</span>
          <el-button size="small" @click="toggleWs">
            {{ signalStore.isConnected ? '断开' : '连接' }}
          </el-button>
        </div>
      </div>
      <el-alert v-if="signalStore.currentSignals.length > 0" :title="`当前有 ${signalStore.currentSignals.length} 条未读信号`" type="warning" :closable="false" show-icon style="margin-bottom: 12px" />

      <el-alert
        v-if="todayStatus?.position_status === 'EMPTY'"
        type="info"
        :closable="false"
        show-icon
        style="margin-bottom: 12px"
      >
        <template #title>
          当前空仓（信号日期 {{ todayStatus.signal_date }}<span v-if="todayStatus.stale">，非今日数据</span>）
        </template>
        {{ todayStatus.empty_reason || '无板块满足买入条件，保持空仓' }}
      </el-alert>

      <el-alert
        v-else-if="todayStatus?.position_status === 'NO_DATA'"
        type="warning"
        :closable="false"
        show-icon
        style="margin-bottom: 12px"
        title="今日尚未生成信号"
      >
        未查询到信号记录，可点击"触发信号计算"手动生成。
      </el-alert>
    </div>

    <!-- 信号列表 -->
    <div class="page-card">
      <div class="card-header">
        <span class="card-title">信号列表</span>
        <el-button type="success" size="small" :loading="calculating" @click="triggerCalculate">
          <el-icon><Lightning /></el-icon> 触发信号计算
        </el-button>
      </div>

       <div class="responsive-table">
        <el-table :data="pagedSignals" stripe style="width: 100%" v-loading="loading">
        <el-table-column prop="signal_date" label="信号日期" width="110" />
        <el-table-column prop="strategy_type" label="策略类型" width="90">
          <template #default="{ row }">
            <el-tag :type="strategyTagMap[row.strategy_type]" size="small">{{ strategyLabelMap[row.strategy_type] || row.strategy_type }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="sector_name" label="板块" width="90" />
        <el-table-column label="推荐ETF" width="140">
          <template #default="{ row }">
            <span v-if="row.etf_code" class="etf-tag" @click="copyEtf(row.etf_code)">
              <el-tag type="primary" effect="plain" size="small">{{ row.etf_code }}</el-tag>
              <span class="etf-name">{{ row.etf_name }}</span>
            </span>
            <span v-else class="text-muted">--</span>
          </template>
        </el-table-column>
        <el-table-column prop="direction" label="方向" width="80">
          <template #default="{ row }">
            <el-tag v-if="isClearSignal(row)" type="warning" size="small">清仓</el-tag>
            <span v-else :class="row.direction === 'BUY' ? 'signal-buy' : 'signal-sell'">
              {{ row.direction === 'BUY' ? '买入' : '卖出' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="current_price" label="信号价" width="100">
          <template #default="{ row }">
            <span>{{ row.current_price != null ? '¥' + Number(row.current_price).toFixed(4) : '--' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="position_ratio" label="建议仓位" width="90">
          <template #default="{ row }">{{ (row.position_ratio * 100).toFixed(1) }}%</template>
        </el-table-column>
        <el-table-column prop="score" label="评分" width="90">
          <template #default="{ row }">
            <el-progress :percentage="Math.min(row.score * 10, 100)" :stroke-width="8" :color="row.score > 5 ? themeColors.good : row.score > 3 ? themeColors.warn : themeColors.bad" />
          </template>
        </el-table-column>
        <el-table-column prop="reason" label="信号原因" min-width="180" show-overflow-tooltip />
        <el-table-column prop="created_at" label="生成时间" width="170">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <template #empty>
          <el-empty :description="emptyDescription">
            <el-button type="primary" size="small" @click="triggerCalculate">触发信号计算</el-button>
          </el-empty>
        </template>
      </el-table>
      </div>

       <el-pagination
         v-model:current-page="pagination.page"
         v-model:page-size="pagination.size"
         :total="pagination.total"
         :page-sizes="[20, 50, 100]"
         layout="total, sizes, prev, pager, next"
         class="pagination-bar"
         @size-change="onSizeChange"
       />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, watch, onMounted } from 'vue'
import { signalApi } from '@/api/signal'
import { strategyApi } from '@/api/strategy'
import { useSignalStore } from '@/stores/signal'
import { useStrategyStore } from '@/stores/strategy'
import { useThemeStore } from '@/stores/theme'

// 语义色随主题切换：暗色下提高明度，保证与暗背景的对比度
const themeStore = useThemeStore()
const isDark = computed(() => themeStore.mode === 'dark')
const themeColors = computed(() => (isDark.value
  ? { good: '#357a5c', warn: '#e6a23c', bad: '#ff6f61' }
  : { good: '#67c23a', warn: '#e6a23c', bad: '#f56c6c' }))
import type { TradeSignal } from '@/api/signal'
import { ElMessage } from 'element-plus'
import dayjs from 'dayjs'

const signalStore = useSignalStore()
const strategyStore = useStrategyStore()
const loading = ref(false)
const calculating = ref(false)
const signalList = ref<TradeSignal[]>([])
const dateRange = ref<[string, string]>([
  dayjs().subtract(30, 'day').format('YYYY-MM-DD'),
  dayjs().format('YYYY-MM-DD'),
])

const filterForm = reactive({ strategyType: strategyStore.currentStrategy as string, direction: '' })
const pagination = reactive({ page: 1, size: 20, total: 0 })

// 今日持仓状态：空仓必须显式表达，避免"无信号"被误读为"没计算"
const todayStatus = ref<{
  position_status: 'HOLD' | 'EMPTY' | 'NO_DATA'
  signal_date: string
  stale: boolean
  market_regime: string
  empty_reason: string
} | null>(null)

async function fetchTodayStatus() {
  const type = filterForm.strategyType && filterForm.strategyType !== 'ALL'
    ? filterForm.strategyType
    : 'MODERATE'
  try {
    todayStatus.value = await strategyApi.getTodaySignals(type)
  } catch {
    todayStatus.value = null
  }
}

const strategyLabelMap: Record<string, string> = { AGGRESSIVE: '激进', MODERATE: '稳健', CONSERVATIVE: '保守' }
const strategyTagMap: Record<string, string> = { AGGRESSIVE: 'danger', MODERATE: 'warning', CONSERVATIVE: 'success' }

// Client-side filtering for direction (backend does not support direction filter)
const filteredSignals = computed(() => {
  let result = signalList.value
  if (filterForm.direction && filterForm.direction !== 'ALL') {
    result = result.filter(s => s.direction === filterForm.direction)
  }
  pagination.total = result.length
  return result
})

// 清仓信号：卖出且理由含"清仓"（如"市场不景气，空仓清仓"）
function isClearSignal(sig: any): boolean {
  return sig?.direction === 'SELL' && String(sig?.reason || '').includes('清仓')
}

// 空态文案需区分"已计算但空仓"与"尚未计算"
const emptyDescription = computed(() => {
  if (todayStatus.value?.position_status === 'EMPTY') {
    return todayStatus.value.empty_reason || '当前为空仓状态，无持仓信号'
  }
  if (todayStatus.value?.position_status === 'NO_DATA') {
    return '今日尚未生成信号'
  }
  return '暂无信号数据'
})

// Frontend pagination: slice data by current page
const pagedSignals = computed(() => {
  const start = (pagination.page - 1) * pagination.size
  const end = start + pagination.size
  return filteredSignals.value.slice(start, end)
})

// Handle page size change: reset to first page
function onSizeChange(size: number) {
  pagination.size = size
  pagination.page = 1
}

async function fetchSignals() {
  loading.value = true
  try {
    const startDate = dateRange.value?.[0] || dayjs().subtract(30, 'day').format('YYYY-MM-DD')
    const endDate = dateRange.value?.[1] || dayjs().format('YYYY-MM-DD')

    if (!filterForm.strategyType || filterForm.strategyType === 'ALL') {
      // "全部"：分别查询三种策略并合并
      const types: ('AGGRESSIVE' | 'MODERATE' | 'CONSERVATIVE')[] = ['AGGRESSIVE', 'MODERATE', 'CONSERVATIVE']
      const results = await Promise.all(
        types.map(t => signalApi.getSignalHistory({ strategyType: t, startDate, endDate }))
      )
      // 合并并按日期倒序排列
      const merged = results.flat()
      // 按时间倒序：最新记录置顶。优先用完整时间戳 created_at（同日内也能正确排序），
      // 缺失时回退到 signal_date
      merged.sort((a, b) => {
        const ta = a.created_at || a.signal_date || ''
        const tb = b.created_at || b.signal_date || ''
        return tb.localeCompare(ta)
      })
      signalList.value = merged
    } else {
      signalList.value = await signalApi.getSignalHistory({
        strategyType: filterForm.strategyType,
        startDate,
        endDate,
      })
    }
    pagination.page = 1 // 重置到第一页
    await fetchTodayStatus()
  } catch (e: any) {
    ElMessage.error(e?.message || '查询信号失败')
  } finally {
    loading.value = false
  }
}

async function triggerCalculate() {
  calculating.value = true
  try {
    const types = ['AGGRESSIVE', 'MODERATE', 'CONSERVATIVE']
    let total = 0
    for (const t of types) {
      const result = await strategyApi.calculateSignals(t)
      total += result?.length || 0
    }
    ElMessage.success(`信号计算完成，共生成 ${total} 条信号`)
    await fetchSignals()
  } catch (e: any) {
    ElMessage.error(e?.message || '信号计算失败')
  } finally {
    calculating.value = false
  }
}

function toggleWs() {
  if (signalStore.isConnected) {
    signalStore.disconnectWebSocket()
  } else {
    signalStore.connectWebSocket()
  }
}

function copyEtf(code: string) {
  navigator.clipboard.writeText(code).then(() => {
    ElMessage.success(`已复制ETF代码: ${code}`)
  }).catch(() => {})
}

function formatTime(val: string | null | undefined): string {
  if (!val) return '--'
  return val.replace('T', ' ').substring(0, 19)
}

// 全局策略切换时联动刷新信号列表
watch(() => strategyStore.currentStrategy, (v) => {
  filterForm.strategyType = v
  fetchSignals()
})

onMounted(() => fetchSignals())
</script>

<style lang="scss" scoped>
.ws-status { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--text-secondary); }
.etf-tag { cursor: pointer; display: inline-flex; align-items: center; gap: 4px; .etf-name { font-size: 12px; color: var(--text-secondary); } &:hover .el-tag { border-color: var(--accent-primary); } }
.text-muted { color: var(--text-tertiary); }
.pagination-bar { margin-top: 16px; justify-content: flex-end; display: flex; }

@media (max-width: 768px) {
  .filter-form { flex-wrap: wrap; }
  .pagination-bar { justify-content: center; }
}
</style>
