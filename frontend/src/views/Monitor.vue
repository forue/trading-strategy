<template>
  <div class="monitor-page">
    <el-row :gutter="20">
      <!-- Docker容器状态 -->
      <el-col :span="12">
        <div class="page-card">
          <div class="card-header">
            <span class="card-title">Docker 服务状态</span>
            <el-button size="small" @click="refreshServices" :loading="refreshing">刷新</el-button>
          </div>
          <el-table :data="services" stripe size="small">
            <el-table-column prop="name" label="服务名称" width="160" />
            <el-table-column prop="status" label="状态" width="100">
              <template #default="{ row }">
                <el-badge :type="row.status === 'running' ? 'success' : row.status === 'stopped' ? 'danger' : 'warning'" is-dot />
                <span style="margin-left: 6px">{{ row.status }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="cpu" label="CPU" width="80" />
            <el-table-column prop="memory" label="内存" width="100" />
            <el-table-column prop="uptime" label="运行时间" width="120" />
            <el-table-column prop="port" label="端口" width="80" />
          </el-table>
        </div>
      </el-col>

      <!-- 服务健康检查 -->
      <el-col :span="12">
        <div class="page-card">
          <div class="card-header">
            <span class="card-title">服务健康检查</span>
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
    <div class="page-card" style="margin-top: 20px">
      <div class="card-header">
        <span class="card-title">系统日志</span>
        <el-select v-model="logService" size="small" style="width: 160px">
          <el-option label="全部服务" value="" />
          <el-option label="认证中心" value="auth" />
          <el-option label="策略引擎" value="strategy" />
          <el-option label="数据采集" value="data-collector" />
          <el-option label="信号通知" value="signal" />
          <el-option label="资金管理" value="fund" />
        </el-select>
      </div>
      <div class="log-container">
        <div v-for="(log, idx) in logs" :key="idx" class="log-line" :class="log.level">
          <span class="log-time">{{ log.time }}</span>
          <el-tag :type="logLevelMap[log.level]" size="small" style="margin: 0 8px">{{ log.level.toUpperCase() }}</el-tag>
          <span class="log-service">[{{ log.service }}]</span>
          <span class="log-message">{{ log.message }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue'

const refreshing = ref(false)
const logService = ref('')

const services = ref([
  { name: 'rotation-postgres', status: 'running', cpu: '0.5%', memory: '128MB', uptime: '3d 12h', port: '5432' },
  { name: 'rotation-redis', status: 'running', cpu: '0.2%', memory: '32MB', uptime: '3d 12h', port: '6379' },
  { name: 'rotation-influxdb', status: 'running', cpu: '1.2%', memory: '256MB', uptime: '3d 12h', port: '8086' },
  { name: 'rotation-rabbitmq', status: 'running', cpu: '0.8%', memory: '96MB', uptime: '3d 12h', port: '5672' },
  { name: 'rotation-auth', status: 'running', cpu: '0.3%', memory: '256MB', uptime: '2d 8h', port: '8001' },
  { name: 'rotation-strategy', status: 'running', cpu: '2.1%', memory: '512MB', uptime: '2d 8h', port: '8002' },
  { name: 'rotation-data-collector', status: 'running', cpu: '1.5%', memory: '384MB', uptime: '2d 8h', port: '8003' },
  { name: 'rotation-signal', status: 'running', cpu: '0.4%', memory: '192MB', uptime: '2d 8h', port: '8004' },
  { name: 'rotation-fund', status: 'running', cpu: '0.6%', memory: '320MB', uptime: '2d 8h', port: '8005' },
  { name: 'rotation-scheduler', status: 'running', cpu: '0.1%', memory: '128MB', uptime: '2d 8h', port: '8006' },
  { name: 'rotation-frontend', status: 'running', cpu: '0.1%', memory: '16MB', uptime: '2d 8h', port: '80' },
])

const healthChecks = reactive([
  { name: 'PostgreSQL', status: 'healthy', detail: '连接正常, 28个表' },
  { name: 'Redis', status: 'healthy', detail: '连接正常, 内存使用率32%' },
  { name: 'InfluxDB', status: 'healthy', detail: '连接正常, 1.2GB数据' },
  { name: 'RabbitMQ', status: 'healthy', detail: '连接正常, 3个队列' },
  { name: '认证中心', status: 'healthy', detail: 'HTTP 200, 响应12ms' },
  { name: '策略引擎', status: 'healthy', detail: 'HTTP 200, 响应45ms' },
  { name: '数据采集', status: 'healthy', detail: 'HTTP 200, 响应23ms' },
  { name: '信号通知', status: 'warning', detail: 'WebSocket连接数: 1' },
  { name: '资金管理', status: 'healthy', detail: 'HTTP 200, 响应18ms' },
  { name: '任务调度', status: 'healthy', detail: '下次执行: 15:00' },
])

const logLevelMap: Record<string, string> = { info: 'info', warn: 'warning', error: 'danger', debug: '' }

const logs = ref([
  { time: '2026-04-17 15:00:02', level: 'info', service: 'scheduler', message: '定时任务触发: 每日数据采集' },
  { time: '2026-04-17 15:00:05', level: 'info', service: 'data-collector', message: '开始采集申万一级行业资金流数据' },
  { time: '2026-04-17 15:00:12', level: 'info', service: 'data-collector', message: '采集完成: 28个板块, 写入InfluxDB 336条记录' },
  { time: '2026-04-17 15:00:15', level: 'info', service: 'strategy', message: '策略计算开始: 激进/稳健/保守三档轮动' },
  { time: '2026-04-17 15:00:18', level: 'warn', service: 'strategy', message: '保守策略: 有色金属估值分位52%超过上限50%, 已排除' },
  { time: '2026-04-17 15:00:20', level: 'info', service: 'strategy', message: '策略计算完成: 生成8条买卖信号' },
  { time: '2026-04-17 15:00:21', level: 'info', service: 'signal', message: '信号推送: 3条信号通过WebSocket推送到1个客户端' },
  { time: '2026-04-17 15:00:22', level: 'info', service: 'fund', message: '净值计算完成: 稳健策略今日收益率0.35%' },
  { time: '2026-04-17 14:30:00', level: 'info', service: 'auth', message: '用户 admin 登录成功, Token有效期24h' },
  { time: '2026-04-17 09:30:00', level: 'info', service: 'data-collector', message: '开盘数据采集启动, 实时模式' },
])

async function refreshServices() {
  refreshing.value = true
  setTimeout(() => { refreshing.value = false }, 1000)
}
</script>

<style lang="scss" scoped>
.card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; .card-title { font-size: 16px; font-weight: 600; } }
.health-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }
.health-item { display: flex; align-items: center; gap: 12px; padding: 12px; border-radius: 8px; background: #f5f7fa; &.healthy { border-left: 3px solid #67c23a; } &.unhealthy { border-left: 3px solid #f56c6c; } &.warning { border-left: 3px solid #e6a23c; } .health-info { .health-name { font-weight: 500; font-size: 14px; } .health-detail { color: #909399; font-size: 12px; margin-top: 4px; } } }
.log-container { background: #1d1e2c; border-radius: 8px; padding: 16px; max-height: 400px; overflow-y: auto; font-family: 'Consolas', 'Monaco', monospace; font-size: 13px; }
.log-line { padding: 4px 0; color: #d4d4d4; display: flex; align-items: center; &.warn { color: #e6a23c; } &.error { color: #f56c6c; } &.debug { color: #909399; } .log-time { color: #6a9955; min-width: 160px; } .log-service { color: #569cd6; min-width: 120px; } .log-message { flex: 1; } }
</style>
