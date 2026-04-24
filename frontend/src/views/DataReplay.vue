<template>
  <div class="data-replay-page">
    <!-- 回放模式切换 + 时间范围 -->
    <div class="page-card">
      <div class="card-header">
        <span class="card-title">板块交易数据回放</span>
        <el-tag v-if="dataAvailability.has_data" size="small" type="success">
          数据: {{ dataAvailability.min_date }} ~ {{ dataAvailability.max_date }}
        </el-tag>
      </div>

      <!-- 回放模式 Tabs -->
      <el-tabs v-model="replayMode" @tab-change="onModeChange">
        <el-tab-pane label="按日期回放" name="byDate">
          <div class="replay-controls">
            <el-date-picker
              v-model="dateRange"
              type="daterange"
              value-format="YYYY-MM-DD"
              start-placeholder="开始日期"
              end-placeholder="结束日期"
              :disabled-date="disableDate"
              style="width: 260px"
              @change="onDateRangeChange"
            />
            <el-select v-model="selectedSector" placeholder="全部板块" clearable filterable style="width: 160px" @change="onSectorFilterChange">
              <el-option v-for="s in sectorList" :key="s.sector_code" :label="s.sector_name" :value="s.sector_code" />
            </el-select>

            <el-divider direction="vertical" />

            <el-button @click="stepBackward" :disabled="currentDateIndex <= 0 || loading" size="default">
              <el-icon><ArrowLeft /></el-icon> 前一日
            </el-button>
            <el-date-picker
              v-model="selectedDate"
              type="date"
              value-format="YYYY-MM-DD"
              placeholder="选择日期"
              :disabled-date="disableDate"
              @change="onDateChange"
              style="width: 150px"
            />
            <el-button @click="stepForward" :disabled="currentDateIndex >= availableDates.length - 1 || loading" size="default">
              后一日 <el-icon><ArrowRight /></el-icon>
            </el-button>

            <el-divider direction="vertical" />

            <el-button type="primary" @click="loadDayData" :loading="loading" size="default">加载</el-button>
            <el-button :type="autoPlaying ? 'danger' : 'success'" @click="toggleAutoPlay" size="default">
              {{ autoPlaying ? '停止' : '自动播放' }}
            </el-button>
            <span style="color: #909399; font-size: 13px; margin-left: 4px">间隔:</span>
            <el-input-number v-model="playSpeed" :min="0.5" :max="10" :step="0.5" size="default" style="width: 90px" />
            <span style="color: #909399; font-size: 13px">秒</span>

            <div v-if="currentDateIndex >= 0" class="date-progress">
              {{ currentDateIndex + 1 }} / {{ availableDates.length }}
            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane label="按板块回放" name="bySector">
          <div class="replay-controls">
            <el-select v-model="selectedSectorForHistory" placeholder="选择板块" filterable style="width: 200px" @change="onSectorHistoryChange">
              <el-option v-for="s in sectorList" :key="s.sector_code" :label="`${s.sector_name} (${s.sector_code})`" :value="s.sector_code" />
            </el-select>
            <el-date-picker
              v-model="sectorDateRange"
              type="daterange"
              value-format="YYYY-MM-DD"
              start-placeholder="开始日期"
              end-placeholder="结束日期"
              style="width: 260px"
              @change="loadSectorHistory"
            />
            <el-button type="primary" @click="loadSectorHistory" :loading="sectorLoading" size="default">加载历史</el-button>
          </div>
        </el-tab-pane>

        <el-tab-pane label="策略叠加回放" name="strategyOverlay">
          <div class="replay-controls">
            <el-date-picker
              v-model="overlayDateRange"
              type="daterange"
              value-format="YYYY-MM-DD"
              start-placeholder="开始日期"
              end-placeholder="结束日期"
              style="width: 260px"
            />
            <el-select v-model="overlayStrategyType" placeholder="选择策略" style="width: 150px">
              <el-option label="激进轮动" value="AGGRESSIVE" />
              <el-option label="稳健轮动" value="MODERATE" />
              <el-option label="保守轮动" value="CONSERVATIVE" />
            </el-select>
            <el-checkbox v-model="autoOptimize" :disabled="overlayLoading">自动寻优</el-checkbox>
            <el-input-number v-model="overlayCapital" :min="100000" :max="100000000" :step="100000" :controls="false" style="width: 140px" placeholder="初始资金" />
            <el-button type="primary" @click="loadStrategyOverlay" :loading="overlayLoading" size="default">
              {{ autoOptimize ? '自动寻优' : '运行策略回放' }}
            </el-button>
            <el-tag v-if="overlayLoading && autoOptimize" size="small" type="warning">
              寻优进度: {{ optimizationProgress }}/{{ totalCombinations }}
            </el-tag>
          </div>
        </el-tab-pane>
      </el-tabs>
    </div>

    <!-- ============ 按日期回放 ============ -->
    <div v-if="replayMode === 'byDate' && dayData" class="page-card" style="margin-top: 16px">
      <div class="card-header">
        <span class="card-title">{{ dayData.date }} 板块数据</span>
        <el-tag size="small">{{ dayData.count }} 个板块</el-tag>
      </div>

      <el-row :gutter="16" style="margin-bottom: 16px">
        <el-col :span="6">
          <div class="stat-box rise"><div class="stat-value">{{ riseCount }}</div><div class="stat-label">上涨板块</div></div>
        </el-col>
        <el-col :span="6">
          <div class="stat-box fall"><div class="stat-value">{{ fallCount }}</div><div class="stat-label">下跌板块</div></div>
        </el-col>
        <el-col :span="6">
          <div class="stat-box"><div class="stat-value">{{ avgChangeStr }}</div><div class="stat-label">平均涨跌幅</div></div>
        </el-col>
        <el-col :span="6">
          <div class="stat-box">
            <div class="stat-value" :style="{ color: maxRiseSector?.index_change_pct >= 0 ? '#f56c6c' : '#67c23a' }">
              {{ maxRiseSector?.sector_name || '-' }}
            </div>
            <div class="stat-label">领涨板块 {{ maxRiseSector ? (maxRiseSector.index_change_pct >= 0 ? '+' : '') + maxRiseSector.index_change_pct.toFixed(2) + '%' : '' }}</div>
          </div>
        </el-col>
      </el-row>

      <v-chart v-if="dayData?.date" :option="flowChartOption" :key="`flow-${dayData.date}`" style="height: 350px" autoresize />
      <div v-else style="height: 350px; display: flex; align-items: center; justify-content: center; color: #909399">
        加载中...
      </div>

      <el-table :data="dayData.sectors" stripe size="small" style="margin-top: 16px" :default-sort="{ prop: 'index_change_pct', order: 'descending' }">
        <el-table-column prop="sector_name" label="板块" width="120" fixed />
        <el-table-column prop="index_change_pct" label="涨跌幅" width="100" sortable>
          <template #default="{ row }">
            <span :class="row.index_change_pct >= 0 ? 'signal-buy' : 'signal-sell'">
              {{ row.index_change_pct >= 0 ? '+' : '' }}{{ row.index_change_pct.toFixed(2) }}%
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="index_close" label="收盘指数" width="100">
          <template #default="{ row }">{{ row.index_close?.toFixed(2) }}</template>
        </el-table-column>
        <el-table-column prop="main_net_inflow" label="主力净流入(亿)" width="130" sortable>
          <template #default="{ row }">
            <span :style="{ color: row.main_net_inflow >= 0 ? '#f56c6c' : '#67c23a' }">{{ (row.main_net_inflow / 1e8).toFixed(2) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="north_net_inflow" label="北向净流入(亿)" width="130" sortable>
          <template #default="{ row }">
            <span :style="{ color: row.north_net_inflow >= 0 ? '#f56c6c' : '#67c23a' }">{{ (row.north_net_inflow / 1e8).toFixed(2) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="turnover" label="成交额(亿)" width="110" sortable>
          <template #default="{ row }">{{ (row.turnover / 1e8).toFixed(2) }}</template>
        </el-table-column>
      </el-table>
    </div>

    <div v-else-if="replayMode === 'byDate' && !loading" class="page-card" style="margin-top: 16px">
      <el-empty description="请选择时间范围并点击加载" />
    </div>

    <!-- ============ 按板块回放 ============ -->
    <div v-if="replayMode === 'bySector' && sectorHistory.length > 0" class="page-card" style="margin-top: 16px">
      <div class="card-header">
        <span class="card-title">{{ currentSectorName }} 历史数据</span>
        <el-tag size="small">{{ sectorHistory.length }} 个交易日</el-tag>
      </div>

      <el-row :gutter="16" style="margin-bottom: 16px">
        <el-col :span="6">
          <div class="stat-box"><div class="stat-value">{{ sectorStats.totalReturn }}</div><div class="stat-label">区间涨跌幅</div></div>
        </el-col>
        <el-col :span="6">
          <div class="stat-box"><div class="stat-value">{{ sectorStats.maxRise }}</div><div class="stat-label">最大单日涨幅</div></div>
        </el-col>
        <el-col :span="6">
          <div class="stat-box"><div class="stat-value">{{ sectorStats.maxFall }}</div><div class="stat-label">最大单日跌幅</div></div>
        </el-col>
        <el-col :span="6">
          <div class="stat-box"><div class="stat-value">{{ sectorStats.avgChange }}</div><div class="stat-label">日均涨跌幅</div></div>
        </el-col>
      </el-row>

      <v-chart :option="sectorHistoryChartOption" style="height: 400px" autoresize />

      <el-table :data="sectorHistory" stripe size="small" style="margin-top: 16px">
        <el-table-column prop="date" label="日期" width="120" sortable />
        <el-table-column prop="index_change_pct" label="涨跌幅" width="100" sortable>
          <template #default="{ row }">
            <span :class="row.index_change_pct >= 0 ? 'signal-buy' : 'signal-sell'">{{ row.index_change_pct >= 0 ? '+' : '' }}{{ row.index_change_pct.toFixed(2) }}%</span>
          </template>
        </el-table-column>
        <el-table-column prop="index_close" label="收盘指数" width="100">
          <template #default="{ row }">{{ row.index_close?.toFixed(2) }}</template>
        </el-table-column>
        <el-table-column prop="main_net_inflow" label="主力净流入(亿)" width="130" sortable>
          <template #default="{ row }">
            <span :style="{ color: row.main_net_inflow >= 0 ? '#f56c6c' : '#67c23a' }">{{ (row.main_net_inflow / 1e8).toFixed(2) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="north_net_inflow" label="北向净流入(亿)" width="130" sortable>
          <template #default="{ row }">
            <span :style="{ color: row.north_net_inflow >= 0 ? '#f56c6c' : '#67c23a' }">{{ (row.north_net_inflow / 1e8).toFixed(2) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="turnover" label="成交额(亿)" width="110" sortable>
          <template #default="{ row }">{{ (row.turnover / 1e8).toFixed(2) }}</template>
        </el-table-column>
      </el-table>
    </div>

    <div v-else-if="replayMode === 'bySector' && !sectorLoading" class="page-card" style="margin-top: 16px">
      <el-empty description="请选择板块并点击加载历史" />
    </div>

    <!-- ============ 策略叠加回放 ============ -->
    <div v-if="replayMode === 'strategyOverlay' && overlayData" class="page-card" style="margin-top: 16px">
      <!-- 策略参数显示 -->
      <div v-if="overlayData.summary.params" class="params-display">
        <el-tag size="small" type="info">参数: top_n={{ overlayData.summary.params.top_n }}, 持仓={{ overlayData.summary.params.max_position * 100 }}%, 持有={{ overlayData.summary.params.hold_days }}日, 止损={{ overlayData.summary.params.stop_loss * 100 }}%, 评分阈值={{ overlayData.summary.params.min_score_threshold }}, 评分差={{ overlayData.summary.params.score_gap_threshold }}, 冷却={{ overlayData.summary.params.cooldown_days }}日</el-tag>
      </div>

      <!-- 策略收益概览 -->
      <div class="card-header">
        <span class="card-title">{{ overlayStrategyLabel }} 回放结果</span>
        <el-tag size="small">{{ overlayData.summary.trading_days }} 个交易日</el-tag>
      </div>

      <el-row :gutter="16" style="margin-bottom: 16px">
        <el-col :span="4">
          <div class="stat-box" :class="{ rise: overlayData.summary.total_return >= 0, fall: overlayData.summary.total_return < 0 }">
            <div class="stat-value">{{ (overlayData.summary.total_return >= 0 ? '+' : '') + (overlayData.summary.total_return * 100).toFixed(2) }}%</div>
            <div class="stat-label">总收益</div>
          </div>
        </el-col>
        <el-col :span="4">
          <div class="stat-box" :class="{ rise: overlayData.summary.annual_return >= 0, fall: overlayData.summary.annual_return < 0 }">
            <div class="stat-value">{{ (overlayData.summary.annual_return >= 0 ? '+' : '') + (overlayData.summary.annual_return * 100).toFixed(2) }}%</div>
            <div class="stat-label">年化收益</div>
          </div>
        </el-col>
        <el-col :span="4">
          <div class="stat-box fall">
            <div class="stat-value">{{ (overlayData.summary.max_drawdown * 100).toFixed(2) }}%</div>
            <div class="stat-label">最大回撤</div>
          </div>
        </el-col>
        <el-col :span="4">
          <div class="stat-box rise">
            <div class="stat-value">{{ overlayData.summary.buy_count }}</div>
            <div class="stat-label">买入信号</div>
          </div>
        </el-col>
        <el-col :span="4">
          <div class="stat-box fall">
            <div class="stat-value">{{ overlayData.summary.sell_count }}</div>
            <div class="stat-label">卖出信号</div>
          </div>
        </el-col>
        <el-col :span="4">
          <div class="stat-box">
            <div class="stat-value">{{ formatMoney(overlayData.summary.final_capital) }}</div>
            <div class="stat-label">最终资产(万)</div>
          </div>
        </el-col>
      </el-row>

      <!-- 策略净值曲线 + 买卖点标记 -->
      <v-chart :option="overlayChartOption" style="height: 420px" autoresize />

      <!-- 每日信号明细 -->
      <div style="margin-top: 16px">
        <div class="card-header" style="margin-bottom: 8px">
          <span style="font-weight: 600">调仓日信号明细</span>
          <el-tag size="small">{{ overlaySignalDays.length }} 个调仓日</el-tag>
        </div>
        <el-table :data="overlaySignalDays" stripe size="small" max-height="400">
          <el-table-column prop="date" label="日期" width="120" />
          <el-table-column label="买入" min-width="200">
            <template #default="{ row }">
              <el-tag v-for="sig in row.buySignals" :key="sig.sector_code" size="small" type="danger" style="margin: 2px">
                {{ sig.sector_name }}
              </el-tag>
              <span v-if="!row.buySignals.length" style="color: #909399">无</span>
            </template>
          </el-table-column>
          <el-table-column label="卖出" min-width="200">
            <template #default="{ row }">
              <el-tag v-for="sig in row.sellSignals" :key="sig.sector_code" size="small" type="success" style="margin: 2px">
                {{ sig.sector_name }}
              </el-tag>
              <span v-if="!row.sellSignals.length" style="color: #909399">无</span>
            </template>
          </el-table-column>
          <el-table-column prop="strategy_return" label="策略日收益" width="120" sortable>
            <template #default="{ row }">
              <span :style="{ color: row.strategy_return >= 0 ? '#f56c6c' : '#67c23a' }">
                {{ row.strategy_return >= 0 ? '+' : '' }}{{ row.strategy_return.toFixed(4) }}%
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="benchmark_return" label="基准日收益" width="120">
            <template #default="{ row }">
              <span style="color: #909399">{{ row.benchmark_return >= 0 ? '+' : '' }}{{ row.benchmark_return.toFixed(4) }}%</span>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <div v-else-if="replayMode === 'strategyOverlay' && !overlayLoading" class="page-card" style="margin-top: 16px">
      <el-empty description="请选择时间范围和策略，点击运行策略回放" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onUnmounted } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { BarChart, LineChart, ScatterChart, CandlestickChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, MarkLineComponent, MarkPointComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { ElMessage } from 'element-plus'
import { settingsApi } from '@/api/settings'
import { strategyApi } from '@/api/strategy'
import dayjs from 'dayjs'

use([BarChart, LineChart, ScatterChart, CandlestickChart, GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, MarkLineComponent, MarkPointComponent, CanvasRenderer])

// ============ 通用状态 ============
const loading = ref(false)
const sectorLoading = ref(false)
const overlayLoading = ref(false)
const replayMode = ref<'byDate' | 'bySector' | 'strategyOverlay'>('byDate')
const sectorList = ref<{ sector_code: string; sector_name: string }[]>([])
const dataAvailability = reactive({ has_data: false, min_date: '', max_date: '' })

// ============ 按日期回放状态 ============
const dateRange = ref<string[]>([])
const selectedDate = ref('')
const selectedSector = ref('')
const availableDates = ref<string[]>([])
const currentDateIndex = ref(-1)
const dayData = ref<{ date: string; sectors: any[]; count: number } | null>(null)
const autoPlaying = ref(false)
const playSpeed = ref(1.5)
let autoPlayTimer: ReturnType<typeof setTimeout> | null = null

// ============ 按板块回放状态 ============
const selectedSectorForHistory = ref('')
const sectorDateRange = ref<string[]>([])
const sectorHistory = ref<any[]>([])

// ============ 策略叠加回放状态 ============
const overlayDateRange = ref<string[]>([])
const overlayStrategyType = ref('MODERATE')
const overlayCapital = ref(1000000)
const autoOptimize = ref(false)
const optimizationProgress = ref(0)
const totalCombinations = ref(0)
const bestParams = ref<any>(null)
const overlayData = ref<{
  daily_signals: any[]
  nav_curve: any[]
  summary: any
} | null>(null)

// ============ 计算属性 ============
const riseCount = computed(() => dayData.value?.sectors.filter(s => s.index_change_pct >= 0).length ?? 0)
const fallCount = computed(() => dayData.value?.sectors.filter(s => s.index_change_pct < 0).length ?? 0)
const avgChangeStr = computed(() => {
  if (!dayData.value?.sectors.length) return '-'
  const avg = dayData.value.sectors.reduce((sum, s) => sum + s.index_change_pct, 0) / dayData.value.sectors.length
  return (avg >= 0 ? '+' : '') + avg.toFixed(2) + '%'
})
const maxRiseSector = computed(() => {
  if (!dayData.value?.sectors.length) return null
  return [...dayData.value.sectors].sort((a, b) => b.index_change_pct - a.index_change_pct)[0]
})

const currentSectorName = computed(() => {
  const s = sectorList.value.find(x => x.sector_code === selectedSectorForHistory.value)
  return s?.sector_name || selectedSectorForHistory.value
})

const sectorStats = computed(() => {
  if (!sectorHistory.value.length) return { totalReturn: '-', maxRise: '-', maxFall: '-', avgChange: '-' }
  const changes = sectorHistory.value.map(s => s.index_change_pct)
  const total = changes.reduce((a, b) => a + b, 0)
  return {
    totalReturn: (total >= 0 ? '+' : '') + total.toFixed(2) + '%',
    maxRise: '+' + Math.max(...changes).toFixed(2) + '%',
    maxFall: Math.min(...changes).toFixed(2) + '%',
    avgChange: (total / changes.length >= 0 ? '+' : '') + (total / changes.length).toFixed(3) + '%',
  }
})

const overlayStrategyLabel = computed(() => {
  const map: Record<string, string> = { AGGRESSIVE: '激进轮动', MODERATE: '稳健轮动', CONSERVATIVE: '保守轮动' }
  return map[overlayStrategyType.value] || overlayStrategyType.value
})

// 策略叠加 - 有信号的调仓日
const overlaySignalDays = computed(() => {
  if (!overlayData.value?.daily_signals) return []
  return overlayData.value.daily_signals
    .filter(d => d.signals && d.signals.length > 0)
    .map(d => ({
      date: d.date,
      buySignals: d.signals.filter((s: any) => s.direction === 'BUY'),
      sellSignals: d.signals.filter((s: any) => s.direction === 'SELL'),
      strategy_return: d.strategy_return,
      benchmark_return: d.benchmark_return,
    }))
})

function formatMoney(val: number): string {
  return (val / 10000).toFixed(1)
}

// ============ 日期禁用 ============
function disableDate(date: Date): boolean {
  // 1. 排除周末（周六、周日）
  const day = date.getDay()
  if (day === 0 || day === 6) return true
  
  // 2. 如果有可用日期列表，只允许选择有数据的交易日
  if (availableDates.value.length === 0) return false
  return !availableDates.value.includes(dayjs(date).format('YYYY-MM-DD'))
}

// ============ 按日期回放逻辑 ============
async function loadAvailableDates() {
  try {
    const start = dateRange.value?.[0] || dataAvailability.min_date || undefined
    const end = dateRange.value?.[1] || dataAvailability.max_date || undefined
    const data = await settingsApi.getReplayDates(start, end)
    availableDates.value = data || []
    if (data.length > 0 && !selectedDate.value) {
      selectedDate.value = data[data.length - 1]
      currentDateIndex.value = data.length - 1
    }
  } catch { ElMessage.error('加载日期列表失败') }
}

async function loadDayData() {
  if (!selectedDate.value) { ElMessage.warning('请先选择日期'); return }
  loading.value = true
  try {
    // 设置一个空key让图表强制重建
    const loadingKey = 'loading-' + Date.now()
    dayData.value = { date: loadingKey, sectors: [], count: 0 }
    await new Promise(r => setTimeout(r, 100))
    const newData = await settingsApi.getReplayDayData(selectedDate.value, selectedSector.value || undefined)
    dayData.value = newData
    currentDateIndex.value = availableDates.value.indexOf(selectedDate.value)
  } catch { ElMessage.error('加载数据失败') }
  finally { loading.value = false }
}

function onDateChange(val: string) { if (val) { selectedDate.value = val; loadDayData() } }
function onDateRangeChange() { loadAvailableDates() }
function onSectorFilterChange() { if (selectedDate.value) loadDayData() }

function stepBackward() {
  if (currentDateIndex.value > 0) { currentDateIndex.value--; selectedDate.value = availableDates.value[currentDateIndex.value]; loadDayData() }
}
function stepForward() {
  if (currentDateIndex.value < availableDates.value.length - 1) { currentDateIndex.value++; selectedDate.value = availableDates.value[currentDateIndex.value]; loadDayData() }
}

function toggleAutoPlay() {
  if (autoPlaying.value) { stopAutoPlay() } else {
    if (!selectedDate.value) { ElMessage.warning('请先加载某日数据'); return }
    autoPlaying.value = true; autoPlayStep()
  }
}
function autoPlayStep() {
  if (!autoPlaying.value) return
  if (currentDateIndex.value >= availableDates.value.length - 1) { stopAutoPlay(); ElMessage.info('回放已结束'); return }
  stepForward()
  autoPlayTimer = setTimeout(autoPlayStep, playSpeed.value * 1000)
}
function stopAutoPlay() { autoPlaying.value = false; if (autoPlayTimer) { clearTimeout(autoPlayTimer); autoPlayTimer = null } }

// ============ 按板块回放逻辑 ============
async function loadSectorHistory() {
  if (!selectedSectorForHistory.value) { ElMessage.warning('请先选择板块'); return }
  sectorLoading.value = true
  try {
    const start = sectorDateRange.value?.[0] || dataAvailability.min_date || undefined
    const end = sectorDateRange.value?.[1] || dataAvailability.max_date || undefined
    const data = await settingsApi.getReplaySectorHistory(selectedSectorForHistory.value, start, end)
    // 过滤掉周末（非交易日），后端数据本身应该只有交易日，但前端做双重保障
    sectorHistory.value = data.filter((item: any) => {
      const d = new Date(item.date)
      return d.getDay() !== 0 && d.getDay() !== 6
    })
    if (!sectorHistory.value.length) ElMessage.info('该板块在选定时间段内无数据')
  } catch { ElMessage.error('加载板块历史数据失败') }
  finally { sectorLoading.value = false }
}
function onSectorHistoryChange() { sectorHistory.value = [] }

// ============ 策略叠加回放逻辑 ============
async function loadStrategyOverlay() {
  if (!overlayDateRange.value?.[0] || !overlayDateRange.value?.[1]) {
    ElMessage.warning('请选择时间范围'); return
  }
  overlayLoading.value = true
  
  if (autoOptimize.value) {
    await runAutoOptimization()
    return
  }
  
  try {
    overlayData.value = await settingsApi.runStrategyOverlay({
      start_date: overlayDateRange.value[0],
      end_date: overlayDateRange.value[1],
      strategy_type: overlayStrategyType.value,
      initial_capital: overlayCapital.value,
    })
    ElMessage.success('策略回放完成')
  } catch { ElMessage.error('策略回放失败') }
  finally { overlayLoading.value = false }
}

async function runAutoOptimization() {
  totalCombinations.value = 0
  optimizationProgress.value = 0
  overlayLoading.value = true
  
  try {
    const result = await settingsApi.runStrategyOptimize({
      start_date: overlayDateRange.value[0],
      end_date: overlayDateRange.value[1],
      strategy_type: overlayStrategyType.value,
      initial_capital: overlayCapital.value,
    })
    
    if (result.best_params && result.best_result) {
      // 转换结果格式以匹配现有显示
      overlayData.value = {
        daily_signals: result.best_result.daily_signals || [],
        nav_curve: result.best_result.nav_curve || [],
        summary: result.best_result,
      }
      bestParams.value = result.best_params
      
      ElMessage.success(`寻优完成! 最优参数: top_n=${bestParams.value.top_n}, 持有=${bestParams.value.hold_days}日, 止损=${(bestParams.value.stop_loss*100).toFixed(0)}%, 总收益=${(result.best_result.total_return*100).toFixed(2)}%`)
    } else {
      ElMessage.error('寻优失败')
    }
  } catch { ElMessage.error('策略寻优失败') }
  finally { overlayLoading.value = false }
}

function onModeChange() { stopAutoPlay() }

// ============ 资金流向柱状图（按日期）- 双面板布局 ============
const flowChartOption = computed(() => {
  if (!dayData.value?.sectors?.length) return {}
  const sorted = [...dayData.value.sectors].sort((a, b) => b.index_change_pct - a.index_change_pct)
  const sectorNames = sorted.map(s => s.sector_name)
  const changes = sorted.map(s => s.index_change_pct)
  const mainFlow = sorted.map(s => +(s.main_net_inflow / 1e8).toFixed(2))
  const northFlow = sorted.map(s => +(s.north_net_inflow / 1e8).toFixed(2))
  return {
    notMerge: true,
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params: any) => {
        const idx = params[0]?.dataIndex
        if (idx === undefined) return ''
        const s = sorted[idx]
        let html = `<b>${s.sector_name}</b><br/>`
        html += `涨跌幅: ${s.index_change_pct >= 0 ? '+' : ''}${s.index_change_pct.toFixed(2)}%<br/>`
        html += `主力净流入: ${(s.main_net_inflow / 1e8).toFixed(2)}亿<br/>`
        html += `北向净流入: ${(s.north_net_inflow / 1e8).toFixed(2)}亿`
        return html
      }
    },
    legend: { data: ['涨跌幅(%)', '主力净流入(亿)', '北向净流入(亿)'], selectedMode: 'multiple' },
    grid: [
      { left: 70, right: 50, top: 35, height: '42%' },
      { left: 70, right: 50, top: '58%', height: '32%' },
    ],
    dataZoom: [
      { type: 'inside', xAxisIndex: [0, 1], start: 0, end: 100 },
      { type: 'slider', xAxisIndex: [0, 1], start: 0, end: 100, bottom: 5, height: 20 },
    ],
    xAxis: [
      { type: 'category', data: sectorNames, gridIndex: 0, axisLabel: { show: false }, position: 'top' },
      { type: 'category', data: sectorNames, gridIndex: 1, axisLabel: { rotate: 45, fontSize: 10 }, position: 'bottom' },
    ],
    yAxis: [
      { type: 'value', name: '涨跌幅(%)', position: 'left', gridIndex: 0, axisLine: { show: true, lineStyle: { color: '#409eff' } }, axisLabel: { formatter: '{value}%' }, splitLine: { lineStyle: { color: '#f5f5f5' } } },
      { type: 'value', name: '主力(亿)', position: 'left', gridIndex: 1, offset: 0, axisLine: { show: true, lineStyle: { color: '#f56c6c' } }, axisLabel: { formatter: '{value}', margin: 8 }, splitLine: { lineStyle: { color: '#f5f5f5' } } },
      { type: 'value', name: '北向(亿)', position: 'right', gridIndex: 1, axisLine: { show: true, lineStyle: { color: '#e6a23c' } }, axisLabel: { formatter: '{value}', margin: 8 }, splitLine: { show: false } },
    ],
    series: [
      { name: '涨跌幅(%)', type: 'bar', xAxisIndex: 0, yAxisIndex: 0, data: changes, itemStyle: { color: (p: any) => p.data >= 0 ? '#f56c6c' : '#67c23a' }, barWidth: 10 },
      { name: '主力净流入(亿)', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: mainFlow, itemStyle: { color: '#f56c6c' }, barWidth: 6 },
      { name: '北向净流入(亿)', type: 'bar', xAxisIndex: 1, yAxisIndex: 2, data: northFlow, itemStyle: { color: '#e6a23c' }, barWidth: 6 },
    ],
  }
})

// ============ 板块K线图 + 资金流（按板块）- 双面板布局 ============
const sectorHistoryChartOption = computed(() => {
  if (!sectorHistory.value.length) return {}
  const dates = sectorHistory.value.map(s => s.date)
  const changes = sectorHistory.value.map(s => s.index_change_pct)

  // 构建K线数据 [open, close, low, high]
  const candleData: number[][] = []
  let prevClose = sectorHistory.value[0]?.index_close ?? 3000
  const hasRealOHLC = sectorHistory.value.some(s => s.open != null && s.high != null && s.low != null)

  for (const s of sectorHistory.value) {
    if (hasRealOHLC && s.open != null && s.high != null && s.low != null && s.close != null) {
      candleData.push([+s.open.toFixed(2), +s.close.toFixed(2), +s.low.toFixed(2), +s.high.toFixed(2)])
    } else {
      const close = s.index_close || (prevClose * (1 + (s.index_change_pct || 0) / 100))
      const pct = (s.index_change_pct || 0) / 100
      const open = prevClose
      const range = Math.abs(pct) * close * 0.6 + close * 0.003
      const high = Math.max(open, close) + range * 0.3
      const low = Math.min(open, close) - range * 0.3
      candleData.push([+open.toFixed(2), +close.toFixed(2), +low.toFixed(2), +high.toFixed(2)])
    }
    prevClose = s.close || s.index_close || prevClose
  }

  // MA5 / MA10
  const closes = candleData.map(d => d[1]) // close
  const ma5: (number | null)[] = [], ma10: (number | null)[] = []
  for (let i = 0; i < closes.length; i++) {
    ma5.push(i < 4 ? null : +(closes.slice(i - 4, i + 1).reduce((a, b) => a + b, 0) / 5).toFixed(2))
    ma10.push(i < 9 ? null : +(closes.slice(i - 9, i + 1).reduce((a, b) => a + b, 0) / 10).toFixed(2))
  }

  // 资金流数据
  const mainFlow = sectorHistory.value.map(s => +(s.main_net_inflow / 1e8).toFixed(2))
  const northFlow = sectorHistory.value.map(s => +(s.north_net_inflow / 1e8).toFixed(2))

  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      formatter: (params: any) => {
        const idx = params[0]?.dataIndex
        if (idx === undefined) return ''
        const s = sectorHistory.value[idx]
        const candle = params.find((p: any) => p.seriesName === 'K线')
        let html = `<b>${s.date}</b><br/>`
        if (candle) {
          const d = candle.data
          html += `开: ${d[1]} 收: ${d[2]} 低: ${d[3]} 高: ${d[4]}<br/>`
        }
        html += `涨跌幅: ${s.index_change_pct?.toFixed(2)}%<br/>`
        html += `主力净流入: ${(s.main_net_inflow / 1e8).toFixed(2)}亿<br/>`
        html += `北向净流入: ${(s.north_net_inflow / 1e8).toFixed(2)}亿`
        return html
      },
    },
    legend: { data: ['K线', 'MA5', 'MA10', '主力净流入(亿)', '北向净流入(亿)'], top: 0 },
    // 上下双面板：上方K线占70%，下方资金流占30%
    grid: [
      { left: 70, right: 20, top: 30, height: '52%' },  // K线主图
      { left: 70, right: 20, top: '72%', height: '20%' }, // 资金流副图
    ],
    xAxis: [
      { type: 'category', data: dates, axisLabel: { show: false }, axisTick: { show: false } },  // 主图X轴隐藏标签
      { type: 'category', data: dates, gridIndex: 1, axisLabel: { rotate: 30, fontSize: 10 } },  // 副图X轴显示标签
    ],
    yAxis: [
      { type: 'value', name: '指数', scale: true, splitLine: { lineStyle: { color: '#eee' } } },  // 主图Y轴
      { type: 'value', name: '亿元', gridIndex: 1, splitLine: { lineStyle: { color: '#f5f5f5' } } },  // 副图Y轴
    ],
    dataZoom: [
      { type: 'inside', xAxisIndex: [0, 1], start: Math.max(0, (1 - 60 / dates.length) * 100) },
      { type: 'slider', xAxisIndex: [0, 1], bottom: 5, height: 18 },
    ],
    series: [
      // === 主图：K线 + 均线 ===
      {
        name: 'K线', type: 'candlestick', data: candleData,
        itemStyle: { color: '#ef232a', color0: '#14b143', borderColor: '#ef232a', borderColor0: '#14b143' },
      },
      {
        name: 'MA5', type: 'line', data: ma5, symbol: 'none',
        lineStyle: { width: 1, color: '#e6a23c' }, itemStyle: { color: '#e6a23c' },
      },
      {
        name: 'MA10', type: 'line', data: ma10, symbol: 'none',
        lineStyle: { width: 1, color: '#909399', type: 'dashed' }, itemStyle: { color: '#909399' },
      },
      // === 副图：资金流柱状 ===
      {
        name: '主力净流入(亿)', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: mainFlow,
        itemStyle: { color: (p: any) => p.data >= 0 ? 'rgba(245,108,108,0.7)' : 'rgba(103,194,58,0.7)' },
        barMaxWidth: 12,
      },
      {
        name: '北向净流入(亿)', type: 'line', xAxisIndex: 1, yAxisIndex: 1, data: northFlow,
        smooth: true, symbol: 'none',
        lineStyle: { width: 1.5, color: '#409eff' }, itemStyle: { color: '#409eff' },
      },
    ],
  }
})

// ============ 策略叠加净值曲线 + 买卖点标记 ============
const overlayChartOption = computed(() => {
  if (!overlayData.value?.nav_curve?.length) return {}
  const curve = overlayData.value.nav_curve
  const signals = overlayData.value.daily_signals

  // 构建买卖点标记数据
  const buyPoints: any[] = []
  const sellPoints: any[] = []
  const dateIndexMap: Record<string, number> = {}
  curve.forEach((p: any, i: number) => { dateIndexMap[p.date] = i })

  for (const day of signals) {
    if (!day.signals || day.signals.length === 0) continue
    const idx = dateIndexMap[day.date]
    if (idx === undefined) continue
    const navVal = curve[idx].nav

    for (const sig of day.signals) {
      const point = {
        coord: [idx, navVal],
        value: `${sig.sector_name || sig.sector_code}`,
        itemStyle: { color: sig.direction === 'BUY' ? '#f56c6c' : '#67c23a' },
      }
      if (sig.direction === 'BUY') buyPoints.push(point)
      else sellPoints.push(point)
    }
  }

  const strategyColor = overlayStrategyType.value === 'AGGRESSIVE' ? '#f56c6c' : overlayStrategyType.value === 'CONSERVATIVE' ? '#67c23a' : '#409eff'

  return {
    tooltip: {
      trigger: 'axis',
      formatter: (params: any) => {
        const idx = params[0]?.dataIndex
        if (idx === undefined) return ''
        const point = curve[idx]
        const daySig = signals.find((s: any) => s.date === point.date)
        let html = `<b>${point.date}</b><br/>`
        html += `策略净值: ${(point.nav / 10000).toFixed(2)}万<br/>`
        html += `基准净值: ${(point.benchmark / 10000).toFixed(2)}万<br/>`
        if (point.stop_loss) html += `<span style="color:#e6a23c">⚠ 止损中</span><br/>`
        if (daySig?.signals?.length) {
          const buySigs = daySig.signals.filter((s: any) => s.direction === 'BUY')
          const sellSigs = daySig.signals.filter((s: any) => s.direction === 'SELL')
          if (buySigs.length) {
            html += `<span style="color:#f56c6c; font-weight:bold">买入: ${buySigs.map((s: any) => s.sector_name).join(', ')}</span><br/>`
          }
          if (sellSigs.length) {
            html += `<span style="color:#67c23a; font-weight:bold">卖出: ${sellSigs.map((s: any) => s.sector_name).join(', ')}</span><br/>`
          }
        }
        return html
      },
    },
    legend: { data: ['策略净值', '基准净值', '买入点', '卖出点'] },
    grid: { left: 80, right: 30, bottom: 60, top: 40 },
    dataZoom: [{ type: 'inside' }, { type: 'slider' }],
    xAxis: { type: 'category', data: curve.map((p: any) => p.date), axisLabel: { rotate: 30, fontSize: 10 } },
    yAxis: { type: 'value', name: '净值', scale: true, axisLabel: { formatter: (v: number) => (v / 10000).toFixed(0) + '万' } },
    series: [
      {
        name: '策略净值', type: 'line', data: curve.map((p: any) => p.nav),
        smooth: true, lineStyle: { width: 2.5, color: strategyColor },
        itemStyle: { color: strategyColor }, symbol: 'none',
      },
      {
        name: '基准净值', type: 'line', data: curve.map((p: any) => p.benchmark),
        smooth: true, lineStyle: { width: 1.5, color: '#909399', type: 'dashed' },
        itemStyle: { color: '#909399' }, symbol: 'none',
      },
      {
        name: '买入点', type: 'scatter', data: buyPoints.map((p: any) => [p.coord[0], p.coord[1]]),
        symbol: 'triangle', symbolSize: 12, itemStyle: { color: '#f56c6c' }, z: 10,
        tooltip: { show: false },
      },
      {
        name: '卖出点', type: 'scatter', data: sellPoints.map((p: any) => [p.coord[0], p.coord[1]]),
        symbol: 'path://M-6,-6L6,6M6,-6L-6,6', symbolSize: 12, itemStyle: { color: '#67c23a' }, z: 10,
        tooltip: { show: false },
      },
    ],
  }
})

// ============ 初始化 ============
async function init() {
  try {
    const data = await strategyApi.getDataAvailability()
    dataAvailability.has_data = data.has_data
    dataAvailability.min_date = data.min_date || ''
    dataAvailability.max_date = data.max_date || ''
    if (data.min_date && data.max_date) {
      dateRange.value = [data.min_date, data.max_date]
      sectorDateRange.value = [data.min_date, data.max_date]
      overlayDateRange.value = [data.min_date, data.max_date]
    }
  } catch { /* ignore */ }
  try { sectorList.value = await settingsApi.getReplaySectors() } catch { /* ignore */ }
  await loadAvailableDates()
}

onUnmounted(() => { stopAutoPlay() })
init()
</script>

<style lang="scss" scoped>
.replay-controls {
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap; padding: 8px 0;
}
.date-progress { font-size: 14px; color: #409eff; font-weight: 600; margin-left: 8px; }
.stat-box {
  text-align: center; padding: 16px; background: #f5f7fa; border-radius: 8px;
  .stat-value { font-size: 20px; font-weight: 600; color: #303133; }
  .stat-label { font-size: 12px; color: #909399; margin-top: 4px; }
  &.rise .stat-value { color: #f56c6c; }
  &.fall .stat-value { color: #67c23a; }
}
.card-header {
  display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;
  .card-title { font-size: 16px; font-weight: 600; }
}
.params-display {
  margin-bottom: 12px;
  padding: 8px;
  background: #f5f7fa;
  border-radius: 4px;
}
::deep(.el-tabs__nav-wrap::after) { display: none; }
</style>
