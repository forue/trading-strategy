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
              class="control-date-range"
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
            <el-select v-model="selectedSectorForHistory" placeholder="选择板块" filterable class="control-select-wide" @change="onSectorHistoryChange">
              <el-option v-for="s in sectorList" :key="s.sector_code" :label="`${s.sector_name} (${s.sector_code})`" :value="s.sector_code" />
            </el-select>
            <el-date-picker
              v-model="sectorDateRange"
              type="daterange"
              value-format="YYYY-MM-DD"
              start-placeholder="开始日期"
              end-placeholder="结束日期"
              class="control-date-range"
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
              class="control-date-range"
            />
            <el-select v-model="overlayStrategyType" placeholder="选择策略" class="control-select-small">
              <el-option label="激进轮动" value="AGGRESSIVE" />
              <el-option label="稳健轮动" value="MODERATE" />
              <el-option label="保守轮动" value="CONSERVATIVE" />
            </el-select>
            <el-checkbox v-model="autoOptimize" :disabled="overlayLoading">自动寻优</el-checkbox>
            <el-input-number v-model="overlayCapital" :min="100000" :max="100000000" :step="100000" :controls="false" class="control-input-num" placeholder="初始资金" />
            <el-input-number v-if="autoOptimize" v-model="nTrials" :min="20" :max="200" :step="10" class="control-input-num-small" placeholder="试验次数" />
            <el-button type="primary" @click="loadStrategyOverlay" :loading="overlayLoading" size="default">
              {{ autoOptimize ? '自动寻优' : '运行策略回放' }}
            </el-button>
            <el-tag v-if="overlayLoading && autoOptimize" size="small" type="warning">
              寻优进度: {{ optimizationProgress }}/{{ totalCombinations }} ({{ totalCombinations > 0 ? Math.round(optimizationProgress / totalCombinations * 100) : 0 }}%)
            </el-tag>
          </div>
        </el-tab-pane>
      </el-tabs>
    </div>

    <!-- ============ 按日期回放 ============ -->
    <div v-if="replayMode === 'byDate' && dayData" class="page-card page-section">
      <div class="card-header">
        <span class="card-title">{{ dayData.date }} 板块数据</span>
        <el-tag size="small">{{ dayData.count }} 个板块</el-tag>
      </div>

      <el-row :gutter="16" style="margin-bottom: 16px">
        <el-col :xs="12" :sm="6">
          <div class="stat-box rise"><div class="stat-value">{{ riseCount }}</div><div class="stat-label">上涨板块</div></div>
        </el-col>
        <el-col :xs="12" :sm="6">
          <div class="stat-box fall"><div class="stat-value">{{ fallCount }}</div><div class="stat-label">下跌板块</div></div>
        </el-col>
        <el-col :xs="12" :sm="6">
          <div class="stat-box"><div class="stat-value">{{ avgChangeStr }}</div><div class="stat-label">平均涨跌幅</div></div>
        </el-col>
        <el-col :xs="12" :sm="6">
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

      <div class="responsive-table"><el-table :data="dayData.sectors" stripe size="small" style="margin-top: 16px" :default-sort="{ prop: 'index_change_pct', order: 'descending' }">
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
      </el-table></div>
    </div>

    <div v-else-if="replayMode === 'byDate' && !loading" class="page-card page-section">
      <el-empty description="请选择时间范围并点击加载" />
    </div>

    <!-- ============ 按板块回放 ============ -->
    <div v-if="replayMode === 'bySector' && sectorHistory.length > 0" class="page-card page-section">
      <div class="card-header">
        <span class="card-title">{{ currentSectorName }} 历史数据</span>
        <el-tag size="small">{{ sectorHistory.length }} 个交易日</el-tag>
      </div>

      <el-row :gutter="16" style="margin-bottom: 16px">
        <el-col :xs="12" :sm="6">
          <div class="stat-box"><div class="stat-value">{{ sectorStats.totalReturn }}</div><div class="stat-label">区间涨跌幅</div></div>
        </el-col>
        <el-col :xs="12" :sm="6">
          <div class="stat-box"><div class="stat-value">{{ sectorStats.maxRise }}</div><div class="stat-label">最大单日涨幅</div></div>
        </el-col>
        <el-col :xs="12" :sm="6">
          <div class="stat-box"><div class="stat-value">{{ sectorStats.maxFall }}</div><div class="stat-label">最大单日跌幅</div></div>
        </el-col>
        <el-col :xs="12" :sm="6">
          <div class="stat-box"><div class="stat-value">{{ sectorStats.avgChange }}</div><div class="stat-label">日均涨跌幅</div></div>
        </el-col>
      </el-row>

      <v-chart :option="sectorHistoryChartOption" style="height: 400px" autoresize />

      <div class="responsive-table"><el-table :data="sectorHistory" stripe size="small" style="margin-top: 16px">
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
      </el-table></div>
    </div>

    <div v-else-if="replayMode === 'bySector' && !sectorLoading" class="page-card page-section">
      <el-empty description="请选择板块并点击加载历史" />
    </div>

    <!-- ============ 策略叠加回放 ============ -->
    <div v-if="replayMode === 'strategyOverlay' && overlayData" class="page-card page-section">
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
        <el-col :xs="12" :sm="6" :md="4">
          <div class="stat-box" :class="{ rise: overlayData.summary.total_return >= 0, fall: overlayData.summary.total_return < 0 }">
            <div class="stat-value">{{ (overlayData.summary.total_return >= 0 ? '+' : '') + (overlayData.summary.total_return * 100).toFixed(2) }}%</div>
            <div class="stat-label">总收益</div>
          </div>
        </el-col>
        <el-col :xs="12" :sm="6" :md="4">
          <div class="stat-box" :class="{ rise: overlayData.summary.annual_return >= 0, fall: overlayData.summary.annual_return < 0 }">
            <div class="stat-value">{{ (overlayData.summary.annual_return >= 0 ? '+' : '') + (overlayData.summary.annual_return * 100).toFixed(2) }}%</div>
            <div class="stat-label">年化收益</div>
          </div>
        </el-col>
        <el-col :xs="12" :sm="6" :md="4">
          <div class="stat-box fall">
            <div class="stat-value">{{ (overlayData.summary.max_drawdown * 100).toFixed(2) }}%</div>
            <div class="stat-label">最大回撤</div>
          </div>
        </el-col>
        <el-col :xs="12" :sm="6" :md="4">
          <div class="stat-box rise">
            <div class="stat-value">{{ overlayData.summary.buy_count }}</div>
            <div class="stat-label">买入信号</div>
          </div>
        </el-col>
        <el-col :xs="12" :sm="6" :md="4">
          <div class="stat-box fall">
            <div class="stat-value">{{ overlayData.summary.sell_count }}</div>
            <div class="stat-label">卖出信号</div>
          </div>
        </el-col>
        <el-col :xs="12" :sm="6" :md="4">
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
          <span style="font-weight: 600">每日持仓明细</span>
          <el-tag size="small">{{ overlaySignalDays.length }} 个交易日</el-tag>
        </div>
        <div class="responsive-table"><el-table :data="overlaySignalDays" stripe size="small" max-height="500">
          <el-table-column prop="date" label="日期" width="110" sortable fixed />
          <el-table-column label="持仓" min-width="260">
            <template #default="{ row }">
              <template v-if="row.positions.length">
                <div v-for="p in row.positions" :key="p.sector_code" class="holding-item">
                  <span class="holding-etf">{{ p.etf_code || p.sector_code }} {{ p.etf_name || p.sector_name }}</span>
                  <span class="holding-meta">{{ (p.weight * 100).toFixed(1) }}% {{ formatOverlayMoney(p.amount) }}</span>
                </div>
              </template>
              <span v-else style="color: var(--text-tertiary)">空仓</span>
            </template>
          </el-table-column>
          <el-table-column label="买入" min-width="150">
            <template #default="{ row }">
              <el-tag v-for="sig in row.buySignals" :key="sig.sector_code" size="small" type="danger" style="margin: 1px">
                {{ sig.sector_name }}
              </el-tag>
              <span v-if="!row.buySignals.length" style="color: var(--text-tertiary)">-</span>
            </template>
          </el-table-column>
          <el-table-column label="卖出" min-width="150">
            <template #default="{ row }">
              <el-tag v-for="sig in row.sellSignals" :key="sig.sector_code" size="small" type="success" style="margin: 1px">
                {{ sig.sector_name }}
              </el-tag>
              <span v-if="!row.sellSignals.length" style="color: var(--text-tertiary)">-</span>
            </template>
          </el-table-column>
          <el-table-column prop="strategy_return" label="策略日收益" width="100" sortable>
            <template #default="{ row }">
              <span :style="{ color: row.strategy_return >= 0 ? '#f56c6c' : '#67c23a' }">
                {{ row.strategy_return >= 0 ? '+' : '' }}{{ row.strategy_return.toFixed(2) }}%
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="benchmark_return" label="基准日收益" width="100">
            <template #default="{ row }">
              <span style="color: var(--text-tertiary)">{{ row.benchmark_return >= 0 ? '+' : '' }}{{ row.benchmark_return.toFixed(2) }}%</span>
            </template>
          </el-table-column>
          <el-table-column prop="total_position_value" label="持仓市值" width="105">
            <template #default="{ row }">{{ formatOverlayMoney(row.total_position_value) }}</template>
          </el-table-column>
          <el-table-column prop="cash" label="现金" width="105">
            <template #default="{ row }">{{ formatOverlayMoney(row.cash) }}</template>
          </el-table-column>
          <el-table-column prop="total_asset" label="总资产" width="105" sortable>
            <template #default="{ row }">{{ formatOverlayMoney(row.total_asset) }}</template>
          </el-table-column>
        </el-table></div>
      </div>

      <!-- 调仓明细 -->
      <div v-if="overlayRebalanceGroups.length" style="margin-top: 16px">
        <div class="card-header" style="margin-bottom: 8px">
          <span style="font-weight: 600">调仓明细</span>
          <el-tag size="small">{{ overlayRebalanceGroups.length }} 个调仓日</el-tag>
        </div>
        <div v-for="group in overlayRebalanceGroups" :key="group.date" class="rebalance-group">
          <div class="rebalance-date-header">
            <span class="rebalance-date">{{ group.date }}</span>
            <el-tag size="small">{{ group.trades.length }} 笔调仓</el-tag>
          </div>
          <!-- 持仓快照 -->
          <div v-if="group.snapshot?.portfolio?.length" class="responsive-table" style="margin: 8px 0">
            <el-table :data="group.snapshot.portfolio" stripe size="small" max-height="200">
              <el-table-column prop="sector_name" label="板块" width="120" />
              <el-table-column prop="weight" label="仓位" width="80">
                <template #default="{ row }">{{ (row.weight * 100).toFixed(1) }}%</template>
              </el-table-column>
              <el-table-column prop="amount" label="金额" width="100">
                <template #default="{ row }">{{ formatOverlayMoney(row.amount) }}</template>
              </el-table-column>
              <el-table-column prop="day_change_pct" label="当日涨跌" width="90">
                <template #default="{ row }">
                  <span :style="{ color: row.day_change_pct >= 0 ? '#f56c6c' : '#67c23a' }">
                    {{ row.day_change_pct >= 0 ? '+' : '' }}{{ row.day_change_pct.toFixed(2) }}%
                  </span>
                </template>
              </el-table-column>
              <el-table-column prop="contribution_pct" label="贡献" width="80">
                <template #default="{ row }">
                  <span :style="{ color: row.contribution_pct >= 0 ? '#f56c6c' : '#67c23a' }">
                    {{ row.contribution_pct >= 0 ? '+' : '' }}{{ row.contribution_pct.toFixed(2) }}%
                  </span>
                </template>
              </el-table-column>
            </el-table>
          </div>
          <div v-else-if="group.snapshot && !group.snapshot.portfolio?.length" style="color:#909399;font-size:12px;margin:4px 0">空仓</div>
          <!-- 交易记录 -->
          <div class="rebalance-trades">
            <el-tag v-for="(t, idx) in group.trades" :key="idx" size="small"
              :type="overlayTradeTagType(t.action)" style="margin: 2px">
              {{ t.sector_name || t.sector_code }} {{ overlayActionLabel(t.action) }}
              <span v-if="t.amount > 0">{{ formatOverlayMoney(t.amount) }}</span>
              <span v-if="t.cost > 0" style="opacity:0.7"> (费{{ t.cost.toFixed(1) }})</span>
            </el-tag>
          </div>
          <div v-if="group.trades.length && group.trades[0].reason" style="color: #909399; font-size: 12px; margin-top: 4px">
            {{ group.trades[0].reason }}
          </div>
        </div>
      </div>
    </div>

    <div v-else-if="replayMode === 'strategyOverlay' && !overlayLoading" class="page-card page-section">
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
import { useThemeStore } from '@/stores/theme'
import { useBreakpoint } from '@/composables/useBreakpoint'
import dayjs from 'dayjs'

