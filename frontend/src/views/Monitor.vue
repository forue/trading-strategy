<template>
  <div class="monitor-page">
    <el-row :gutter="20">
      <!-- 服务健康检查 -->
      <el-col :span="24">
        <div class="page-card">
          <div class="card-header">
            <span class="card-title">服务健康检查</span>
            <el-button size="small" @click="refreshAll" :loading="refreshing">刷新</el-button>
          </div>
          <div class="health-grid">
            <div v-for="check in healthChecks" :key="check.name" class="health-item" :class="check.status">
              <el-icon :size="24">
                <component :is="check.status === 'healthy' ? 'CircleCheck' : check.status === 'unhealthy' ? 'CircleClose' : 'Warning'" />
              </el-icon>
              <div class="health-info">
                <div class="health-name">{{ check.name }}</div>
                <div class="health-detail">{{ check.detail }}</div>
              </div>
            </div>
          </div>
        </div>
      </el-col>
    </el-row>

    <!-- 系统日志 -->
    <div class="page-card page-section">
      <div class="card-header">
        <span class="card-title">系统日志</span>
        <div class="log-header-controls">
          <el-select v-model="logService" size="small" class="log-service-select" @change="fetchLogs">
            <el-option label="全部服务" value="" />
            <el-option label="策略引擎" value="backend-strategy" />
            <el-option label="数据采集" value="backend-data-collector" />
            <el-option label="信号通知" value="backend-signal" />
            <el-option label="AI 决策" value="backend-ai-decision" />
            <el-option label="任务调度" value="backend-scheduler" />
          </el-select>
          <el-select v-model="logLevel" size="small" class="log-level-select" @change="fetchLogs">
            <el-option label="全部等级" value="" />
            <el-option label="DEBUG" value="debug" />
            <el-option label="INFO" value="info" />
            <el-option label="WARNING" value="warning" />
            <el-option label="ERROR" value="error" />
          </el-select>
          <el-button size="small" @click="fetchLogs" :loading="logsLoading">刷新日志</el-button>
        </div>
      </div>
      <div class="log-container">
        <div v-if="logsLoading && logs.length === 0" style="color: #909399; text-align: center; padding: 20px">
          加载日志中...
        </div>
        <div v-else-if="logs.length === 0" style="color: #909399; text-align: center; padding: 20px">
          暂无日志
        </div>
        <div v-for="(log, idx) in filteredLogs" :key="idx" class="log-line" :class="log.level">
          <span class="log-time">{{ log.time }}</span>
          <el-tag :type="logLevelMap[log.level]" size="small" style="margin: 0 8px">{{ log.level.toUpperCase() }}</el-tag>
          <span class="log-service">[{{ serviceNameMap[log.service] || log.service }}]</span>
          <span class="log-message">{{ log.message }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'

const refreshing = ref(false)
const logsLoading = ref(false)
const logService = ref('')
const logLevel = ref('')

interface HealthCheck {
  name: string
  status: 'healthy' | 'unhealthy' | 'warning'
  detail: string
}

interface LogEntry {
  time: string
  level: string
  service: string
  message: string
}

const healthChecks = ref<HealthCheck[]>([
  { name: 'PostgreSQL', status: 'warning', detail: '检查中...' },
  { name: 'Redis', status: 'warning', detail: '检查中...' },
  { name: 'InfluxDB', status: 'warning', detail: '检查中...' },
  { name: '策略引擎', status: 'warning', detail: '检查中...' },
  { name: '数据采集', status: 'warning', detail: '检查中...' },
  { name: '信号通知', status: 'warning', detail: '检查中...' },
  { name: 'AI 决策', status: 'warning', detail: '检查中...' },
  { name: '任务调度', status: 'warning', detail: '检查中...' },
])

const logLevelMap: Record<string, string> = { info: 'info', warn: 'warning', error: 'danger', debug: '' }

const serviceNameMap: Record<string, string> = {
  'backend-strategy': '策略引擎',
  'backend-data-collector': '数据采集',
  'backend-signal': '信号通知',
  'backend-ai-decision': 'AI决策',
  'backend-scheduler': '任务调度',
  'backend-auth': '认证中心',
  'backend-fund': '资金管理',
}

const logs = ref<LogEntry[]>([])

const filteredLogs = computed(() => logs.value)

async function checkHealth(url: string, name: string): Promise<HealthCheck> {
  try {
    const start = Date.now()
    const resp = await fetch(url, { signal: AbortSignal.timeout(5000) })
    const elapsed = Date.now() - start
    if (resp.ok) {
      return { name, status: 'healthy', detail: `HTTP ${resp.status}, 响应 ${elapsed}ms` }
    }
    return { name, status: 'unhealthy', detail: `HTTP ${resp.status}` }
  } catch {
    return { name, status: 'unhealthy', detail: '连接失败' }
  }
}

async function refreshHealthChecks() {
  const checks = await Promise.all([
    checkHealth('/api/strategy/database/status', 'PostgreSQL / Redis / InfluxDB'),
    checkHealth('/api/strategy/health', '策略引擎'),
    checkHealth('/api/data/health', '数据采集'),
    checkHealth('/api/signals/health', '信号通知'),
    checkHealth('/api/ai/health', 'AI 决策'),
    checkHealth('/api/scheduler/health', '任务调度'),
  ])
  healthChecks.value = checks
}

async function fetchLogs() {
  logsLoading.value = true
  try {
    const params = new URLSearchParams({ lines: '100' })
    if (logService.value) params.set('service', logService.value)
    if (logLevel.value) params.set('level', logLevel.value)
    const url = `/api/scheduler/logs?${params}`
    const resp = await fetch(url, { signal: AbortSignal.timeout(10000) })
    if (resp.ok) {
      const data = await resp.json()
      logs.value = data.data || []
    }
  } catch {
    // 忽略错误
  } finally {
    logsLoading.value = false
  }
}

async function refreshAll() {
  refreshing.value = true
  await Promise.all([refreshHealthChecks(), fetchLogs()])
  refreshing.value = false
}

onMounted(() => {
  refreshAll()
})
</script>

<style lang="scss" scoped>
.health-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
.health-item {
  display: flex; align-items: center; gap: 12px; padding: 12px;
  border-radius: var(--radius-sm); background: var(--bg-tertiary);
  border-left: 3px solid var(--text-tertiary);
  transition: background var(--transition-base);
  &.healthy { border-left-color: var(--accent-success); }
  &.unhealthy { border-left-color: var(--accent-danger); }
  &.warning { border-left-color: var(--accent-warning); }
  .health-info {
    .health-name { font-weight: 500; font-size: 14px; color: var(--text-primary); }
    .health-detail { color: var(--text-tertiary); font-size: 12px; margin-top: 4px; }
  }
}
.log-header-controls {
  display: flex; gap: 8px; align-items: center; flex-wrap: wrap;
}
.log-service-select { width: 140px; max-width: 100%; }
.log-level-select { width: 100px; max-width: 100%; }
.log-container {
  background: #12141a; border-radius: var(--radius-sm); padding: 16px;
  max-height: 500px; overflow-y: auto;
  font-family: var(--font-mono); font-size: 13px;
}
.log-line {
  padding: 4px 0; color: #d4d4d4; display: flex; align-items: center;
  flex-wrap: wrap;
  &.warn { color: var(--accent-warning); }
  &.error { color: var(--accent-danger); }
  &.debug { color: var(--text-tertiary); }
  .log-time { color: #6a9955; min-width: 160px; flex-shrink: 0; }
  .log-service { color: #569cd6; min-width: 120px; flex-shrink: 0; }
  .log-message { flex: 1; word-break: break-all; min-width: 0; }
}
@media (max-width: 768px) {
  .health-grid { grid-template-columns: 1fr; }
  .log-service-select,
  .log-level-select { width: 100%; }
}

@media (max-width: 480px) {
  .log-time { min-width: 100px !important; font-size: 11px; }
  .log-service { min-width: 70px !important; font-size: 11px; }
  .log-container { padding: 8px; font-size: 11px; }
  .log-line { gap: 4px; }
  .log-message { flex-basis: 100%; margin-top: 2px; }
}
</style>
