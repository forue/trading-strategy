<template>
  <div class="strategy-page">
    <el-row :gutter="20">
      <!-- 三档策略卡片 -->
      <el-col :xs="24" :md="12" :lg="8" v-for="strategy in strategies" :key="strategy.type">
        <div class="strategy-card" :class="strategy.type.toLowerCase()">
          <div class="strategy-header">
            <el-icon :size="32"><component :is="strategy.icon" /></el-icon>
            <h3>{{ strategy.name }}</h3>
            <el-tag :type="strategy.tagType" size="small">{{ strategy.riskLevel }}</el-tag>
          </div>
          <p class="strategy-desc">{{ strategy.description }}</p>

          <el-form label-width="100px" size="small">
            <el-form-item label="选取前N名">
              <el-input-number v-model="strategy.params.top_n" :min="1" :max="10" />
            </el-form-item>
            <el-form-item label="最大仓位">
              <el-slider v-model="strategy.params.max_position_pct" :min="10" :max="100" :step="5" show-stops format-tooltip="(v) => v + '%'" />
            </el-form-item>
            <el-form-item label="持有天数">
              <el-input-number v-model="strategy.params.hold_days" :min="1" :max="30" />
            </el-form-item>
            <el-form-item label="止损比例">
              <el-input-number v-model="strategy.params.stop_loss_pct" :min="1" :max="20" :step="0.5" />
            </el-form-item>
            <el-form-item v-if="strategy.type === 'CONSERVATIVE'" label="估值分位上限">
              <el-input-number v-model="strategy.params.valuation_pct_max" :min="10" :max="90" :step="5" />
            </el-form-item>
            <!-- 交易成本设置 -->
            <el-form-item label="佣金费率">
              <el-input-number v-model="strategy.params.commission_rate_pct" :min="0.1" :max="5" :step="0.1" :precision="2" />
              <span class="unit">‰ (千分之)</span>
            </el-form-item>
            <el-form-item label="印花税率">
              <el-input-number v-model="strategy.params.stamp_tax_rate_pct" :min="0.1" :max="5" :step="0.1" :precision="2" />
              <span class="unit">‰ (千分之)</span>
            </el-form-item>
            <el-form-item label="滑点费率">
              <el-input-number v-model="strategy.params.slippage_rate_pct" :min="0.1" :max="5" :step="0.1" :precision="2" />
              <span class="unit">‰ (千分之)</span>
            </el-form-item>
          </el-form>

          <div class="strategy-actions">
            <el-button type="primary" @click="saveStrategy(strategy)">保存配置</el-button>
            <el-button type="warning" plain @click="resetStrategy(strategy)">恢复默认</el-button>
          </div>
        </div>
      </el-col>
    </el-row>

    <!-- 回测区域 -->
    <div class="page-card page-section">
      <div class="card-header">
        <span class="card-title">策略回测</span>
        <div class="backtest-header-right">
          <el-tag v-if="dataAvailability.has_data" size="small" type="success">
            数据范围: {{ dataAvailability.min_date }} ~ {{ dataAvailability.max_date }}
          </el-tag>
          <el-tag v-else size="small" type="danger">无历史数据</el-tag>
          <el-button size="small" :loading="collecting" @click="collectHistoryData" type="warning">
            {{ collecting ? '采集中...' : '采集历史数据' }}
          </el-button>
        </div>
      </div>
      <el-alert v-if="!dataAvailability.has_data" title="暂无历史数据，请先点击「采集历史数据」按钮获取数据后再进行回测" type="warning" :closable="false" show-icon style="margin-bottom: 16px;" />
      <el-form :inline="true" :model="backtestForm" size="default">
        <el-form-item label="策略类型">
          <el-select v-model="backtestForm.strategyType" style="width: 140px">
            <el-option label="激进轮动" value="AGGRESSIVE" />
            <el-option label="稳健轮动" value="MODERATE" />
            <el-option label="保守轮动" value="CONSERVATIVE" />
          </el-select>
        </el-form-item>
        <el-form-item label="起始日期">
          <el-date-picker v-model="backtestForm.startDate" type="date" value-format="YYYY-MM-DD" placeholder="起始日期" />
        </el-form-item>
        <el-form-item label="结束日期">
          <el-date-picker v-model="backtestForm.endDate" type="date" value-format="YYYY-MM-DD" placeholder="结束日期" />
        </el-form-item>
        <el-form-item label="初始资金(万)">
          <el-input-number v-model="backtestForm.initialCapital" :min="10" :max="10000" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="backtesting" @click="runBacktest" :disabled="!dataAvailability.has_data">开始回测</el-button>
        </el-form-item>
      </el-form>

      <!-- 当前回测任务：外框流光表示仍在计算，进度与交易日计数来自后端真实回放 -->
      <div v-if="backtestTask" class="bt-task-card" :class="{ 'is-done': backtestTask.status === 'done' }">
        <div class="bt-task-head">
          <span class="bt-task-title">
            {{ backtestTask.status === 'done' ? '回测完成' : '回测中' }} ·
            {{ backtestTask.strategyType === 'AGGRESSIVE' ? '激进' : backtestTask.strategyType === 'MODERATE' ? '稳健' : '保守' }}
          </span>
          <span class="bt-task-range">{{ backtestTask.startDate }} ~ {{ backtestTask.endDate }}</span>
        </div>
        <!-- 取数阶段拿不到真实百分比（耗时取决于 InfluxDB），用流动条表示仍在工作 -->
        <div class="bt-task-bar"
          :class="{ 'is-indeterminate': backtestTask.total === 0, 'is-done': backtestTask.status === 'done' }">
          <div class="bt-task-bar-fill" :style="backtestTask.total > 0 ? { width: backtestTask.progress + '%' } : undefined" />
        </div>
        <div class="bt-task-foot">
          <span>{{ backtestStageText }}</span>
          <span class="bt-task-meta">
            {{ backtestTask.total > 0 ? backtestTask.progress + '% · ' : '' }}已用 {{ backtestElapsed }}s
          </span>
        </div>
      </div>

      <div v-if="backtestResult" class="backtest-result">
        <el-row :gutter="16">
          <el-col :xs="12" :sm="6"><div class="result-item"><span>总收益率</span><strong>{{ (backtestResult.totalReturn * 100).toFixed(2) }}%</strong></div></el-col>
          <el-col :xs="12" :sm="6"><div class="result-item"><span>年化收益</span><strong>{{ (backtestResult.annualReturn * 100).toFixed(2) }}%</strong></div></el-col>
          <el-col :xs="12" :sm="6"><div class="result-item"><span>最大回撤</span><strong>{{ (backtestResult.maxDrawdown * 100).toFixed(2) }}%</strong></div></el-col>
          <el-col :xs="12" :sm="6"><div class="result-item"><span>夏普比率</span><strong>{{ backtestResult.sharpeRatio?.toFixed(2) }}</strong></div></el-col>
        </el-row>
        <el-row :gutter="16" class="result-row">
          <el-col :xs="12" :sm="6"><div class="result-item"><span>累计佣金</span><strong>{{ backtestResult.totalCommission?.toFixed(2) }}元</strong></div></el-col>
          <el-col :xs="12" :sm="6"><div class="result-item"><span>累计印花税</span><strong>{{ backtestResult.totalStampTax?.toFixed(2) }}元</strong></div></el-col>
          <el-col :xs="12" :sm="6"><div class="result-item"><span>累计滑点成本</span><strong>{{ backtestResult.totalSlippageCost?.toFixed(2) }}元</strong></div></el-col>
          <el-col :xs="12" :sm="6"><div class="result-item"><span>总交易成本</span><strong>{{ backtestResult.totalTradeCost?.toFixed(2) }}元</strong></div></el-col>
        </el-row>
        <el-row :gutter="16" class="result-row">
          <el-col :xs="12" :sm="6"><div class="result-item"><span>交易笔数</span><strong>{{ backtestResult.tradeCount }}</strong></div></el-col>
          <el-col :xs="12" :sm="6"><div class="result-item"><span>实际交易笔数</span><strong>{{ backtestResult.tradeCountActual }}</strong></div></el-col>
          <el-col :xs="12" :sm="6"><div class="result-item"><span>胜率</span><strong>{{ (backtestResult.winRate * 100).toFixed(2) }}%</strong></div></el-col>
          <el-col :xs="12" :sm="6"><div class="result-item"><span>成本/总收益比</span><strong>{{ backtestResult.totalReturn > 0 ? (backtestResult.totalTradeCost / (backtestResult.totalReturn * backtestForm.initialCapital * 10000) * 100).toFixed(2) : '0.00' }}%</strong></div></el-col>
        </el-row>
        <v-chart :option="backtestChartOption" class="backtest-chart" autoresize />
      </div>
    </div>

    <!-- 回测历史 -->
    <div class="page-card page-section">
      <div class="card-header">
        <span class="card-title">回测历史</span>
        <el-button size="small" @click="loadBacktestHistory">刷新</el-button>
      </div>
      <!-- 手机端：九列回测历史改为指标条目 -->
      <ul v-if="isMobile && backtestHistory.length > 0" class="m-bt-list">
        <li v-for="row in backtestHistory" :key="row.id" class="m-bt-row">
          <div class="m-bt-head">
            <el-tag :type="row.strategy_type === 'AGGRESSIVE' ? 'danger' : row.strategy_type === 'MODERATE' ? 'warning' : 'success'" size="small">
              {{ row.strategy_type === 'AGGRESSIVE' ? '激进' : row.strategy_type === 'MODERATE' ? '稳健' : '保守' }}
            </el-tag>
            <span class="m-bt-time">{{ formatTime(row.created_at).slice(5, 16) }}</span>
            <el-button link type="primary" size="small" @click="viewBacktestDetail(row.id)">详情</el-button>
          </div>
          <div class="m-bt-grid">
            <div><em>总收益</em><b :style="{ color: row.total_return >= 0 ? themeColors.profit : themeColors.loss }">{{ (row.total_return * 100).toFixed(2) }}%</b></div>
            <div><em>年化</em><b :style="{ color: row.annual_return >= 0 ? themeColors.profit : themeColors.loss }">{{ (row.annual_return * 100).toFixed(2) }}%</b></div>
            <div><em>最大回撤</em><b>{{ (row.max_drawdown * 100).toFixed(2) }}%</b></div>
            <div><em>夏普</em><b>{{ row.sharpe_ratio?.toFixed(2) }}</b></div>
          </div>
          <div class="m-bt-range">{{ row.start_date }} ~ {{ row.end_date }}</div>
          <div v-if="row.params" class="m-bt-params">
            Top{{ row.params.top_n }} · 仓{{ (row.params.max_position * 100).toFixed(0) }}% · 持{{ row.params.hold_days }}日 · 止{{ (row.params.stop_loss * 100).toFixed(1) }}%
          </div>
        </li>
      </ul>

      <div v-else-if="backtestHistory.length > 0" class="responsive-table">
        <el-table :data="backtestHistory" stripe size="small">
        <el-table-column prop="created_at" label="时间" width="160">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column prop="strategy_type" label="策略" width="80">
          <template #default="{ row }">
            <el-tag :type="row.strategy_type === 'AGGRESSIVE' ? 'danger' : row.strategy_type === 'MODERATE' ? 'warning' : 'success'" size="small">
              {{ row.strategy_type === 'AGGRESSIVE' ? '激进' : row.strategy_type === 'MODERATE' ? '稳健' : '保守' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="区间" width="160">
          <template #default="{ row }">{{ row.start_date }} ~ {{ row.end_date }}</template>
        </el-table-column>
        <el-table-column label="总收益率" width="110" align="right">
          <template #default="{ row }">
            <span :style="{ color: row.total_return >= 0 ? themeColors.profit : themeColors.loss }">
              {{ (row.total_return * 100).toFixed(2) }}%
            </span>
          </template>
        </el-table-column>
        <el-table-column label="年化收益" width="110" align="right">
          <template #default="{ row }">
            <span :style="{ color: row.annual_return >= 0 ? themeColors.profit : themeColors.loss }">
              {{ (row.annual_return * 100).toFixed(2) }}%
            </span>
          </template>
        </el-table-column>
        <el-table-column label="最大回撤" width="110" align="right">
          <template #default="{ row }">{{ (row.max_drawdown * 100).toFixed(2) }}%</template>
        </el-table-column>
        <el-table-column label="夏普" width="80" align="right">
          <template #default="{ row }">{{ row.sharpe_ratio?.toFixed(2) }}</template>
        </el-table-column>
        <el-table-column label="策略参数" min-width="200">
          <template #default="{ row }">
            <div v-if="row.params" class="params-cell">
              <el-tag size="small" type="info">Top{{ row.params.top_n }}</el-tag>
              <el-tag size="small" type="info">仓{{ (row.params.max_position * 100).toFixed(0) }}%</el-tag>
              <el-tag size="small" type="info">持{{ row.params.hold_days }}日</el-tag>
              <el-tag size="small" type="info">止{{ (row.params.stop_loss * 100).toFixed(1) }}%</el-tag>
              <el-tag v-if="row.params.valuation_pct_max" size="small" type="info">估值≤{{ row.params.valuation_pct_max }}%</el-tag>
            </div>
            <span v-else :style="{ color: themeColors.textSub }">默认参数</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="80">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="viewBacktestDetail(row.id)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>
      </div>
      <el-empty v-else description="暂无回测历史" />
    </div>

    <!-- 调仓明细：明细较长，独立放在回测历史之后；按日期倒序，最近的调仓在最前 -->
    <div v-if="rebalanceGroups.length" class="page-card page-section">
      <div class="card-header">
        <span class="card-title">调仓明细</span>
        <el-tag size="small">{{ rebalanceGroups.length }} 个调仓日</el-tag>
      </div>
      <div v-for="group in rebalanceGroups" :key="group.date" class="rebalance-group">
        <div class="rebalance-date-header">
          <span class="rebalance-date">{{ group.date }}</span>
          <el-tag size="small">{{ group.trades.length }} 笔调仓</el-tag>
        </div>
        <!-- 持仓快照 -->
        <template v-if="group.snapshot?.portfolio?.length">
          <!-- 手机端：五列持仓表改为条目，避免横向滑动 -->
          <ul v-if="isMobile" class="m-pf-list">
            <li v-for="(row, i) in group.snapshot.portfolio" :key="i" class="m-pf-row">
              <div class="m-pf-head">
                <span class="m-pf-name">{{ row.sector_name }}</span>
                <span class="m-pf-weight">{{ (row.weight * 100).toFixed(1) }}%</span>
              </div>
              <div class="m-pf-grid">
                <div><em>金额</em><b>{{ formatMoney(row.amount) }}</b></div>
                <div>
                  <em>当日涨跌</em>
                  <b :style="{ color: row.day_change_pct >= 0 ? themeColors.profit : themeColors.loss }">
                    {{ row.day_change_pct >= 0 ? '+' : '' }}{{ row.day_change_pct.toFixed(2) }}%
                  </b>
                </div>
                <div>
                  <em>贡献</em>
                  <b :style="{ color: row.contribution_pct >= 0 ? themeColors.profit : themeColors.loss }">
                    {{ row.contribution_pct >= 0 ? '+' : '' }}{{ row.contribution_pct.toFixed(2) }}%
                  </b>
                </div>
              </div>
            </li>
          </ul>
          <div v-else class="responsive-table" style="margin: 8px 0">
            <el-table :data="group.snapshot.portfolio" stripe size="small" max-height="200">
              <el-table-column prop="sector_name" label="板块" min-width="120" />
              <el-table-column prop="weight" label="仓位" min-width="80" align="right">
                <template #default="{ row }">{{ (row.weight * 100).toFixed(1) }}%</template>
              </el-table-column>
              <el-table-column prop="amount" label="金额" min-width="96" align="right">
                <template #default="{ row }">{{ formatMoney(row.amount) }}</template>
              </el-table-column>
              <el-table-column prop="day_change_pct" label="当日涨跌" min-width="96" align="right">
                <template #default="{ row }">
                  <span :style="{ color: row.day_change_pct >= 0 ? themeColors.profit : themeColors.loss }">
                    {{ row.day_change_pct >= 0 ? '+' : '' }}{{ row.day_change_pct.toFixed(2) }}%
                  </span>
                </template>
              </el-table-column>
              <el-table-column prop="contribution_pct" label="贡献" min-width="80" align="right">
                <template #default="{ row }">
                  <span :style="{ color: row.contribution_pct >= 0 ? themeColors.profit : themeColors.loss }">
                    {{ row.contribution_pct >= 0 ? '+' : '' }}{{ row.contribution_pct.toFixed(2) }}%
                  </span>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </template>
        <div v-else-if="group.snapshot && !group.snapshot.portfolio?.length" :style="{ color: themeColors.textSub, fontSize: '12px', margin: '4px 0' }">空仓</div>
        <!-- 交易记录 -->
        <div class="rebalance-trades">
          <el-tag v-for="(t, idx) in group.trades" :key="idx" size="small"
            :type="tradeTagType(t.action)" style="margin: 2px">
            {{ t.sector_name || t.sector_code }} {{ actionLabel(t.action) }}
            <span v-if="t.amount > 0">{{ formatMoney(t.amount) }}</span>
            <span v-if="t.cost > 0" style="opacity:0.7"> (费{{ t.cost.toFixed(1) }})</span>
          </el-tag>
        </div>
        <div v-if="group.trades.length && group.trades[0].reason" class="rebalance-reason" :style="{ color: themeColors.textSub, fontSize: '12px', marginTop: '4px' }">
          {{ group.trades[0].reason }}
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onBeforeUnmount } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { ElMessage, ElMessageBox } from 'element-plus'
import { strategyApi } from '@/api/strategy'
import dayjs from 'dayjs'
import { useThemeStore } from '@/stores/theme'
import { useBreakpoint } from '@/composables/useBreakpoint'

const { isMobile } = useBreakpoint()

use([LineChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

// 语义色随主题切换：暗色下提高红绿明度、网格/边框改用暗色，
// 避免深色文字与浅色网格在 --bg-secondary(#1a1d24) 上不可读或刺眼。
const themeStore = useThemeStore()
const isDark = computed(() => themeStore.mode === 'dark')
const themeColors = computed(() => (isDark.value ? {
  profit: '#ff6f61', loss: '#357a5c', text: '#e8eaef', textSub: '#9da1b0',
  primary: '#7b93f5', neutral: '#909399', grid: '#2a2d38', axis: '#2a2d38',
  tooltipBg: '#252832', tooltipBorder: '#2a2d38',
} : {
  profit: '#f56c6c', loss: '#67c23a', text: '#303133', textSub: '#909399',
  primary: '#409eff', neutral: '#909399', grid: '#ebeef5', axis: '#e4e7ed',
  tooltipBg: '#fff', tooltipBorder: '#ebeef5',
}))

interface StrategyState {
  type: string
  name: string
  icon: string
  tagType: string
  riskLevel: string
  description: string
  params: {
    top_n: number
    max_position_pct: number
    hold_days: number
    stop_loss_pct: number
    capital_pct: number
    valuation_pct_max: number
    commission_rate_pct: number
    stamp_tax_rate_pct: number
    slippage_rate_pct: number
  }
}

const strategies = reactive<StrategyState[]>([
  {
    type: 'AGGRESSIVE', name: '激进轮动策略', icon: 'Lightning', tagType: 'danger', riskLevel: '高风险',
    description: '仅取资金强度前2名板块，满仓轮换，持有周期1-3日，追求最大收益',
    params: { top_n: 2, max_position_pct: 100, hold_days: 3, stop_loss_pct: 5, capital_pct: 50, valuation_pct_max: 100, commission_rate_pct: 0.3, stamp_tax_rate_pct: 1.0, slippage_rate_pct: 1.0 },
  },
  {
    type: 'MODERATE', name: '稳健轮动策略', icon: 'Odometer', tagType: 'warning', riskLevel: '中风险',
    description: '取资金强度+指数相对强弱综合前3名，半仓分散，持有周期5日',
    params: { top_n: 3, max_position_pct: 50, hold_days: 5, stop_loss_pct: 3, capital_pct: 30, valuation_pct_max: 100, commission_rate_pct: 0.3, stamp_tax_rate_pct: 1.0, slippage_rate_pct: 1.0 },
  },
  {
    type: 'CONSERVATIVE', name: '保守轮动策略', icon: 'Shield', tagType: 'success', riskLevel: '低风险',
    description: '取资金持续流入且估值分位低于50%的板块，仓位上限30%，注重安全边际',
    params: { top_n: 5, max_position_pct: 30, hold_days: 10, stop_loss_pct: 2, capital_pct: 20, valuation_pct_max: 50, commission_rate_pct: 0.3, stamp_tax_rate_pct: 1.0, slippage_rate_pct: 1.0 },
  },
])

const backtesting = ref(false)
// 当前正在执行的回测任务：发起后由进度卡片展示，结束即收起
const backtestTask = ref<{
  strategyType: string
  startDate: string
  endDate: string
  status: string
  progress: number
  done: number
  total: number
} | null>(null)
const backtestElapsed = ref(0)
const backtestStageText = computed(() => {
  const t = backtestTask.value
  if (!t) return ''
  if (t.status === 'queued') return '任务排队中'
  if (t.status === 'done') return '计算完成'
  if (t.total > 0) return `逐日回放 ${t.done}/${t.total} 个交易日`
  return '读取历史行情数据'
})
const collecting = ref(false)
const backtestResult = ref<any>(null)
const dataAvailability = reactive({ has_data: false, min_date: '', max_date: '' })
const backtestForm = reactive({
  strategyType: 'MODERATE',
  startDate: dayjs().subtract(1, 'year').format('YYYY-MM-DD'),
  endDate: dayjs().format('YYYY-MM-DD'),
  initialCapital: 100,
})

// 检查数据可用性
async function checkDataAvailability() {
  try {
    const data = await strategyApi.getDataAvailability()
    dataAvailability.has_data = data.has_data
    dataAvailability.min_date = data.min_date || ''
    dataAvailability.max_date = data.max_date || ''
    // 如果有数据，自动调整日期范围到可用范围
    if (data.has_data && data.min_date && data.max_date) {
      if (backtestForm.startDate < data.min_date) {
        backtestForm.startDate = data.min_date
      }
      if (backtestForm.endDate > data.max_date) {
        backtestForm.endDate = data.max_date
      }
    }
  } catch {
    // 静默失败
  }
}

// 采集历史数据
async function collectHistoryData() {
  collecting.value = true
  try {
    await strategyApi.collectHistory(60)
    ElMessage.success('历史数据采集成功')
    await checkDataAvailability()
  } catch {
    ElMessage.error('数据采集失败')
  } finally {
    collecting.value = false
  }
}

// 页面加载时检查数据
checkDataAvailability()

// 将后端策略配置应用到前端表单（仅覆盖后端返回的字段，缺失字段保留当前值）
function applyBackendParams(strategy: StrategyState, cfg: any) {
  const p = cfg.params
  if (!p) return
  strategy.params.top_n = p.top_n ?? strategy.params.top_n
  strategy.params.max_position_pct = p.max_position != null
    ? Math.round(p.max_position * 100) : strategy.params.max_position_pct
  strategy.params.hold_days = p.hold_days ?? strategy.params.hold_days
  strategy.params.stop_loss_pct = p.stop_loss != null
    ? p.stop_loss * 100 : strategy.params.stop_loss_pct
  // capital_pct 后端小数转百分比
  if (p.capital_pct != null) {
    strategy.params.capital_pct = p.capital_pct * 100
  }
  if (p.valuation_pct_max != null) {
    strategy.params.valuation_pct_max = p.valuation_pct_max
  }
  // 交易成本参数：后端小数转千分比
  if (p.commission_rate != null) {
    strategy.params.commission_rate_pct = p.commission_rate * 1000
  }
  if (p.stamp_tax_rate != null) {
    strategy.params.stamp_tax_rate_pct = p.stamp_tax_rate * 1000
  }
  if (p.slippage_rate != null) {
    strategy.params.slippage_rate_pct = p.slippage_rate * 1000
  }
}

// 从后端加载已保存的策略配置
async function loadStrategyConfigs() {
  try {
    const configs = await strategyApi.getConfigs()
    for (const cfg of configs) {
      const strategy = strategies.find(s => s.type === cfg.strategy_type)
      if (strategy) {
        applyBackendParams(strategy, cfg)
      }
    }
  } catch {
    // 加载失败使用默认值
  }
}
loadStrategyConfigs()

// 恢复策略配置为出厂默认值（权威来源：后端代码内置模板）
async function resetStrategy(strategy: StrategyState) {
  try {
    await ElMessageBox.confirm(`确定将「${strategy.name}」参数恢复为默认值吗？`, '恢复默认', {
      type: 'warning',
      confirmButtonText: '恢复默认',
      cancelButtonText: '取消',
    })
  } catch {
    return  // 用户取消
  }
  try {
    const configId = STRATEGY_ID_MAP[strategy.type]
    const cfg = await strategyApi.resetConfig(configId)
    applyBackendParams(strategy, cfg)
    ElMessage.success(`${strategy.name}已恢复默认参数`)
  } catch {
    ElMessage.error('恢复默认失败')
  }
}

// 策略类型到后端配置id的映射
const STRATEGY_ID_MAP: Record<string, number> = {
  AGGRESSIVE: 1,
  MODERATE: 2,
  CONSERVATIVE: 3,
}

async function saveStrategy(strategy: StrategyState) {
  try {
    const configId = STRATEGY_ID_MAP[strategy.type]
    await strategyApi.updateConfig(configId, {
      strategy_type: strategy.type as any,
      name: strategy.name,
      is_active: true,
      params: {
        top_n: strategy.params.top_n,
        max_position: strategy.params.max_position_pct / 100,
        hold_days: strategy.params.hold_days,
        stop_loss: strategy.params.stop_loss_pct / 100,
        // 交易成本参数：前端使用千分比，后端使用小数
        commission_rate: strategy.params.commission_rate_pct / 1000,
        stamp_tax_rate: strategy.params.stamp_tax_rate_pct / 1000,
        slippage_rate: strategy.params.slippage_rate_pct / 1000,
        ...(strategy.type === 'CONSERVATIVE' ? { valuation_pct_max: strategy.params.valuation_pct_max } : {}),
      },
    })
    ElMessage.success(`${strategy.name}配置已保存`)
  } catch {
    ElMessage.error('保存失败')
  }
}

// 回测改为「提交任务 + 轮询」：单次算完要十几秒，同步请求在手机切换网络时
// 会被浏览器断开并重发，导致后端重复计算、历史里出现两条一样的记录。
const BACKTEST_POLL_INTERVAL = 2000
const BACKTEST_POLL_TIMEOUT = 5 * 60 * 1000
let pollAborted = false

onBeforeUnmount(() => { pollAborted = true })

async function waitBacktestTask(taskId: string): Promise<string> {
  const deadline = Date.now() + BACKTEST_POLL_TIMEOUT
  let networkErrors = 0
  while (Date.now() < deadline) {
    await new Promise(resolve => setTimeout(resolve, BACKTEST_POLL_INTERVAL))
    if (pollAborted) throw new Error('已离开页面，回测仍在后台执行，可稍后刷新回测历史')
    let task
    try {
      task = await strategyApi.getBacktestTask(taskId)
      networkErrors = 0
    } catch (e: any) {
      // 单次查询失败多半是手机网络抖动，任务本身还在后台跑，容忍若干次
      if (e?.response?.status === 404) throw new Error('回测任务已过期，请刷新回测历史')
      if (++networkErrors >= 5) throw new Error('网络异常，回测仍在后台执行，请稍后刷新回测历史')
      continue
    }
    // 同步到进度卡片：百分比与交易日计数都来自后端真实回放进度
    if (backtestTask.value) {
      backtestTask.value.status = task.status
      backtestTask.value.progress = task.progress ?? backtestTask.value.progress
      backtestTask.value.done = task.progress_done ?? backtestTask.value.done
      backtestTask.value.total = task.progress_total ?? backtestTask.value.total
    }
    if (task.status === 'done' && task.bt_id) return task.bt_id
    if (task.status === 'failed') throw new Error(task.error || '回测失败')
  }
  throw new Error('回测超时，请稍后刷新回测历史查看结果')
}

let elapsedTimer: number | undefined

async function runBacktest() {
  pollAborted = false
  backtesting.value = true
  backtestElapsed.value = 0
  backtestTask.value = {
    strategyType: backtestForm.strategyType,
    startDate: backtestForm.startDate,
    endDate: backtestForm.endDate,
    status: 'queued',
    progress: 0,
    done: 0,
    total: 0,
  }
  // 卡片上的「已用 Ns」用本地计时，不依赖轮询频率
  elapsedTimer = window.setInterval(() => { backtestElapsed.value += 1 }, 1000)
  try {
    // 获取当前选中策略的参数
    const currentStrategy = strategies.find(s => s.type === backtestForm.strategyType)
    const strategyParams = currentStrategy ? {
      top_n: currentStrategy.params.top_n,
      max_position: currentStrategy.params.max_position_pct / 100,
      hold_days: currentStrategy.params.hold_days,
      capital_pct: (currentStrategy.params.capital_pct || 30) / 100,  // 转换为小数，默认30%
      stop_loss: currentStrategy.params.stop_loss_pct / 100,
      // 交易成本参数：前端使用千分比，后端使用小数
      commission_rate: currentStrategy.params.commission_rate_pct / 1000,
      stamp_tax_rate: currentStrategy.params.stamp_tax_rate_pct / 1000,
      slippage_rate: currentStrategy.params.slippage_rate_pct / 1000,
      ...(currentStrategy.type === 'CONSERVATIVE' ? { valuation_pct_max: currentStrategy.params.valuation_pct_max } : {}),
    } : undefined

    const task = await strategyApi.submitBacktest({
      strategyType: backtestForm.strategyType,
      startDate: backtestForm.startDate,
      endDate: backtestForm.endDate,
      initialCapital: backtestForm.initialCapital * 10000,
      strategyParams,
    })
    if (task.reused) {
      ElMessage.info('相同参数的回测正在执行，等待结果中')
    }
    // 记下任务：切到其他页面时组件会被卸载，回到本页要能接着等这个任务
    saveBacktestSession({
      taskId: task.task_id,
      strategyType: backtestForm.strategyType,
      startDate: backtestForm.startDate,
      endDate: backtestForm.endDate,
      startedAt: Date.now(),
    })
    const btId = await waitBacktestTask(task.task_id)
    // 任务完成：留下 btId，切页回来直接重新拉结果，不必再跑一遍
    saveBacktestSession({
      btId,
      strategyType: backtestForm.strategyType,
      startDate: backtestForm.startDate,
      endDate: backtestForm.endDate,
      startedAt: Date.now(),
    })
    try {
      applyBacktestResult(await strategyApi.getBacktestDetail(btId))
    } catch {
      // 拦截器已提示；历史列表已刷新，用户可点「详情」重试
    }
    loadBacktestHistory()
    // 让卡片走到 100% 再收起，避免进度条停在半途突然消失
    backtestTask.value.status = 'done'
    backtestTask.value.progress = 100
    await new Promise(resolve => setTimeout(resolve, 600))
  } catch (e: any) {
    // 已离开页面时不再提示，任务仍在后台执行
    if (pollAborted) return
    // axios 错误已由拦截器提示，这里只补充轮询得到的业务原因
    if (!e?.config && e?.message) {
      ElMessage.error(e.message)
    }
    // 任务可能在网络中断期间已经算完，失败也要刷新历史
    loadBacktestHistory()
  } finally {
    if (elapsedTimer !== undefined) {
      window.clearInterval(elapsedTimer)
      elapsedTimer = undefined
    }
    backtestTask.value = null
    backtesting.value = false
  }
}

// ============ 回测任务续接 ============
// 切换路由会卸载本组件（MainLayout 没有 keep-alive），但任务跑在后端。
// 把 task_id / bt_id 记到 sessionStorage：回来时任务没结束就接着轮询，已结束就直接展示结果。
const BACKTEST_SESSION_KEY = 'strategy.backtestSession'

interface BacktestSession {
  taskId?: string
  btId?: string
  strategyType: string
  startDate: string
  endDate: string
  startedAt: number
}

function readBacktestSession(): BacktestSession | null {
  try {
    const raw = sessionStorage.getItem(BACKTEST_SESSION_KEY)
    return raw ? (JSON.parse(raw) as BacktestSession) : null
  } catch {
    return null
  }
}

function saveBacktestSession(session: BacktestSession | null) {
  try {
    if (session) sessionStorage.setItem(BACKTEST_SESSION_KEY, JSON.stringify(session))
    else sessionStorage.removeItem(BACKTEST_SESSION_KEY)
  } catch {
    // 隐私模式下 sessionStorage 不可写，退化成原来的「切页即丢」，不影响回测本身
  }
}

// 回到本页时接上上次的回测：先探测一次任务状态，避免已完成的任务还闪一下「回测中」
async function restoreBacktestSession() {
  const session = readBacktestSession()
  if (!session) return
  if (session.btId) {
    try {
      applyBacktestResult(await strategyApi.getBacktestDetail(session.btId), false)
    } catch {
      saveBacktestSession(null)
    }
    return
  }
  if (!session.taskId) {
    saveBacktestSession(null)
    return
  }
  let probe: any = null
  try {
    probe = await strategyApi.getBacktestTask(session.taskId)
  } catch (e: any) {
    // 服务重启会清空内存里的任务表，这条任务已无从接续
    if (e?.response?.status === 404) saveBacktestSession(null)
    return
  }
  if (probe?.status === 'failed') {
    saveBacktestSession(null)
    loadBacktestHistory()
    return
  }
  if (probe?.status === 'done' && probe.bt_id) {
    saveBacktestSession({ ...session, taskId: undefined, btId: probe.bt_id })
    try {
      applyBacktestResult(await strategyApi.getBacktestDetail(probe.bt_id), false)
    } catch {
      // 拦截器已提示，用户可从回测历史点「详情」重试
    }
    loadBacktestHistory()
    return
  }
  // 仍在执行：恢复进度卡并继续轮询，结束后照常展示结果
  pollAborted = false
  backtesting.value = true
  backtestElapsed.value = Math.max(0, Math.round((Date.now() - (session.startedAt || Date.now())) / 1000))
  backtestTask.value = {
    strategyType: session.strategyType,
    startDate: session.startDate,
    endDate: session.endDate,
    status: 'queued',
    progress: 0,
    done: 0,
    total: 0,
  }
  elapsedTimer = window.setInterval(() => { backtestElapsed.value += 1 }, 1000)
  try {
    const btId = await waitBacktestTask(session.taskId)
    saveBacktestSession({ ...session, taskId: undefined, btId })
    try {
      applyBacktestResult(await strategyApi.getBacktestDetail(btId), false)
    } catch {
      // 同上，历史列表可兜底
    }
    loadBacktestHistory()
    backtestTask.value.status = 'done'
    backtestTask.value.progress = 100
    await new Promise(resolve => setTimeout(resolve, 600))
  } catch (e: any) {
    if (pollAborted) return
    if (!e?.config && e?.message) ElMessage.error(e.message)
    loadBacktestHistory()
  } finally {
    if (elapsedTimer !== undefined) {
      window.clearInterval(elapsedTimer)
      elapsedTimer = undefined
    }
    backtestTask.value = null
    backtesting.value = false
  }
}

const backtestHistory = ref<any[]>([])

async function loadBacktestHistory() {
  try {
    const data = await strategyApi.getBacktestHistory()
    backtestHistory.value = data || []
  } catch {
    // 静默失败
  }
}

// Map snake_case from backend to camelCase for frontend
// scroll=false 用于切页恢复：回填结果但不打断用户当前浏览位置
function applyBacktestResult(res: any, scroll = true) {
  backtestResult.value = {
    totalReturn: res.total_return ?? 0,
    annualReturn: res.annual_return ?? 0,
    maxDrawdown: res.max_drawdown ?? 0,
    sharpeRatio: res.sharpe_ratio ?? 0,
    winRate: res.win_rate ?? 0,
    tradeCount: res.trade_count ?? 0,
    // 交易成本统计
    totalCommission: res.total_commission ?? 0,
    totalStampTax: res.total_stamp_tax ?? 0,
    totalSlippageCost: res.total_slippage_cost ?? 0,
    totalTradeCost: res.total_trade_cost ?? 0,
    tradeCountActual: res.trade_count_actual ?? 0,
    navCurve: res.nav_curve ?? [],
    positionChanges: res.position_changes ?? [],
    portfolioSnapshots: res.portfolio_snapshots ?? [],
  }
  // 滚动到回测结果区域
  if (!scroll) return
  const resultEl = document.querySelector('.backtest-result')
  if (resultEl) {
    resultEl.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }
}

async function viewBacktestDetail(btId: string) {
  try {
    applyBacktestResult(await strategyApi.getBacktestDetail(btId))
    ElMessage.success('已加载回测详情')
  } catch {
    ElMessage.error('获取回测详情失败')
  }
}

function formatTime(isoStr: string) {
  if (!isoStr) return ''
  return isoStr.replace('T', ' ').substring(0, 19)
}

function actionLabel(action: string): string {
  const map: Record<string, string> = {
    ADD: '加仓', REDUCE: '减仓', CLEAR: '清仓',
    STOP_LOSS: '止损', TAKE_PROFIT: '止盈', EMERGENCY_EXIT: '紧急清仓', BEAR_EXIT: '熊市清仓',
  }
  return map[action] || action
}

function tradeTagType(action: string): string {
  const map: Record<string, string> = {
    ADD: 'danger', REDUCE: 'warning', CLEAR: 'success',
    STOP_LOSS: 'danger', TAKE_PROFIT: 'warning', EMERGENCY_EXIT: 'danger', BEAR_EXIT: 'danger',
  }
  return map[action] || 'info'
}

function triggerLabel(trigger: string): string {
  const map: Record<string, string> = {
    rebalance: '调仓', stop_loss: '止损', emergency_exit: '紧急退出', bear_exit: '熊市清仓',
  }
  return map[trigger] || trigger
}

function formatMoney(val: number): string {
  if (val == null) return '-'
  return (val / 10000).toFixed(2) + '万'
}

const rebalanceGroups = computed(() => {
  const changes = backtestResult.value?.positionChanges
  const snapshots = backtestResult.value?.portfolioSnapshots || []
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
  // 调仓日按日期倒序：最近的调仓显示在最前面
  return Object.values(groupMap)
    .sort((a, b) => String(b.date || '').localeCompare(String(a.date || '')))
})

// 页面加载时获取回测历史，并接上可能还在跑的回测任务
loadBacktestHistory()
restoreBacktestSession()

/** 纵轴金额简写：≥1 万写 w、≥1 千写 k，否则百万级刻度把左轴撑爆（390 下只容 5-6 字符）。
 *  小数位取 2 位再去尾 0：刻度步长偏小时 1050/1100 不会都显示成 1.1k，10200/10800 也不会都是 1.1w */
function axisMoney(val: number): string {
  const abs = Math.abs(val)
  if (abs >= 10000) return Number((val / 10000).toFixed(2)) + 'w'
  if (abs >= 1000) return Number((val / 1000).toFixed(2)) + 'k'
  return String(Math.round(val))
}

const backtestChartOption = computed(() => {
  if (!backtestResult.value?.navCurve) return {}
  const data = backtestResult.value.navCurve
  const c = themeColors.value
  return {
    tooltip: {
      trigger: 'axis',
      backgroundColor: c.tooltipBg, borderColor: c.tooltipBorder, textStyle: { color: c.text },
    },
    legend: { data: ['策略净值', '基准净值'], textStyle: { color: c.textSub } },
    // containLabel 把轴标签算进边距，否则百万级金额刻度被卡片左边裁掉；
    // right 取 34（≈ 半个「2025-12-19」标签宽）保证末位日期不被右边缘裁掉
    grid: { left: 4, right: 34, top: 28, bottom: 2, containLabel: true },
    xAxis: {
      type: 'category', data: data.map((d: any) => d.date),
      axisLabel: { color: c.textSub }, axisLine: { lineStyle: { color: c.axis } },
    },
    yAxis: {
      type: 'value', scale: true,
      axisLabel: { color: c.textSub, formatter: axisMoney }, axisLine: { lineStyle: { color: c.axis } },
      splitLine: { lineStyle: { color: c.grid } },
    },
    series: [
      { name: '策略净值', type: 'line', data: data.map((d: any) => d.nav), smooth: true, lineStyle: { width: 2 }, itemStyle: { color: c.primary } },
      { name: '基准净值', type: 'line', data: data.map((d: any) => d.benchmark), smooth: true, lineStyle: { width: 2, type: 'dashed' }, itemStyle: { color: c.neutral } },
    ],
  }
})
</script>

<style lang="scss" scoped>
.strategy-card {
  position: relative;
  padding: 24px;
  background: var(--bg-surface);
  border: 1px solid var(--border-primary);
  border-radius: var(--radius-md);
  overflow: hidden;
  transition: border-color var(--dur-fast) var(--ease);
  // 顶部语义色条表达策略风险等级，主体保持统一轻量边界
  &::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 3px;
    background: var(--border-strong);
  }
  &.aggressive::before { background: var(--accent-danger); }
  &.moderate::before { background: var(--accent-warning); }
  &.conservative::before { background: var(--accent-success); }
  &:hover { border-color: var(--accent-primary); }
  .strategy-header { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; h3 { margin: 0; font-size: 17px; color: var(--text-primary); } }
  .strategy-desc { color: var(--text-tertiary); font-size: 13px; margin-bottom: 16px; line-height: 1.6; }
  .strategy-actions { display: flex; gap: 8px; margin-top: 16px; .el-button { flex: 1; } }
}
.backtest-header-right {
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
}
/* ─── 当前回测任务卡片：外框流光表示任务仍在计算 ─── */
.bt-task-card {
  position: relative;
  margin-top: 16px;
  padding: 14px 16px;
  border-radius: var(--radius-md);
  overflow: hidden;
  // 伪元素用负层级，靠 isolation 把层级限制在本卡片内
  isolation: isolate;

  // 旋转的锥形渐变打底，再用内层实色盖住中间，只留一圈流动的边
  &::before {
    content: '';
    position: absolute;
    left: 50%;
    top: 50%;
    width: 230%;
    aspect-ratio: 1;
    background: conic-gradient(from 0deg, transparent 0deg, transparent 200deg,
      var(--accent-primary) 280deg, var(--accent-warning) 320deg, transparent 360deg);
    transform: translate(-50%, -50%);
    animation: bt-task-spin 2.4s linear infinite;
    // 持续旋转交给合成层，避免每帧重绘整个渐变大图
    will-change: transform;
    z-index: -2;
  }
  &::after {
    content: '';
    position: absolute;
    inset: 1.5px;
    border-radius: calc(var(--radius-md) - 1.5px);
    background: var(--bg-surface);
    z-index: -1;
  }
  &.is-done::before {
    background: var(--accent-success);
    animation: none;
  }

  .bt-task-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    margin-bottom: 10px;

    .bt-task-title { font-size: 13px; font-weight: 600; color: var(--text-primary); }
    .bt-task-range { font-size: 11px; color: var(--text-tertiary); font-family: var(--font-mono); }
  }
  .bt-task-bar {
    position: relative;
    height: 8px;
    border-radius: 4px;
    background: var(--bg-tertiary);
    overflow: hidden;

    .bt-task-bar-fill {
      height: 100%;
      border-radius: 4px;
      background: linear-gradient(90deg, var(--accent-primary), var(--accent-warning));
      transition: width var(--dur-base) var(--ease);
    }

    // 取数阶段时长不定：条子来回流动，表示在工作但还不知道要多久
    &.is-indeterminate .bt-task-bar-fill {
      width: 35%;
      transition: none;
      animation: bt-task-flow 1.4s ease-in-out infinite;
    }
    &.is-done .bt-task-bar-fill { background: var(--accent-success); }
  }
  .bt-task-foot {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    margin-top: 8px;
    font-size: 11px;
    color: var(--text-tertiary);

    .bt-task-meta { font-family: var(--font-mono); }
  }
}

@keyframes bt-task-spin {
  from { transform: translate(-50%, -50%) rotate(0deg); }
  to { transform: translate(-50%, -50%) rotate(360deg); }
}

@keyframes bt-task-flow {
  from { transform: translateX(-100%); }
  to { transform: translateX(320%); }
}

@media (prefers-reduced-motion: reduce) {
  .bt-task-card::before { animation: none; }
  .bt-task-card .bt-task-bar.is-indeterminate .bt-task-bar-fill { animation: none; width: 100%; opacity: 0.5; }
}

.backtest-result {
  margin-top: 16px;
  .result-row { margin-top: 12px; }
  .result-item {
    text-align: center; padding: 14px;
    background: var(--bg-tertiary); border-radius: var(--radius-sm);
    span { display: block; color: var(--text-tertiary); font-size: 12px; margin-bottom: 6px; }
    strong { font-size: 20px; color: var(--text-primary); font-family: var(--font-mono); }
  }
}
.params-cell { display: flex; flex-wrap: wrap; gap: 4px; }
.backtest-chart { height: var(--chart-h-lg); margin-top: 16px; }
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

@media (max-width: 768px) {
  .strategy-card { padding: 16px; }
  .strategy-header h3 { font-size: 15px; }
  .backtest-result .result-item { padding: 10px; strong { font-size: 16px; } }
  .backtest-chart { height: var(--chart-h-md); }
}

/* ─── 手机端回测历史条目 ─── */
.m-bt-list {
  list-style: none;
  margin: 0;
  padding: 0;
}
.m-bt-row {
  padding: 8px 0;
  border-bottom: 1px solid var(--border-subtle);

  &:last-child { border-bottom: none; }
}
.m-bt-head {
  display: flex;
  align-items: center;
  gap: 8px;

  .m-bt-time { flex: 1; font-size: 10px; color: var(--text-tertiary); font-family: var(--font-mono); }
}
.m-bt-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
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
.m-bt-range,
.m-bt-params {
  margin-top: 4px;
  font-size: 10px;
  color: var(--text-tertiary);
  font-family: var(--font-mono);
}

/* ─── 手机端调仓明细：持仓快照条目 ─── */
.m-pf-list {
  list-style: none;
  margin: 8px 0;
  padding: 0;
}
.m-pf-row {
  padding: 6px 0;
  border-bottom: 1px solid var(--border-subtle);

  &:last-child { border-bottom: none; }
}
.m-pf-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;

  .m-pf-name { font-size: 12px; color: var(--text-primary); }
  .m-pf-weight { flex: none; font-size: 12px; font-family: var(--font-mono); color: var(--text-secondary); }
}
.m-pf-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 4px;
  margin-top: 4px;

  // 调仓分组底色是 bg-tertiary，格子改用 bg-surface 才能分出来
  & > div {
    display: flex;
    flex-direction: column;
    gap: 1px;
    min-width: 0;
    padding: 4px 5px;
    background: var(--bg-surface);
    border-radius: 4px;
  }

  em { font-style: normal; font-size: 10px; color: var(--text-tertiary); }
  b { font-size: 11px; font-weight: 600; font-family: var(--font-mono); }
}