const bp = useBreakpoint()

use([BarChart, LineChart, ScatterChart, CandlestickChart, GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, MarkLineComponent, MarkPointComponent, CanvasRenderer])

const themeStore = useThemeStore()

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
const nTrials = ref(50)
const autoOptimize = ref(false)
const optimizationProgress = ref(0)
const totalCombinations = ref(0)
const bestParams = ref<any>(null)
const abortOptimize = ref(false)
const overlayData = ref<{
  daily_signals: any[]
  nav_curve: any[]
  summary: any
  position_changes: any[]
  portfolio_snapshots?: any[]
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
  return overlayData.value.daily_signals.map(d => {
    const positions = d.positions ? Object.entries(d.positions).map(([code, info]: [string, any]) => ({
      sector_code: code,
      sector_name: info.sector_name || code,
      etf_code: info.etf_code,
      etf_name: info.etf_name,
      weight: info.weight,
      amount: info.amount,
    })) : []
    const positionValue = d.total_position_value || positions.reduce((sum: number, p: any) => sum + (p.amount || 0), 0)
    const cash = d.cash || 0
    return {
      date: d.date,
      buySignals: (d.signals || []).filter((s: any) => s.direction === 'BUY'),
      sellSignals: (d.signals || []).filter((s: any) => s.direction === 'SELL'),
      strategy_return: d.strategy_return,
      benchmark_return: d.benchmark_return,
      positions,
      total_position_value: positionValue,
      cash,
      total_asset: d.total_asset != null ? d.total_asset : positionValue + cash,
    }
  })
})

