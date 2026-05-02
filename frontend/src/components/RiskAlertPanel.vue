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
          <el-icon v-if="alert.level === 'CRITICAL'" color="#f56c6c"><CircleCloseFilled /></el-icon>
          <el-icon v-else-if="alert.level === 'WARNING'" color="#e6a23c"><WarningFilled /></el-icon>
          <el-icon v-else color="#909399"><InfoFilled /></el-icon>
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

const overallRiskType = computed(() => {
  const map: Record<string, string> = { LOW: 'success', MEDIUM: 'warning', HIGH: 'danger', CRITICAL: 'danger' }
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
  background: #fff;
  border-radius: 8px;
  border: 1px solid #e4e7ed;
  overflow: hidden;

  .panel-header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 12px 16px;
    font-weight: 600;
    font-size: 14px;
    background: #f5f7fa;

    &.high, &.critical {
      background: linear-gradient(135deg, #f56c6c 0%, #e6a23c 100%);
      color: #fff;
    }
    &.medium {
      background: linear-gradient(135deg, #e6a23c 0%, #f9ae3d 100%);
      color: #fff;
    }
    &.low {
      background: linear-gradient(135deg, #67c23a 0%, #95d475 100%);
      color: #fff;
    }
  }

  .safe-state {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    padding: 24px;
    color: #67c23a;
    font-size: 14px;
  }

  .alert-list {
    padding: 12px;

    .alert-item {
      display: flex;
      gap: 10px;
      padding: 10px 12px;
      border-radius: 6px;
      margin-bottom: 8px;

      &:last-child {
        margin-bottom: 0;
      }

      &.critical {
        background: #fef0f0;
        border-left: 3px solid #f56c6c;
      }
      &.warning {
        background: #fdf6ec;
        border-left: 3px solid #e6a23c;
      }
      &.info {
        background: #f4f4f5;
        border-left: 3px solid #909399;
      }

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
          color: #606266;
          margin-bottom: 4px;
        }
        .alert-suggestion {
          font-size: 12px;
          color: #409eff;
        }
      }
    }
  }
}
</style>
