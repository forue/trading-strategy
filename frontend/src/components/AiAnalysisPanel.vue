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
  align-self: start;
  background: var(--bg-surface);
  border: 1px solid var(--border-primary);
  border-radius: var(--radius-md);
  padding: 20px;
  overflow: hidden;

  .panel-header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 0 0 16px;
    margin-bottom: 16px;
    border-bottom: 1px solid var(--border-subtle);
    color: var(--text-primary);
    font-weight: 600;
    font-size: 16px;

    &::before {
      content: '';
      width: 2px;
      height: 14px;
      border-radius: 1px;
      background: var(--accent-primary);
      flex-shrink: 0;
    }
  }

  .loading-state, .empty-state {
    padding: 20px;
  }

  .analysis-list {
    padding: 0;

    .analysis-card {
      padding: 16px 0;
      border-bottom: 1px solid var(--border-primary);
      margin-bottom: 0;

      &:last-child {
        border-bottom: none;
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

      @media (max-width: 480px) {
        .card-header { flex-wrap: wrap; }
        .confidence { margin-left: 0; }
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

/* 手机端：面板与卡片内边距压到 10px，正文 11px、辅助 10px */
@media (max-width: 480px) {
  .ai-analysis-panel {
    padding: 10px;

    .panel-header {
      gap: 6px;
      padding-bottom: 8px;
      margin-bottom: 8px;
      font-size: 12px;

      &::before { height: 11px; }
    }

    .loading-state,
    .empty-state { padding: 10px; }

    .analysis-list .analysis-card {
      padding: 9px 0;

      .card-header {
        gap: 6px;
        margin-bottom: 6px;

        .sector-name { font-size: 12px; }
        .confidence .label { font-size: 10px; }
      }

      .interpretation {
        font-size: 11px;
        line-height: 1.55;
        padding: 6px 8px;
        margin-bottom: 7px;
      }

      .risk-factors {
        margin-bottom: 7px;

        .risk-title { font-size: 11px; margin-bottom: 4px; }
        ul { padding-left: 16px; font-size: 10px; line-height: 1.7; }
      }

      .suggestion {
        gap: 5px;
        padding: 6px 8px;
        font-size: 10px;
        line-height: 1.5;
      }
    }

    .panel-footer {
      padding: 6px 8px;

      .meta { font-size: 10px; }
    }
  }
}
</style>