function formatMoney(val: number): string {
  return (val / 10000).toFixed(1)
}

function overlayActionLabel(action: string): string {
  const map: Record<string, string> = {
    ADD: '加仓', REDUCE: '减仓', CLEAR: '清仓',
    STOP_LOSS: '止损', TAKE_PROFIT: '止盈', EMERGENCY_EXIT: '紧急清仓', BEAR_EXIT: '熊市清仓',
    HOLD: '继续持有',
  }
  return map[action] || action
}

function overlayTradeTagType(action: string): string {
  const map: Record<string, string> = {
    ADD: 'danger', REDUCE: 'warning', CLEAR: 'success',
    STOP_LOSS: 'danger', TAKE_PROFIT: 'warning', EMERGENCY_EXIT: 'danger', BEAR_EXIT: 'danger',
    HOLD: 'info',
  }
  return map[action] || 'info'
}

function overlayTriggerLabel(trigger: string): string {
  const map: Record<string, string> = {
    rebalance: '调仓', stop_loss: '止损', emergency_exit: '紧急退出', bear_exit: '熊市清仓',
  }
  return map[trigger] || trigger
}

function formatOverlayMoney(val: number): string {
  if (val == null) return '-'
  return (val / 10000).toFixed(2) + '万'
}

const overlayRebalanceGroups = computed(() => {
  const changes = overlayData.value?.position_changes
  const snapshots = overlayData.value?.portfolio_snapshots || []
  if (!changes?.length) return []
  const groupMap: Record<string, { date: string; trades: any[]; snapshot: any }> = {}
  for (const item of changes) {
    const d = item.date
    if (!groupMap[d]) {
      const snap = snapshots.find((s: any) => s.date === d)
      groupMap[d] = { date: d, trades: [], snapshot: snap || null }
    }
    groupMap[d].trades.push(item)
  }
  return Object.values(groupMap)
})

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
  totalCombinations.value = nTrials.value
  optimizationProgress.value = 0
  overlayLoading.value = true
  abortOptimize.value = false
  bestParams.value = null
  overlayData.value = null

  try {
    // 触发后台寻优（立即返回），随后轮询进度直至完成
    await settingsApi.runStrategyOptimize({
      start_date: overlayDateRange.value[0],
      end_date: overlayDateRange.value[1],
      strategy_type: overlayStrategyType.value,
      initial_capital: overlayCapital.value,
      n_trials: nTrials.value,
    })

    // 轮询等待寻优完成（后台运行可能远超HTTP超时，因此不走长连接）
    while (!abortOptimize.value) {
      await new Promise(resolve => setTimeout(resolve, 2000))
      let p: any
      try {
        p = await settingsApi.getOptimizeProgress()
      } catch { continue }
      if (p.total) totalCombinations.value = p.total
      optimizationProgress.value = p.completed
      if (!p.active) break
    }
    if (abortOptimize.value) return

    // 确保进度显示为 100%
    optimizationProgress.value = totalCombinations.value

    const res: any = await settingsApi.getOptimizeResult()
    const result = res?.result
    if (result && result.best_params && result.best_result) {
      overlayData.value = {
        daily_signals: result.best_result.daily_signals || [],
        nav_curve: result.best_result.nav_curve || [],
        summary: result.best_result,
        position_changes: result.best_result.position_changes || [],
        portfolio_snapshots: result.best_result.portfolio_snapshots || [],
      }
      bestParams.value = result.best_params

      const totalReturn = (result.best_result.total_return * 100).toFixed(2)
      const maxDrawdown = (result.best_result.max_drawdown * 100).toFixed(2)
      const combos = result.all_results?.length || 0
      ElMessage.success({
        message: `寻优完成! 测试${combos}种参数, 最优收益=${totalReturn}%, 最大回撤=${maxDrawdown}%`,
        duration: 5000,
      })
    } else {
      ElMessage.error('寻优失败: 无有效结果')
    }
  } catch (e: any) {
    if (!abortOptimize.value) ElMessage.error('策略寻优失败: ' + (e?.message || '未知错误'))
  } finally {
    overlayLoading.value = false
  }
}

