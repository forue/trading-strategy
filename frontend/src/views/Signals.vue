<template>
  <div class="signals-page">
    <!-- 筛选条件 -->
    <div class="page-card">
      <el-form :inline="true" :model="filterForm" size="default">
        <el-form-item label="策略类型">
          <el-select v-model="filterForm.strategyType" style="width: 140px">
            <el-option label="全部" value="" />
            <el-option label="激进轮动" value="AGGRESSIVE" />
            <el-option label="稳健轮动" value="MODERATE" />
            <el-option label="保守轮动" value="CONSERVATIVE" />
          </el-select>
        </el-form-item>
        <el-form-item label="信号方向">
          <el-select v-model="filterForm.direction" style="width: 100px">
            <el-option label="全部" value="" />
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
    </div>

    <!-- 信号列表 -->
    <div class="page-card">
      <div class="card-header">
        <span class="card-title">信号列表</span>
        <el-button type="success" size="small" :loading="calculating" @click="triggerCalculate">
          <el-icon><Lightning /></el-icon> 触发信号计算
        </el-button>
      </div>

      <el-table :data="filteredSignals" stripe style="width: 100%" v-loading="loading">
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
        <el-table-column prop="direction" label="方向" width="70">
          <template #default="{ row }">
            <span :class="row.direction === 'BUY' ? 'signal-buy' : 'signal-sell'">
              {{ row.direction === 'BUY' ? '买入' : '卖出' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="position_ratio" label="建议仓位" width="90">
          <template #default="{ row }">{{ (row.position_ratio * 100).toFixed(1) }}%</template>
        </el-table-column>
        <el-table-column prop="score" label="评分" width="90">
          <template #default="{ row }">
            <el-progress :percentage="Math.min(row.score * 10, 100)" :stroke-width="8" :color="row.score > 5 ? '#67c23a' : row.score > 3 ? '#e6a23c' : '#f56c6c'" />
          </template>
        </el-table-column>
        <el-table-column prop="reason" label="信号原因" min-width="180" show-overflow-tooltip />
        <el-table-column prop="created_at" label="生成时间" width="170">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无信号数据">
            <el-button type="primary" size="small" @click="triggerCalculate">触发信号计算</el-button>
          </el-empty>
        </template>
      </el-table>

      <el-pagination
        v-model:current-page="pagination.page"
        v-model:page-size="pagination.size"
        :total="pagination.total"
        :page-sizes="[20, 50, 100]"
        layout="total, sizes, prev, pager, next"
        style="margin-top: 16px; justify-content: flex-end"
        @size-change="fetchSignals"
        @current-change="fetchSignals"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { signalApi } from '@/api/signal'
import { strategyApi } from '@/api/strategy'
import { useSignalStore } from '@/stores/signal'
import type { TradeSignal } from '@/api/signal'
import { ElMessage } from 'element-plus'
import dayjs from 'dayjs'

const signalStore = useSignalStore()
const loading = ref(false)
const calculating = ref(false)
const signalList = ref<TradeSignal[]>([])
const dateRange = ref<[string, string]>([
  dayjs().subtract(30, 'day').format('YYYY-MM-DD'),
  dayjs().format('YYYY-MM-DD'),
])

const filterForm = reactive({ strategyType: '', direction: '' })
const pagination = reactive({ page: 1, size: 20, total: 0 })

const strategyLabelMap: Record<string, string> = { AGGRESSIVE: '激进', MODERATE: '稳健', CONSERVATIVE: '保守' }
const strategyTagMap: Record<string, string> = { AGGRESSIVE: 'danger', MODERATE: 'warning', CONSERVATIVE: 'success' }

// Client-side filtering for direction (backend does not support direction filter)
const filteredSignals = computed(() => {
  let result = signalList.value
  if (filterForm.direction) {
    result = result.filter(s => s.direction === filterForm.direction)
  }
  pagination.total = result.length
  return result
})

async function fetchSignals() {
  loading.value = true
  try {
    signalList.value = await signalApi.getSignalHistory({
      strategyType: filterForm.strategyType || 'MODERATE',
      startDate: dateRange.value?.[0] || dayjs().subtract(30, 'day').format('YYYY-MM-DD'),
      endDate: dateRange.value?.[1] || dayjs().format('YYYY-MM-DD'),
    })
  } catch (e: any) {
    ElMessage.error(e?.message || '查询信号失败')
  } finally {
    loading.value = false
  }
}

async function triggerCalculate() {
  calculating.value = true
  try {
    const strategyType = filterForm.strategyType || 'AGGRESSIVE'
    const result = await strategyApi.calculateSignals(strategyType)
    ElMessage.success(`信号计算完成，生成 ${result?.length || 0} 条信号`)
    // Refresh signal list
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

onMounted(() => fetchSignals())
</script>

<style lang="scss" scoped>
.card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; .card-title { font-size: 16px; font-weight: 600; } }
.ws-status { display: flex; align-items: center; gap: 8px; font-size: 13px; }
.signal-buy { color: #f56c6c; font-weight: bold; }
.signal-sell { color: #67c23a; font-weight: bold; }
.etf-tag { cursor: pointer; display: inline-flex; align-items: center; gap: 4px; .etf-name { font-size: 12px; color: #606266; } &:hover .el-tag { border-color: #409eff; } }
.text-muted { color: #c0c4cc; }
</style>
