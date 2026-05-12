<template>
  <div class="ai-analysis-panel">
    <div class="panel-header">
      <el-icon><MagicStick /></el-icon>
      <span>AI 分析</span>
      <el-tag v-if="loading" size="small" type="info">分析中...</el-tag>
      <el-tag v-else-if="analyses.length > 0" size="small" type="success">{{ analyses.length }} 条分析</el-tag>
    </div>

    <div v-if="loading" class="loading-state">
      <el-skeleton :rows="3" animated />
    </div>

    <div v-else-if="analyses.length === 0" class="empty-state">
      <el-empty description="暂无AI分析" :image-size="60" />
    </div>

    <div v-else class="analysis-list">
      <div v-for="analysis in analyses" :key="analysis.sector_code" class="analysis-card">
        <div class="card-header">
          <span class="sector-name">{{ analysis.sector_name }}</span>
          <el-tag :type="analysis.direction === 'BUY' ? 'danger' : 'success'" size="small">
            {{ analysis.direction === 'BUY' ? '买入' : '卖出' }}
          </el-tag>
          <div class="confidence">
            <span class="label">信心度</span>
            <el-progress
              :percentage="Math.round(analysis.confidence * 100)"
              :stroke-width="6"
              :color="getConfidenceColor(analysis.confidence)"
              style="width: 80px"
            />
          </div>
        </div>

        <div class="interpretation">
          {{ analysis.interpretation }}
        </div>

        <div v-if="analysis.risk_factors.length > 0" class="risk-factors">
          <div class="risk-title">
            <el-icon><Warning /></el-icon>
            <span>风险提示</span>
          </div>
          <ul>
            <li v-for="(factor, idx) in analysis.risk_factors" :key="idx">{{ factor }}</li>
          </ul>
        </div>

        <div class="suggestion">
          <el-icon><InfoFilled /></el-icon>
          <span>{{ analysis.suggestion }}</span>
        </div>
      </div>
    </div>

    <div v-if="analyses.length > 0" class="panel-footer">
      <span class="meta">模型: {{ analyses[0]?.model || '-' }} | 耗时: {{ analyses[0]?.latency_ms || 0 }}ms</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { MagicStick, Warning, InfoFilled } from '@element-plus/icons-vue'
import { aiApi } from '@/api/ai'
import type { SignalAnalysis } from '@/api/ai'

const props = defineProps<{
  strategyType: string
  signalDate?: string
}>()

const loading = ref(false)
const analyses = ref<SignalAnalysis[]>([])

async function loadAnalyses() {
  if (!props.strategyType) return
  loading.value = true
  try {
    const res = await aiApi.analyzeSignal(props.strategyType, props.signalDate)
    analyses.value = res.analyses || []
  } catch {
    analyses.value = []
  } finally {
    loading.value = false
  }
}

function getConfidenceColor(confidence: number): string {
  if (confidence >= 0.7) return '#67c23a'
  if (confidence >= 0.4) return '#e6a23c'
  return '#f56c6c'
}

watch(() => [props.strategyType, props.signalDate], loadAnalyses, { immediate: true })
</script>

<style lang="scss" scoped>
.ai-analysis-panel {
  background: var(--bg-primary);
  border-radius: var(--radius-md);
  border: 1px solid var(--border-secondary);
  box-shadow: var(--shadow-card);
  overflow: hidden;

  .panel-header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 12px 16px;
    background: linear-gradient(135deg, #637ee8 0%, #8b5cf6 100%);
    color: var(--text-inverse);
    font-weight: 600;
    font-size: 14px;
  }

  .loading-state, .empty-state {
    padding: 20px;
  }

  .analysis-list {
    padding: 12px;

    .analysis-card {
      padding: 12px;
      border: 1px solid var(--border-secondary);
      border-radius: 6px;
      margin-bottom: 10px;

      &:last-child {
        margin-bottom: 0;
      }

      .card-header {
        display: flex;
        align-items: center;
        gap: 8px;
        margin-bottom: 10px;

        .sector-name {
          font-weight: 600;
          font-size: 15px;
        }

        .confidence {
          margin-left: auto;
          display: flex;
          align-items: center;
          gap: 6px;

          .label {
            font-size: 12px;
            color: var(--text-tertiary);
          }
        }
      }

      .interpretation {
        font-size: 13px;
        color: var(--text-primary);
        line-height: 1.6;
        margin-bottom: 10px;
        padding: 8px 12px;
        background: var(--bg-tertiary);
        border-radius: 4px;
      }

      .risk-factors {
        margin-bottom: 10px;

        .risk-title {
          display: flex;
          align-items: center;
          gap: 4px;
          font-size: 13px;
          font-weight: 600;
          color: var(--accent-warning);
          margin-bottom: 6px;
        }

        ul {
          margin: 0;
          padding-left: 20px;
          font-size: 12px;
          color: var(--text-secondary);
          line-height: 1.8;
        }
      }

      .suggestion {
        display: flex;
        align-items: flex-start;
        gap: 6px;
        font-size: 12px;
        color: var(--accent-primary);
        padding: 8px 12px;
        background: var(--accent-primary-light);
        border-radius: 4px;
      }
    }
  }

  .panel-footer {
    padding: 8px 16px;
    border-top: 1px solid var(--border-secondary);
    text-align: right;

    .meta {
      font-size: 11px;
      color: var(--text-tertiary);
    }
  }
}
</style>