@media (max-width: 480px) {
  .strategy-page { padding: 0; }
  .strategy-card { padding: 10px; border-radius: 8px; }
  .strategy-card .strategy-header { gap: 8px; margin-bottom: 8px; :deep(.el-icon) { font-size: 17px; } h3 { font-size: 13px; } }
  .strategy-card .strategy-desc { font-size: 11px; line-height: 1.5; margin-bottom: 10px; }
  .strategy-card .strategy-actions { margin-top: 10px; gap: 6px; }
  .backtest-result .result-item { padding: 7px 4px; span { font-size: 10px; margin-bottom: 3px; } strong { font-size: 13px; } }
  .backtest-chart { height: var(--chart-h-sm); margin-top: 10px; }
  .bt-task-card {
    margin-top: 10px;
    padding: 10px 12px;
    border-radius: 8px;

    &::after { border-radius: 6.5px; }
    .bt-task-head { margin-bottom: 8px; .bt-task-title { font-size: 11px; } .bt-task-range { font-size: 10px; } }
    .bt-task-foot { margin-top: 6px; font-size: 10px; }
  }

  /* 数据范围是 el-tag（高 20），采集历史数据是 el-button（高 36），并排时规格不一致。
     手机端改为卡片头纵向两行：tag 整行、按钮整行 */
  .card-header { flex-wrap: wrap; row-gap: 6px; }
  .backtest-header-right { width: 100%; flex-direction: column; align-items: stretch; gap: 6px; }
  .backtest-header-right .el-tag { font-size: 11px; height: auto; padding: 5px 8px; display: block; text-align: center; }
  .backtest-header-right .el-button { width: 100%; margin-left: 0; }

  /* el-row 的负边距在手机上会把卡片顶出屏幕，这里归零 */
  :deep(.el-row) { margin-left: 0 !important; margin-right: 0 !important; }
  :deep(.el-col) { padding-left: 0 !important; padding-right: 0 !important; }
  /* 归零 padding 后 gutter 带来的横向间隔消失，纵向间距也必须补回来，
     否则三张策略卡片首尾相接、回测结果 2×2 网格上下贴死 */
  :deep(.el-col) { margin-bottom: var(--m-gap); }
  /* 但回测结果的 2×2 指标卡是两列并排，零 padding 会让四张卡横向贴成一整块：
     上面归零只适用于铺满整行的策略卡片，这里单独把指标卡的缝补回 8px */
  .backtest-result :deep(.el-row) { margin-left: -4px !important; margin-right: -4px !important; }
  .backtest-result :deep(.el-col) { padding-left: 4px !important; padding-right: 4px !important; }

  /* 参数表单：标签上置，滑杆与数字框占满整行 */
  .strategy-card :deep(.el-form-item) { flex-direction: column; align-items: stretch; margin-bottom: var(--ctrl-row-gap); }
  .strategy-card :deep(.el-form-item__label) { width: auto !important; text-align: left; padding: 0 0 2px; height: auto; line-height: 1.4; font-size: 11px; }
  /* 单位与控件同一行：控件可伸缩，单位固定不压缩（原先 width:100% 会把单位挤到下一行） */
  .strategy-card :deep(.el-form-item__content) {
    margin-left: 0 !important;
    flex-wrap: nowrap;
    align-items: center;
    gap: 6px;
  }
  .strategy-card :deep(.el-input-number),
  .strategy-card :deep(.el-slider) {
    flex: 1 1 auto;
    width: auto;
    min-width: 0;
  }
  .strategy-card :deep(.unit) { flex: 0 0 auto; font-size: 10px; }

  .rebalance-group { padding: 8px; margin-bottom: 8px; }
  .rebalance-date-header .rebalance-date { font-size: 12px; }
  .rebalance-trades { gap: 3px; }
}
</style>
