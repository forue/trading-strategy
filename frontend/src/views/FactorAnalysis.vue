<template>
  <div class="factor-analysis">
    <div class="page-card">
      <div class="card-header">
        <span class="card-title">因子分析</span>
        <div class="header-actions">
          <el-select v-model="selectedSector" size="small" style="width: 200px" placeholder="选择板块" filterable>
            <el-option v-for="s in sectors" :key="s.sector_code" :label="s.sector_name" :value="s.sector_code" />
          </el-select>
          <el-select v-model="selectedStrategy" size="small" style="width: 100px">
            <el-option label="激进" value="AGGRESSIVE" />
            <el-option label="稳健" value="MODERATE" />
            <el-option label="保守" value="CONSERVATIVE" />
          </el-select>
          <el-button type="primary" size="small" @click="analyzeSector" :loading="loading" :disabled="!selectedSector">
            分析
          </el-button>
        </div>
      </div>

      <div v-if="loading" style="padding: 40px; text-align: center">
        <el-skeleton :rows="5" animated />
      </div>

      <div v-else-if="result">
        <!-- 数据日期提示 -->
        <el-alert v-if="result.date" type="info" :closable="false" show-icon style="margin-bottom: 16px">
          <template #title>
            数据日期: {{ result.date }} | 板块: {{ result.sector_name }} ({{ result.sector_code }})
          </template>
        </el-alert>

        <el-alert
          v-if="result.engine_fallback"
          type="warning"
          :closable="false"
          show-icon
          style="margin-bottom: 16px"
          title="当前使用简化评分回退（因子引擎异常或数据不完整）。综合分仍可用，因子明细可能不完整。"
        />

        <el-alert
          v-if="result.note"
          type="info"
          :closable="false"
          show-icon
          style="margin-bottom: 16px"
          :title="result.note"
        />

        <!-- 综合评分 + 类别得分 -->
        <div class="score-section">
          <div class="score-meta">
            <span>绝对综合分: <strong>{{ absCompositeDisplay }}</strong></span>
            <span class="sep">|</span>
            <span>截面排名综合分: <strong>{{ rankCompositeDisplay }}</strong></span>
            <span class="hint">（单板块分析不产生全市场截面分，故多为「—」）</span>
          </div>
          <div class="score-grid">
            <div class="score-box main-score">
              <div class="score-value" :style="{ color: getScoreColor(result.composite_score) }">
                {{ result.composite_score?.toFixed(2) }}
              </div>
              <div class="score-label">综合评分（与后端 composite_score 一致）</div>
            </div>
            <div v-for="cat in categoryList" :key="cat.key" class="score-box">
              <div class="score-value" :style="{ color: getScoreColor(cat.score) }">
                {{ cat.score?.toFixed(2) }}
              </div>
              <div class="score-label">{{ cat.label }}</div>
            </div>
          </div>
        </div>

        <!-- 因子详情表格 -->
        <div class="card-header">
          <span class="card-title">因子详情</span>
        </div>
        <el-table :data="factorList" stripe size="small" style="margin-bottom: 16px">
          <el-table-column prop="name" label="因子" width="160">
            <template #default="{ row }">
              <el-tooltip :content="getFactorDescription(row.name)" placement="top" :show-after="300">
                <span style="font-weight: 500; cursor: help; border-bottom: 1px dashed #c0c4cc">{{ getFactorLabel(row.name) }}</span>
              </el-tooltip>
            </template>
          </el-table-column>
          <el-table-column prop="category" label="类别" width="80" align="center">
            <template #default="{ row }">
              <el-tag size="small" :type="getCategoryType(row.category)">{{ getCategoryLabel(row.category) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="score" label="得分" width="80" align="center">
            <template #default="{ row }">
              <span :style="{ color: getScoreColor(row.score), fontWeight: 600 }">{{ row.score?.toFixed(2) }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="weight" label="权重" width="80" align="center">
            <template #default="{ row }">{{ (row.weight * 100).toFixed(0) }}%</template>
          </el-table-column>
          <el-table-column prop="confidence" label="置信度" width="120" align="center">
            <template #default="{ row }">
              <el-progress :percentage="Math.round(row.confidence * 100)" :stroke-width="6"
                :color="row.confidence >= 0.7 ? '#67c23a' : row.confidence >= 0.4 ? '#e6a23c' : '#f56c6c'"
                style="width: 80px" />
            </template>
          </el-table-column>
          <el-table-column prop="raw_value" label="原始值" width="100" align="right">
            <template #default="{ row }">{{ formatRawValue(row) }}</template>
          </el-table-column>
          <el-table-column label="计算详情">
            <template #default="{ row }">
              <span style="font-size: 12px; color: #909399">{{ formatDetail(row) }}</span>
            </template>
          </el-table-column>
        </el-table>

        <!-- 权重配置 -->
        <div class="card-header" style="margin-top: 16px">
          <span class="card-title">策略类别权重（展示）</span>
          <el-tag size="small" type="info">{{ selectedStrategy === 'AGGRESSIVE' ? '激进' : selectedStrategy === 'CONSERVATIVE' ? '保守' : '稳健' }}</el-tag>
          <span class="weight-hint">与本次分析接口返回的 `strategy_weights` 同步；调整后仅本地预览，未调用保存接口。</span>
        </div>

        <el-row :gutter="12">
          <el-col :span="4" v-for="(weight, key) in strategyWeights" :key="key">
            <div class="weight-item">
              <div class="weight-label">{{ getCategoryLabel(String(key)) }}</div>
              <el-slider v-model="strategyWeights[key]" :min="0" :max="100" :step="5" size="small" />
              <div class="weight-value">{{ strategyWeights[key] }}%</div>
            </div>
          </el-col>
        </el-row>
      </div>

      <el-empty v-else description="选择板块并点击分析" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  strategyApi,
  type FactorAnalyzeResult,
  type FactorResultItem,
  type StrategyWeightsPayload,
} from '@/api/strategy'

const sectors = ref<{ sector_code: string; sector_name: string }[]>([])
const selectedSector = ref('')
const selectedStrategy = ref('MODERATE')
const loading = ref(false)
const result = ref<FactorAnalyzeResult | null>(null)

/** 与后端 `combiner/weighted.py` DEFAULT_WEIGHTS 一致的滑块初值（百分比） */
const DEFAULT_WEIGHTS_SLIDER: Record<
  'AGGRESSIVE' | 'MODERATE' | 'CONSERVATIVE',
  Record<'capital_flow' | 'momentum' | 'technical' | 'sentiment' | 'valuation' | 'rotation', number>
> = {
  AGGRESSIVE: { capital_flow: 48, momentum: 33, technical: 10, sentiment: 5, valuation: 0, rotation: 4 },
  MODERATE: { capital_flow: 33, momentum: 23, technical: 24, sentiment: 10, valuation: 5, rotation: 5 },
  CONSERVATIVE: { capital_flow: 29, momentum: 14, technical: 24, sentiment: 14, valuation: 14, rotation: 5 },
}

const strategyWeights = reactive({ ...DEFAULT_WEIGHTS_SLIDER.MODERATE })

const categoryList = computed(() => {
  if (!result.value?.category_scores) return []
  const labels: Record<string, string> = {
    capital_flow: '资金流',
    momentum: '动量',
    technical: '技术',
    sentiment: '情绪',
    valuation: '估值',
    rotation: '轮动',
  }
  return Object.entries(result.value.category_scores).map(([key, val]) => ({
    key,
    label: labels[key] || key,
    score: val.score,
  }))
})

const factorList = computed<FactorResultItem[]>(() => result.value?.factors || [])

const absCompositeDisplay = computed(() => {
  const r = result.value
  if (!r) return '—'
  const v = r.abs_composite_score ?? r.composite_score
  return typeof v === 'number' ? v.toFixed(2) : '—'
})

const rankCompositeDisplay = computed(() => {
  const v = result.value?.rank_composite_score
  if (v === null || v === undefined) return '—'
  return typeof v === 'number' ? v.toFixed(2) : '—'
})

function syncStrategyWeightsFromApi(sw?: StrategyWeightsPayload) {
  if (!sw) return
  const keys = ['capital_flow', 'momentum', 'technical', 'sentiment', 'valuation', 'rotation'] as const
  for (const k of keys) {
    const n = sw[k]
    if (typeof n === 'number' && !Number.isNaN(n)) {
      strategyWeights[k] = Math.round(n * 100)
    }
  }
}

async function loadSectors() {
  try {
    sectors.value = await strategyApi.getReplaySectors()
  } catch {
    sectors.value = []
  }
}

async function analyzeSector() {
  if (!selectedSector.value) return
  loading.value = true
  try {
    const data = await strategyApi.analyzeFactors({
      sector_code: selectedSector.value,
      strategy_type: selectedStrategy.value,
    })
    result.value = data
    syncStrategyWeightsFromApi(data.strategy_weights)
  } catch (e: any) {
    ElMessage.error('分析失败: ' + (e?.message || '未知错误'))
    result.value = null
  } finally {
    loading.value = false
  }
}

function getScoreColor(score: number): string {
  if (score >= 7) return '#67c23a'
  if (score >= 4) return '#e6a23c'
  return '#f56c6c'
}

function getCategoryType(category: string): string {
  const map: Record<string, string> = {
    capital_flow: 'danger',
    momentum: 'warning',
    technical: 'primary',
    sentiment: 'info',
    valuation: 'success',
    rotation: '',
  }
  return map[category] || ''
}

function getCategoryLabel(category: string): string {
  const map: Record<string, string> = {
    capital_flow: '资金流',
    momentum: '动量',
    technical: '技术',
    sentiment: '情绪',
    valuation: '估值',
    rotation: '轮动',
  }
  return map[category] || category
}

const factorLabels: Record<string, string> = {
  main_flow: '主力净流入',
  north_flow: '北向资金',
  price_momentum: '价格动量',
  relative_strength: '相对强弱',
  rsi_14: 'RSI强弱指标',
  macd: 'MACD趋势',
  bollinger: '布林带位置',
  kdj: 'KDJ随机指标',
  volume_ratio: '量比',
  volatility: '波动率',
  market_breadth: '市场广度',
  pe_percentile: 'PE估值分位',
  pb_percentile: 'PB估值分位',
  persistence: '板块持续性',
  trend_consistency: '趋势一致性',
}

const factorDescriptions: Record<string, string> = {
  main_flow: '主力资金净流入强度，反映机构资金对板块的看好程度。正值越大表示资金流入越多。',
  north_flow: '北向资金净流入，反映外资对板块的偏好。正值表示外资加仓。',
  price_momentum: '近5-10日价格变动趋势，动量越强表示板块上涨动能越大。',
  relative_strength: '板块涨幅相对市场平均的超额收益，正值表示跑赢大盘。',
  rsi_14: '14日相对强弱指标(0-100)。<30超卖，>70超买。用于判断板块是否过度涨跌。',
  macd: '指数平滑异同移动平均线，判断趋势方向。DIF>DEA为多头，金叉为买入信号。',
  bollinger: '价格在布林带中的位置(0-1)。<0.2偏低，>0.8偏高。用于判断价格相对位置。',
  kdj: '随机指标，衡量收盘价在价格区间中的位置。<20超卖，>80超买。',
  volume_ratio: '当日成交量与近5日均量的比值。>1.5放量，<0.7缩量。放量配合涨跌判断趋势。',
  volatility: '20日历史波动率，衡量价格波动幅度。低波动更稳健，高波动风险大但机会多。',
  market_breadth: '上涨板块占总板块的比例。>0.7市场强势，<0.3市场弱势。',
  pe_percentile: '市盈率在历史中的百分位。低分位表示估值便宜，适合价值投资。',
  pb_percentile: '市净率在历史中的百分位。低分位表示估值便宜，适合保守投资。',
  persistence:
    '近若干交易日中，在全市场截面涨幅排名进入前 K 的天数占比（需多板块历史对齐）；无截面数据时退化为正收益日占比。',
  trend_consistency: '板块涨跌方向的一致性。高一致性表示趋势明确。',
}

function getFactorLabel(name: string): string {
  return factorLabels[name] || name
}

function getFactorDescription(name: string): string {
  return factorDescriptions[name] || ''
}

function formatRawValue(factor: FactorResultItem): string {
  const v = factor.raw_value
  if (factor.name.includes('flow')) return `${(v / 1e8).toFixed(2)}亿`
  if (factor.name.includes('rsi') || factor.name.includes('kdj')) return v.toFixed(1)
  if (factor.name.includes('bollinger')) return (v * 100).toFixed(1) + '%'
  if (factor.name.includes('volatility')) return (v * 100).toFixed(1) + '%'
  if (factor.name.includes('momentum') || factor.name.includes('strength')) return v.toFixed(2) + '%'
  return typeof v === 'number' ? v.toFixed(2) : String(v)
}

function formatDetail(factor: FactorResultItem): string {
  const d = factor.detail
  if (!d) return ''
  return Object.entries(d)
    .filter(([k]) => !k.startsWith('_'))
    .map(([k, v]) => `${k}=${typeof v === 'number' ? v.toFixed?.(2) ?? v : v}`)
    .join(', ')
}

watch(selectedStrategy, () => {
  const st = selectedStrategy.value as keyof typeof DEFAULT_WEIGHTS_SLIDER
  Object.assign(strategyWeights, DEFAULT_WEIGHTS_SLIDER[st] || DEFAULT_WEIGHTS_SLIDER.MODERATE)
})

loadSectors()
</script>

<style lang="scss" scoped>
.factor-analysis {
  .card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 12px;
    .card-title { font-size: 15px; font-weight: 600; }
    .header-actions { display: flex; gap: 8px; align-items: center; }
  }

  .score-section {
    margin-bottom: 24px;
  }

  .score-meta {
    font-size: 13px;
    color: #606266;
    margin-bottom: 12px;
    .sep {
      margin: 0 8px;
      color: #dcdfe6;
    }
    .hint {
      margin-left: 8px;
      color: #909399;
      font-size: 12px;
    }
  }

  .weight-hint {
    font-size: 12px;
    color: #909399;
    margin-left: 8px;
  }

  .score-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
    gap: 12px;
  }

  .score-box {
    text-align: center;
    padding: 16px;
    background: #f5f7fa;
    border-radius: 8px;
    border: 1px solid #ebeef5;
    .score-value { font-size: 24px; font-weight: bold; }
    .score-label { font-size: 12px; color: #909399; margin-top: 6px; }
    &.main-score {
      background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
      border: none;
      .score-value { color: #fff !important; font-size: 28px; }
      .score-label { color: rgba(255,255,255,0.8); }
    }
  }

  .weight-item {
    text-align: center;
    padding: 10px 6px;
    background: #f5f7fa;
    border-radius: 6px;
    border: 1px solid #ebeef5;
    .weight-label { font-size: 12px; color: #606266; margin-bottom: 6px; }
    .weight-value { font-size: 13px; font-weight: 600; margin-top: 4px; }
  }
}
</style>
