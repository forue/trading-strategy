<template>
  <div class="risk-alert-panel">
    <div class="panel-header" :class="overallRiskClass">
      <el-icon><Warning /></el-icon>
      <span>风险预警</span>
      <el-tag :type="overallRiskType" size="small">{{ overallRiskLabel }}</el-tag>
    </div>

    <div v-if="loading" class="loading-state">
      <el-skeleton :rows="2" animated />
    </div>

    <div v-else-if="alerts.length === 0" class="safe-state">
      <el-icon><SuccessFilled /></el-icon>
      <span>当前无风险预警</span>
    </div>

    <div v-else class="alert-list">
      <div v-for="(alert, idx) in alerts" :key="idx" class="alert-item" :class="alert.level.toLowerCase()">
        <div class="alert-icon">
          <el-icon v-if="alert.level === 'CRITICAL'" color="var(--accent-danger)"><CircleCloseFilled /></el-icon>
          <el-icon v-else-if="alert.level === 'WARNING'" color="var(--accent-warning)"><WarningFilled /></el-icon>
          <el-icon v-else color="var(--text-tertiary)"><InfoFilled /></el-icon>
        </div>
        <div class="alert-content">
          <div class="alert-title">{{ alert.title }}</div>
          <div class="alert-desc">{{ alert.description }}</div>
          <div class="alert-suggestion">{{ alert.suggestion }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { Warning, SuccessFilled, CircleCloseFilled, WarningFilled, InfoFilled } from '@element-plus/icons-vue'
import { aiApi } from '@/api/ai'
import type { RiskAlert } from '@/api/ai'

const loading = ref(false)
const alerts = ref<RiskAlert[]>([])
const overallRisk = ref('LOW')

const overallRiskType = computed<'success' | 'warning' | 'danger' | 'info'>(() => {
  const map: Record<string, 'success' | 'warning' | 'danger' | 'info'> = {
    LOW: 'success',
    MEDIUM: 'warning',
    HIGH: 'danger',
    CRITICAL: 'danger',
  }
  return map[overallRisk.value] || 'info'
})

const overallRiskLabel = computed(() => {
  const map: Record<string, string> = { LOW: '低风险', MEDIUM: '中风险', HIGH: '高风险', CRITICAL: '极高风险' }
  return map[overallRisk.value] || '未知'
})

const overallRiskClass = computed(() => overallRisk.value.toLowerCase())

async function loadAlerts() {
  loading.value = true
  try {
    const res = await aiApi.riskCheck()
    alerts.value = res.alerts || []
    overallRisk.value = res.overall_risk || 'LOW'
  } catch {
    alerts.value = []
    overallRisk.value = 'LOW'
  } finally {
    loading.value = false
  }
}

onMounted(loadAlerts)

defineExpose({ refresh: loadAlerts })
</script>

<style lang="scss" scoped>
.risk-alert-panel {
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
    font-weight: 600;
    font-size: 16px;
    color: var(--text-primary);

    &::before {
      content: '';
      width: 2px;
      height: 14px;
      border-radius: 1px;
      background: var(--accent-primary);
      flex-shrink: 0;
    }
  }

  .safe-state {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    padding: 24px;
    color: var(--accent-success);
    font-size: 14px;
  }

  .alert-list {
    padding: 0;

    .alert-item {
      display: flex;
      gap: 10px;
      padding: 12px 14px;
      border: 1px solid var(--border-primary);
      border-radius: var(--radius-sm);
      margin-bottom: 10px;
      background: var(--bg-surface);

      &:last-child {
        margin-bottom: 0;
      }

      &.critical { border-left: 3px solid var(--accent-danger); }
      &.warning { border-left: 3px solid var(--accent-warning); }
      &.info { border-left: 3px solid var(--text-tertiary); }

      .alert-icon {
        flex-shrink: 0;
        padding-top: 2px;
      }

      .alert-content {
        flex: 1;

        .alert-title {
          font-weight: 600;
          font-size: 13px;
          margin-bottom: 4px;
        }
        .alert-desc {
          font-size: 12px;
          color: var(--text-secondary);
          margin-bottom: 4px;
        }
        .alert-suggestion {
          font-size: 12px;
          color: var(--accent-primary);
        }
      }
    }
  }
}

/* 手机端：面板内边距与标题压到 10px 栅格，告警条目改为紧凑三行 */
@media (max-width: 480px) {
  .risk-alert-panel {
    padding: 10px;

    .panel-header {
      gap: 6px;
      padding-bottom: 8px;
      margin-bottom: 8px;
      font-size: 12px;

      &::before { height: 11px; }
    }

    .safe-state {
      padding: 14px;
      font-size: 11px;
    }

    .alert-list .alert-item {
      gap: 8px;
      padding: 8px 9px;
      margin-bottom: 6px;

      .alert-icon { font-size: 13px; }

      .alert-content {
        .alert-title { font-size: 11px; margin-bottom: 2px; }
        .alert-desc,
        .alert-suggestion { font-size: 10px; line-height: 1.5; margin-bottom: 2px; }
      }
    }
  }
}
</style>
