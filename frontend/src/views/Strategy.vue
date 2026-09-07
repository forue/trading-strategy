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
              <span style="margin-left: 8px; color: var(--text-tertiary); font-size: 12px">‰ (千分之)</span>
            </el-form-item>
            <el-form-item label="印花税率">
              <el-input-number v-model="strategy.params.stamp_tax_rate_pct" :min="0.1" :max="5" :step="0.1" :precision="2" />
              <span style="margin-left: 8px; color: var(--text-tertiary); font-size: 12px">‰ (千分之)</span>
            </el-form-item>
            <el-form-item label="滑点费率">
              <el-input-number v-model="strategy.params.slippage_rate_pct" :min="0.1" :max="5" :step="0.1" :precision="2" />
              <span style="margin-left: 8px; color: var(--text-tertiary); font-size: 12px">‰ (千分之)</span>
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

        <!-- 调仓明细 -->
        <div v-if="rebalanceGroups.length" style="margin-top: 16px">
          <div class="card-header" style="margin-bottom: 8px">
            <span style="font-weight: 600">调仓明细</span>
            <el-tag size="small">{{ rebalanceGroups.length }} 个调仓日</el-tag>
          </div>
          <div v-for="group in rebalanceGroups" :key="group.date" class="rebalance-group">
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
                  <template #default="{ row }">{{ formatMoney(row.amount) }}</template>
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
                :type="tradeTagType(t.action)" style="margin: 2px">
                {{ t.sector_name || t.sector_code }} {{ actionLabel(t.action) }}
                <span v-if="t.amount > 0">{{ formatMoney(t.amount) }}</span>
                <span v-if="t.cost > 0" style="opacity:0.7"> (费{{ t.cost.toFixed(1) }})</span>
              </el-tag>
            </div>
            <div v-if="group.trades.length && group.trades[0].reason" class="rebalance-reason" style="color: #909399; font-size: 12px; margin-top: 4px">
              {{ group.trades[0].reason }}
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 回测历史 -->
    <div class="page-card page-section">
      <div class="card-header">
        <span class="card-title">回测历史</span>
        <el-button size="small" @click="loadBacktestHistory">刷新</el-button>
      </div>
      <div v-if="backtestHistory.length > 0" class="responsive-table">
        <el-table :data="backtestHistory" stripe size="small">
        <el-table-column prop="created_at" label="时间" width="180">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column prop="strategy_type" label="策略" width="100">
          <template #default="{ row }">
            <el-tag :type="row.strategy_type === 'AGGRESSIVE' ? 'danger' : row.strategy_type === 'MODERATE' ? 'warning' : 'success'" size="small">
              {{ row.strategy_type === 'AGGRESSIVE' ? '激进' : row.strategy_type === 'MODERATE' ? '稳健' : '保守' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="区间" width="200">
          <template #default="{ row }">{{ row.start_date }} ~ {{ row.end_date }}</template>
        </el-table-column>
        <el-table-column label="总收益率" width="120">
          <template #default="{ row }">
            <span :style="{ color: row.total_return >= 0 ? '#67c23a' : '#f56c6c' }">
              {{ (row.total_return * 100).toFixed(2) }}%
            </span>
          </template>
        </el-table-column>
        <el-table-column label="年化收益" width="120">
          <template #default="{ row }">
            <span :style="{ color: row.annual_return >= 0 ? '#67c23a' : '#f56c6c' }">
              {{ (row.annual_return * 100).toFixed(2) }}%
            </span>
          </template>
        </el-table-column>
        <el-table-column label="最大回撤" width="120">
          <template #default="{ row }">{{ (row.max_drawdown * 100).toFixed(2) }}%</template>
        </el-table-column>
        <el-table-column label="夏普" width="80">
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
            <span v-else style="color: #c0c4cc">默认参数</span>
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
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { ElMessage, ElMessageBox } from 'element-plus'
import { strategyApi } from '@/api/strategy'
import dayjs from 'dayjs'

use([LineChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

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

async function runBacktest() {
  backtesting.value = true
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

    const res = await strategyApi.runBacktest({
      strategyType: backtestForm.strategyType,
      startDate: backtestForm.startDate,
      endDate: backtestForm.endDate,
      initialCapital: backtestForm.initialCapital * 10000,
      strategyParams,
    })
    // Map snake_case from backend to camelCase for frontend
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
    // 刷新回测历史
    loadBacktestHistory()
  } catch {
    ElMessage.error('回测失败')
  } finally {
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

async function viewBacktestDetail(btId: string) {
  try {
    const res = await strategyApi.getBacktestDetail(btId)
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
    const resultEl = document.querySelector('.backtest-result')
    if (resultEl) {
      resultEl.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
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
  return Object.values(groupMap)
})

// 页面加载时获取回测历史
loadBacktestHistory()

const backtestChartOption = computed(() => {
  if (!backtestResult.value?.navCurve) return {}
  const data = backtestResult.value.navCurve
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['策略净值', '基准净值'] },
    xAxis: { type: 'category', data: data.map((d: any) => d.date) },
    yAxis: { type: 'value', scale: true },
    series: [
      { name: '策略净值', type: 'line', data: data.map((d: any) => d.nav), smooth: true, lineStyle: { width: 2 }, itemStyle: { color: '#409eff' } },
      { name: '基准净值', type: 'line', data: data.map((d: any) => d.benchmark), smooth: true, lineStyle: { width: 2, type: 'dashed' }, itemStyle: { color: '#909399' } },
    ],
  }
})
</script>

<style lang="scss" scoped>
.strategy-card {
  background: var(--bg-secondary); border-radius: var(--radius-lg); padding: 24px;
  box-shadow: var(--shadow-sm); border: 1px solid var(--border-secondary);
  border-top: 4px solid var(--border-primary);
  transition: all var(--transition-base);
  &.aggressive { border-top-color: var(--accent-danger); }
  &.moderate { border-top-color: var(--accent-warning); }
  &.conservative { border-top-color: var(--accent-success); }
  &:hover { box-shadow: var(--shadow-card); }
  .strategy-header { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; h3 { margin: 0; font-size: 17px; color: var(--text-primary); } }
  .strategy-desc { color: var(--text-tertiary); font-size: 13px; margin-bottom: 16px; line-height: 1.6; }
  .strategy-actions { display: flex; gap: 8px; margin-top: 16px; .el-button { flex: 1; } }
}
.backtest-header-right {
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
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
.backtest-chart { height: 350px; margin-top: 16px; }
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
  .backtest-chart { height: 280px; }
}

@media (max-width: 480px) {
  .strategy-card { padding: 12px; }
  .backtest-result .result-item { padding: 8px; strong { font-size: 14px; } span { font-size: 11px; } }
  .backtest-chart { height: 220px; }
  .backtest-header-right { width: 100%; }
  .backtest-header-right .el-tag { font-size: 11px; }
}
</style>