function onModeChange() { abortOptimize.value = true; stopAutoPlay() }

// ============ 资金流向柱状图（按日期）- 双面板布局 ============
const flowChartOption = computed(() => {
  if (!dayData.value?.sectors?.length) return {}
  const isDark = themeStore.mode === 'dark'
  const gridColor = isDark ? '#2a2d38' : '#ebeef5'
  const textColor = isDark ? '#9da1b0' : '#5a5f6e'
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
    legend: { data: ['涨跌幅(%)', '主力净流入(亿)', '北向净流入(亿)'], selectedMode: 'multiple', textStyle: { color: textColor } },
    grid: [
      { left: 70, right: 50, top: 35, height: '42%' },
      { left: 70, right: 50, top: '58%', height: '32%' },
    ],
    dataZoom: [
      { type: 'inside', xAxisIndex: [0, 1], start: 0, end: 100 },
      { type: 'slider', xAxisIndex: [0, 1], start: 0, end: 100, bottom: 5, height: 20, textStyle: { color: textColor } },
    ],
    xAxis: [
      { type: 'category', data: sectorNames, gridIndex: 0, axisLabel: { show: false }, position: 'top' },
      { type: 'category', data: sectorNames, gridIndex: 1, axisLabel: { rotate: bp.isMobile.value ? 90 : 45, fontSize: bp.isMobile.value ? 9 : 10, color: textColor, interval: bp.labelInterval(sectorNames.length) }, position: 'bottom' },
    ],
    yAxis: [
      { type: 'value', name: '涨跌幅(%)', position: 'left', gridIndex: 0, nameTextStyle: { color: textColor }, axisLine: { show: true, lineStyle: { color: isDark ? '#7b93f5' : '#409eff' } }, axisLabel: { formatter: '{value}%', color: isDark ? '#646878' : '#9499a6' }, splitLine: { lineStyle: { color: gridColor } } },
      { type: 'value', name: '主力(亿)', position: 'left', gridIndex: 1, offset: 0, nameTextStyle: { color: textColor }, axisLine: { show: true, lineStyle: { color: isDark ? '#f06060' : '#f56c6c' } }, axisLabel: { formatter: '{value}', margin: 8, color: isDark ? '#646878' : '#9499a6' }, splitLine: { lineStyle: { color: gridColor } } },
      { type: 'value', name: '北向(亿)', position: 'right', gridIndex: 1, axisLine: { show: true, lineStyle: { color: isDark ? '#eebb3c' : '#e6a23c' } }, axisLabel: { formatter: '{value}', margin: 8, color: isDark ? '#646878' : '#9499a6' }, splitLine: { show: false } },
    ],
    series: [
      { name: '涨跌幅(%)', type: 'bar', xAxisIndex: 0, yAxisIndex: 0, data: changes, itemStyle: { color: (p: any) => p.data >= 0 ? '#f56c6c' : '#67c23a' }, barMaxWidth: 24 },
      { name: '主力净流入(亿)', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: mainFlow, itemStyle: { color: '#f56c6c' }, barMaxWidth: 16 },
      { name: '北向净流入(亿)', type: 'bar', xAxisIndex: 1, yAxisIndex: 2, data: northFlow, itemStyle: { color: '#e6a23c' }, barMaxWidth: 16 },
    ],
  }
})

// ============ 板块K线图 + 资金流（按板块）- 双面板布局 ============
const sectorHistoryChartOption = computed(() => {
  if (!sectorHistory.value.length) return {}
  const isDark = themeStore.mode === 'dark'
  const gridColor = isDark ? '#2a2d38' : '#eee'
  const textColor = isDark ? '#9da1b0' : '#5a5f6e'
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
    legend: { data: ['K线', 'MA5', 'MA10', '主力净流入(亿)', '北向净流入(亿)'], top: 0, textStyle: { color: textColor } },
    // 上下双面板：上方K线占70%，下方资金流占30%
    grid: [
      { left: 70, right: 20, top: 30, height: '52%' },  // K线主图
      { left: 70, right: 20, top: '72%', height: '20%' }, // 资金流副图
    ],
    xAxis: [
      { type: 'category', data: dates, axisLabel: { show: false }, axisTick: { show: false } },
      { type: 'category', data: dates, gridIndex: 1, axisLabel: { rotate: bp.isMobile.value ? 90 : 30, fontSize: bp.isMobile.value ? 9 : 10, color: textColor, interval: bp.labelInterval(dates.length) } },
    ],
    yAxis: [
      { type: 'value', name: '指数', scale: true, nameTextStyle: { color: textColor }, axisLabel: { color: isDark ? '#646878' : '#9499a6' }, splitLine: { lineStyle: { color: gridColor } } },  // 主图Y轴
      { type: 'value', name: '亿元', gridIndex: 1, nameTextStyle: { color: textColor }, axisLabel: { color: isDark ? '#646878' : '#9499a6' }, splitLine: { lineStyle: { color: gridColor } } },  // 副图Y轴
    ],
    dataZoom: [
      { type: 'inside', xAxisIndex: [0, 1], start: Math.max(0, (1 - 60 / dates.length) * 100) },
      { type: 'slider', xAxisIndex: [0, 1], bottom: 5, height: 18, textStyle: { color: textColor } },
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
  const isDark = themeStore.mode === 'dark'
  const gridColor = isDark ? '#2a2d38' : '#ebeef5'
  const textColor = isDark ? '#9da1b0' : '#5a5f6e'
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
    legend: { data: ['策略净值', '基准净值', '买入点', '卖出点'], textStyle: { color: textColor } },
    grid: { left: 80, right: 30, bottom: 60, top: 40 },
    dataZoom: [{ type: 'inside' }, { type: 'slider', textStyle: { color: textColor } }],
    xAxis: { type: 'category', data: curve.map((p: any) => p.date), axisLabel: { rotate: bp.isMobile.value ? 90 : 30, fontSize: bp.isMobile.value ? 9 : 10, interval: bp.labelInterval(curve.length), color: textColor } },
    yAxis: { type: 'value', name: '净值', scale: true, nameTextStyle: { color: textColor }, axisLabel: { formatter: (v: number) => (v / 10000).toFixed(0) + '万', color: isDark ? '#646878' : '#9499a6' }, splitLine: { lineStyle: { color: gridColor } } },
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

onUnmounted(() => { abortOptimize.value = true; stopAutoPlay() })
init()
</script>

<style lang="scss" scoped>
.replay-controls {
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap; padding: 8px 0;
}
.control-date-range { width: 260px; max-width: 100%; }
.control-select { width: 160px; max-width: 100%; }
.control-select-wide { width: 200px; max-width: 100%; }
.control-select-small { width: 150px; max-width: 100%; }
.control-input-num { width: 140px; max-width: 100%; }
.control-input-num-small { width: 120px; max-width: 100%; }
.date-progress { font-size: 14px; color: var(--accent-primary); font-weight: 600; margin-left: 8px; }
.stat-box {
  text-align: center; padding: 16px; background: var(--bg-tertiary); border-radius: var(--radius-sm);
  transition: background var(--transition-base);
  .stat-value { font-size: 20px; font-weight: 600; color: var(--text-primary); }
  .stat-label { font-size: 12px; color: var(--text-tertiary); margin-top: 4px; }
  &.rise .stat-value { color: var(--accent-danger); }
  &.fall .stat-value { color: var(--accent-success); }
}
.card-header {
  display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;
  .card-title { font-size: 16px; font-weight: 600; color: var(--text-primary); }
}
.params-display {
  margin-bottom: 12px; padding: 8px;
  background: var(--bg-tertiary); border-radius: var(--radius-sm);
}
.rebalance-group {
  margin-bottom: 16px; padding: 12px; background: var(--bg-tertiary); border-radius: var(--radius-sm);
  border-left: 3px solid var(--accent-primary);
}
.rebalance-date-header {
  display: flex; align-items: center; gap: 8px; margin-bottom: 8px;
  .rebalance-date { font-weight: 600; font-size: 14px; color: var(--text-primary); }
  .rebalance-cash { font-size: 12px; color: var(--text-tertiary); margin-left: auto; }
}
.rebalance-trades { margin-top: 8px; display: flex; flex-wrap: wrap; gap: 4px; }
.empty-portfolio { color: var(--text-tertiary); font-size: 13px; padding: 8px 0; }
.holding-item {
  display: flex; align-items: center; justify-content: space-between; gap: 8px;
  padding: 2px 8px; margin: 2px 0; border-radius: 4px; font-size: 12px;
  background: var(--bg-secondary, #f5f6f8);
  .holding-etf { font-weight: 600; color: var(--text-primary); white-space: nowrap; }
  .holding-meta { color: var(--text-secondary); white-space: nowrap; }
}
:deep(.el-tabs__nav-wrap::after) { display: none; }

@media (max-width: 768px) {
  .stat-box { padding: 10px; .stat-value { font-size: 16px; } }
  .card-header { flex-wrap: wrap; gap: 8px; }
  .replay-controls {
    :deep(.el-date-picker),
    :deep(.el-select),
    :deep(.el-input-number),
    :deep(.el-button) {
      max-width: 100%;
    }
  }
  :deep(.el-row) { margin-left: -8px !important; margin-right: -8px !important; }
  :deep(.el-col) { padding-left: 8px !important; padding-right: 8px !important; margin-bottom: 8px; }
}
@media (max-width: 480px) {
  .replay-controls {
    flex-direction: column; align-items: stretch;
    :deep(.el-divider--vertical) { display: none; }
  }
  .control-date-range,
  .control-select,
  .control-select-wide,
  .control-select-small,
  .control-input-num,
  .control-input-num-small { width: 100%; }
  .stat-box { padding: 8px; .stat-value { font-size: 14px; } }
  .card-header { flex-direction: column; align-items: flex-start; }
  .params-display { font-size: 12px; }
  .date-progress { margin-left: auto; font-size: 12px; }
  :deep(.el-row) { margin-left: -4px !important; margin-right: -4px !important; }
  :deep(.el-col) { padding-left: 4px !important; padding-right: 4px !important; margin-bottom: 6px; }
}
</style>
