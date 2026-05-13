<template>
  <div class="settings-page">
    <el-tabs v-model="activeTab" type="border-card">
      <!-- WebSocket 实时推送设置 -->
      <el-tab-pane label="实时推送" name="ws">
        <div class="page-card">
          <div class="card-header">
            <span class="card-title">WebSocket 实时推送</span>
            <el-tag :type="wsEnabled ? 'success' : 'info'" size="small">{{ wsEnabled ? '已启用' : '已关闭' }}</el-tag>
          </div>
          <el-form label-width="160px" style="max-width: 600px">
            <el-form-item label="启用实时推送">
              <el-switch v-model="wsEnabled" active-text="开" inactive-text="关" @change="onWsEnabledChange" />
            </el-form-item>
            <el-form-item label="推送策略类型">
              <el-checkbox-group v-model="wsStrategyTypes" @change="saveSettings">
                <el-checkbox label="AGGRESSIVE">激进轮动</el-checkbox>
                <el-checkbox label="MODERATE">稳健轮动</el-checkbox>
                <el-checkbox label="CONSERVATIVE">保守轮动</el-checkbox>
              </el-checkbox-group>
            </el-form-item>
            <el-form-item label="连接状态">
              <el-tag :type="signalStore.isConnected ? 'success' : 'danger'" size="small">
                {{ signalStore.isConnected ? '已连接' : '未连接' }}
              </el-tag>
              <el-button size="small" style="margin-left: 12px" @click="toggleWsConnection">
                {{ signalStore.isConnected ? '断开' : '连接' }}
              </el-button>
            </el-form-item>
            <el-form-item label="浏览器通知">
              <el-button size="small" @click="requestNotificationPermission">授权通知</el-button>
              <el-tag :type="notificationStatus === 'granted' ? 'success' : notificationStatus === 'denied' ? 'danger' : 'warning'" size="small" style="margin-left: 8px">
                {{ notificationStatus === 'granted' ? '已授权' : notificationStatus === 'denied' ? '已拒绝' : '未授权' }}
              </el-tag>
            </el-form-item>
          </el-form>
        </div>
      </el-tab-pane>

      <!-- 外部推送通道 -->
      <el-tab-pane label="推送通道" name="notify">
        <div class="page-card">
          <div class="card-header">
            <span class="card-title">外部推送通道</span>
            <el-tag type="info" size="small">支持钉钉、企业微信</el-tag>
          </div>

          <!-- 钉钉机器人 -->
          <el-divider content-position="left">钉钉机器人</el-divider>
          <el-form label-width="160px" style="max-width: 700px">
            <el-form-item label="启用钉钉推送">
              <el-switch v-model="notifyConfig.dingtalk.enabled" active-text="开" inactive-text="关" @change="saveNotifyConfig" />
            </el-form-item>
            <el-form-item label="Webhook 地址">
              <el-input
                v-model="notifyConfig.dingtalk.webhook_url"
                placeholder="https://oapi.dingtalk.com/robot/send?access_token=..."
                :disabled="!notifyConfig.dingtalk.enabled"
                clearable
                @change="saveNotifyConfig"
              />
              <div v-if="notifyConfig.dingtalk.webhook_url_display && !notifyConfig.dingtalk.webhook_url" class="form-hint">
                当前: {{ notifyConfig.dingtalk.webhook_url_display }}
              </div>
            </el-form-item>
            <el-form-item label="加签密钥">
              <el-input
                v-model="notifyConfig.dingtalk.secret"
                placeholder="SEC... (可选，安全设置中的加签密钥)"
                :disabled="!notifyConfig.dingtalk.enabled"
                clearable
                @change="saveNotifyConfig"
              />
              <div class="form-hint">钉钉机器人安全设置选择"加签"时需要填写</div>
            </el-form-item>
            <el-form-item>
              <el-button
                type="primary"
                size="small"
                :disabled="!notifyConfig.dingtalk.enabled || !notifyConfig.dingtalk.webhook_url"
                :loading="testingDingtalk"
                @click="testNotify('dingtalk')"
              >
                {{ testingDingtalk ? '发送中...' : '发送测试消息' }}
              </el-button>
            </el-form-item>
          </el-form>

          <!-- 企业微信机器人 -->
          <el-divider content-position="left">企业微信机器人</el-divider>
          <el-form label-width="160px" style="max-width: 700px">
            <el-form-item label="启用企微推送">
              <el-switch v-model="notifyConfig.wecom.enabled" active-text="开" inactive-text="关" @change="saveNotifyConfig" />
            </el-form-item>
            <el-form-item label="Webhook 地址">
              <el-input
                v-model="notifyConfig.wecom.webhook_url"
                placeholder="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=..."
                :disabled="!notifyConfig.wecom.enabled"
                clearable
                @change="saveNotifyConfig"
              />
              <div v-if="notifyConfig.wecom.webhook_url_display && !notifyConfig.wecom.webhook_url" class="form-hint">
                当前: {{ notifyConfig.wecom.webhook_url_display }}
              </div>
            </el-form-item>
            <el-form-item>
              <el-button
                type="primary"
                size="small"
                :disabled="!notifyConfig.wecom.enabled || !notifyConfig.wecom.webhook_url"
                :loading="testingWecom"
                @click="testNotify('wecom')"
              >
                {{ testingWecom ? '发送中...' : '发送测试消息' }}
              </el-button>
            </el-form-item>
          </el-form>

          <!-- 使用说明 -->
          <el-divider content-position="left">使用说明</el-divider>
          <el-alert type="info" :closable="false" show-icon>
            <template #title>
              <div style="line-height: 1.8">
                <p><b>钉钉机器人</b>：在钉钉群 → 设置 → 智能群助手 → 添加机器人 → 自定义 → 复制 Webhook 地址</p>
                <p><b>企业微信机器人</b>：在企微群 → 添加群机器人 → 新建机器人 → 复制 Webhook 地址</p>
                <p>信号触发后，会自动向已启用的通道推送买入/卖出信号通知</p>
              </div>
            </template>
          </el-alert>
        </div>
      </el-tab-pane>

      <!-- 数据源设置 -->
      <el-tab-pane label="数据源" name="datasource">
        <div class="page-card">
          <div class="card-header">
            <span class="card-title">数据源配置</span>
          </div>
          <el-form label-width="160px" style="max-width: 700px">
            <el-form-item label="当前数据源">
              <el-select v-model="dataSource" style="width: 300px" @change="saveSettings">
                <el-option label="AkShare (东方财富)" value="akshare" />
                <el-option label="Tushare Pro" value="tushare" disabled />
                <el-option label="Wind 万得" value="wind" disabled />
              </el-select>
            </el-form-item>
            <el-form-item label="数据说明">
              <el-alert :closable="false" type="warning" show-icon>
                <template #title>
                  当前使用 AkShare 开源接口，板块资金流仅支持当日数据。
                  Tushare Pro / Wind 需要付费授权，暂未集成。
                </template>
              </el-alert>
            </el-form-item>
            <el-form-item label="数据可用范围">
              <div v-if="dataAvailability.has_data">
                <el-tag type="success" size="small">{{ dataAvailability.min_date }} ~ {{ dataAvailability.max_date }}</el-tag>
              </div>
              <el-tag v-else type="danger" size="small">无历史数据</el-tag>
            </el-form-item>
            <el-form-item label="采集历史数据">
              <el-input-number v-model="collectDays" :min="7" :max="365" :step="7" style="width: 160px; margin-right: 10px" />
              <el-button type="warning" :loading="collecting" @click="collectHistoryData" size="default">
                {{ collecting ? '采集中...' : '开始采集' }}
              </el-button>
            </el-form-item>
          </el-form>
        </div>
      </el-tab-pane>

      <!-- 缓存配置 -->
      <el-tab-pane label="缓存管理" name="cache">
        <div class="page-card">
          <div class="card-header">
            <span class="card-title">缓存管理</span>
            <el-button size="small" @click="loadCacheStats" :loading="loadingCache">刷新统计</el-button>
          </div>

          <el-row :gutter="20" v-if="cacheStats" style="margin-bottom: 20px">
            <el-col :xs="12" :sm="6">
              <div class="stat-box">
                <div class="stat-value">{{ cacheStats.total_keys }}</div>
                <div class="stat-label">缓存Key总数</div>
              </div>
            </el-col>
            <el-col :xs="12" :sm="6">
              <div class="stat-box">
                <div class="stat-value">{{ cacheStats.used_memory_human }}</div>
                <div class="stat-label">已用内存</div>
              </div>
            </el-col>
            <el-col :xs="12" :sm="6">
              <div class="stat-box">
                <div class="stat-value">{{ cacheStats.peak_memory_human }}</div>
                <div class="stat-label">内存峰值</div>
              </div>
            </el-col>
            <el-col :xs="12" :sm="6">
              <div class="stat-box">
                <div class="stat-value">{{ Object.keys(cacheStats.categories).length }}</div>
                <div class="stat-label">缓存分类数</div>
              </div>
            </el-col>
          </el-row>

          <el-form label-width="160px" style="max-width: 600px; margin-bottom: 20px">
            <el-form-item label="默认缓存天数">
              <el-input-number v-model="cacheTtlDays" :min="1" :max="90" @change="saveSettings" />
              <span style="margin-left: 8px; color: var(--text-tertiary); font-size: 13px">天</span>
            </el-form-item>
          </el-form>

          <div class="responsive-table"><el-table v-if="cacheStats && Object.keys(cacheStats.categories).length > 0" :data="categoryData" stripe size="small" style="margin-bottom: 20px">
            <el-table-column prop="name" label="缓存分类" width="200">
              <template #default="{ row }">{{ categoryLabels[row.name] || row.name }}</template>
            </el-table-column>
            <el-table-column prop="count" label="Key数量" width="120" />
            <el-table-column prop="name" label="说明">
              <template #default="{ row }">{{ categoryDescs[row.name] || '' }}</template>
            </el-table-column>
          </el-table></div>

          <div style="display: flex; gap: 12px">
            <el-popconfirm title="确定清除所有无过期时间的缓存key？" @confirm="handleClearExpired">
              <template #reference>
                <el-button type="warning" :loading="clearing">清理无TTL缓存</el-button>
              </template>
            </el-popconfirm>
            <el-popconfirm title="确定清空所有缓存？此操作不可恢复！" @confirm="handleClearAll">
              <template #reference>
                <el-button type="danger" :loading="clearing">清空全部缓存</el-button>
              </template>
            </el-popconfirm>
          </div>
        </div>
      </el-tab-pane>

      <!-- 数据库管理 -->
      <el-tab-pane label="数据库" name="database">
        <div class="page-card">
          <div class="card-header">
            <span class="card-title">数据库状态</span>
            <el-button size="small" @click="loadDbStatus" :loading="loadingDb">刷新</el-button>
          </div>

          <el-row :gutter="20" v-if="dbStatus">
            <el-col :xs="24" :sm="12" :md="8">
              <div class="db-card">
                <div class="db-header">
                  <el-icon :size="24" color="#336791"><Coin /></el-icon>
                  <span>PostgreSQL</span>
                  <el-tag :type="dbStatus.postgresql.status === 'connected' ? 'success' : 'danger'" size="small">
                    {{ dbStatus.postgresql.status === 'connected' ? '已连接' : '不可用' }}
                  </el-tag>
                </div>
                <div class="db-info">
                  <div>数据库: rotation_db</div>
                  <div>用途: 用户认证、资金管理</div>
                </div>
              </div>
            </el-col>
            <el-col :xs="24" :sm="12" :md="8">
              <div class="db-card">
                <div class="db-header">
                  <el-icon :size="24" color="#5951FF"><Clock /></el-icon>
                  <span>InfluxDB</span>
                  <el-tag :type="dbStatus.influxdb.status === 'connected' || dbStatus.influxdb.status === 'ready' || dbStatus.influxdb.status === 'pass' ? 'success' : 'danger'" size="small">
                    {{ dbStatus.influxdb.status === 'connected' ? '已连接' : dbStatus.influxdb.status === 'pass' ? '已连接' : dbStatus.influxdb.status === 'ready' ? '已连接' : '不可用' }}
                  </el-tag>
                </div>
                <div class="db-info">
                  <div>Bucket: {{ dbStatus.influxdb.bucket }}</div>
                  <div>Org: {{ dbStatus.influxdb.org }}</div>
                  <div v-if="dbStatus.influxdb.detail">状态: {{ dbStatus.influxdb.detail }}</div>
                  <div>数据范围: {{ dbStatus.influxdb.data_counts?.date_range || '无' }}</div>
                </div>
              </div>
            </el-col>
            <el-col :xs="24" :sm="12" :md="8">
              <div class="db-card">
                <div class="db-header">
                  <el-icon :size="24" color="#DC382D"><Lightning /></el-icon>
                  <span>Redis</span>
                  <el-tag :type="dbStatus.redis.status === 'connected' ? 'success' : 'danger'" size="small">
                    {{ dbStatus.redis.status }}
                  </el-tag>
                </div>
                <div class="db-info">
                  <div>版本: {{ dbStatus.redis.version }}</div>
                  <div>内存: {{ dbStatus.redis.used_memory }}</div>
                  <div>运行: {{ dbStatus.redis.uptime_days }} 天</div>
                </div>
              </div>
            </el-col>
          </el-row>
        </div>

        <!-- 调度设置 -->
        <div class="page-card page-section">
          <div class="card-header">
            <span class="card-title">定时任务调度</span>
            <el-switch v-model="schedulerEnabled" active-text="启用" inactive-text="关闭" @change="saveSettings" />
          </div>
          <el-form label-width="160px" style="max-width: 600px">
            <el-form-item label="数据采集时间">
              <el-time-picker v-model="schedulerTimes.collect" format="HH:mm" value-format="HH:mm" placeholder="采集时间" @change="saveSettings" />
              <span style="margin-left: 8px; color: var(--text-tertiary); font-size: 13px">每交易日</span>
            </el-form-item>
            <el-form-item label="策略计算时间">
              <el-time-picker v-model="schedulerTimes.calculate" format="HH:mm" value-format="HH:mm" placeholder="计算时间" @change="saveSettings" />
              <span style="margin-left: 8px; color: var(--text-tertiary); font-size: 13px">每交易日</span>
            </el-form-item>
            <el-form-item label="北向资金采集">
              <el-time-picker v-model="schedulerTimes.north_bound" format="HH:mm" value-format="HH:mm" placeholder="采集时间" @change="saveSettings" />
              <span style="margin-left: 8px; color: var(--text-tertiary); font-size: 13px">每交易日</span>
            </el-form-item>
          </el-form>
        </div>
      </el-tab-pane>

      <!-- AI 模型配置 -->
      <el-tab-pane label="AI 配置" name="ai">
        <AiSettings />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { settingsApi } from '@/api/settings'
import { strategyApi } from '@/api/strategy'
import { useSignalStore } from '@/stores/signal'
import AiSettings from '@/components/AiSettings.vue'
import type { NotifyConfig } from '@/api/settings'

const signalStore = useSignalStore()

const activeTab = ref('ws')
const loadingCache = ref(false)
const loadingDb = ref(false)
const collecting = ref(false)
const clearing = ref(false)
const collectDays = ref(60)

// 通知权限状态
const notificationStatus = ref(Notification.permission || 'default')

// 推送通道配置
const notifyConfig = reactive<NotifyConfig>({
  dingtalk: { enabled: false, webhook_url: '', secret: '' },
  wecom: { enabled: false, webhook_url: '' },
})
const testingDingtalk = ref(false)
const testingWecom = ref(false)

async function loadNotifyConfig() {
  try {
    const data = await settingsApi.getNotifyConfig()
    notifyConfig.dingtalk = {
      ...notifyConfig.dingtalk,
      ...data.dingtalk,
      // 不覆盖本地编辑中的 webhook_url，只加载 enabled 等状态
      webhook_url: data.dingtalk.webhook_url || '',
      webhook_url_display: data.dingtalk.webhook_url_display || '',
    }
    notifyConfig.wecom = {
      ...notifyConfig.wecom,
      ...data.wecom,
      webhook_url: data.wecom.webhook_url || '',
      webhook_url_display: data.wecom.webhook_url_display || '',
    }
  } catch { /* ignore */ }
}

async function saveNotifyConfig() {
  try {
    await settingsApi.updateNotifyConfig({
      dingtalk: {
        enabled: notifyConfig.dingtalk.enabled,
        webhook_url: notifyConfig.dingtalk.webhook_url,
        secret: notifyConfig.dingtalk.secret,
      },
      wecom: {
        enabled: notifyConfig.wecom.enabled,
        webhook_url: notifyConfig.wecom.webhook_url,
      },
    })
    ElMessage.success('推送通道配置已保存')
  } catch {
    ElMessage.error('保存推送通道配置失败')
  }
}

async function testNotify(channel: 'dingtalk' | 'wecom') {
  if (channel === 'dingtalk') {
    testingDingtalk.value = true
  } else {
    testingWecom.value = true
  }
  try {
    await settingsApi.testNotifyChannel(channel)
    ElMessage.success('测试消息已发送')
  } catch (e: any) {
    ElMessage.error(e?.message || '测试消息发送失败')
  } finally {
    testingDingtalk.value = false
    testingWecom.value = false
  }
}

function requestNotificationPermission() {
  if ('Notification' in window) {
    Notification.requestPermission().then((p) => {
      notificationStatus.value = p
      if (p === 'granted') ElMessage.success('通知权限已授权')
      else ElMessage.warning('通知权限被拒绝')
    })
  }
}

// WebSocket设置
const wsEnabled = ref(true)
const wsStrategyTypes = ref(['AGGRESSIVE', 'MODERATE', 'CONSERVATIVE'])

function toggleWsConnection() {
  if (signalStore.isConnected) {
    signalStore.disconnectWebSocket()
    ElMessage.info('WebSocket已断开')
  } else {
    signalStore.connectWebSocket()
    ElMessage.info('正在连接WebSocket...')
  }
}

// 监听 wsEnabled 变化，自动连接/断开 WebSocket
function onWsEnabledChange(val: boolean) {
  if (val) {
    signalStore.connectWebSocket()
  } else {
    signalStore.disconnectWebSocket()
  }
  saveSettings()
}

// 数据源设置
const dataSource = ref('akshare')
const dataAvailability = reactive({ has_data: false, min_date: '', max_date: '' })

async function checkDataAvailability() {
  try {
    const data = await strategyApi.getDataAvailability()
    dataAvailability.has_data = data.has_data
    dataAvailability.min_date = data.min_date || ''
    dataAvailability.max_date = data.max_date || ''
  } catch { /* ignore */ }
}

async function collectHistoryData() {
  collecting.value = true
  try {
    await strategyApi.collectHistory(collectDays.value)
    ElMessage.success('历史数据采集成功')
    await checkDataAvailability()
    await loadDbStatus()
  } catch {
    ElMessage.error('数据采集失败')
  } finally {
    collecting.value = false
  }
}

// 缓存管理
const cacheStats = ref<any>(null)
const cacheTtlDays = ref(7)

const categoryLabels: Record<string, string> = {
  backtest_result: '回测结果',
  backtest_history: '回测历史',
  signals: '交易信号',
  sector_data: '板块数据',
  system_settings: '系统设置',
}
const categoryDescs: Record<string, string> = {
  backtest_result: '单次回测的完整结果数据，含净值曲线',
  backtest_history: '回测记录列表索引，按策略类型分组',
  signals: '每日策略计算产生的买卖信号',
  sector_data: '板块资金流向缓存数据',
  system_settings: '系统配置参数',
}
const categoryData = computed(() => {
  if (!cacheStats.value?.categories) return []
  return Object.entries(cacheStats.value.categories).map(([name, count]) => ({ name, count }))
})

async function loadCacheStats() {
  loadingCache.value = true
  try {
    cacheStats.value = await settingsApi.getCacheStats()
  } catch {
    ElMessage.error('获取缓存统计失败')
  } finally {
    loadingCache.value = false
  }
}

async function handleClearExpired() {
  clearing.value = true
  try {
    const res = await settingsApi.clearExpiredCache()
    ElMessage.success(res.message || '清理完成')
    await loadCacheStats()
  } catch {
    ElMessage.error('清理失败')
  } finally {
    clearing.value = false
  }
}

async function handleClearAll() {
  clearing.value = true
  try {
    await settingsApi.clearAllCache()
    ElMessage.success('缓存已全部清空')
    await loadCacheStats()
  } catch {
    ElMessage.error('清空失败')
  } finally {
    clearing.value = false
  }
}

// 数据库管理
const dbStatus = ref<any>(null)
const schedulerEnabled = ref(true)
const schedulerTimes = reactive({
  collect: '15:00',
  calculate: '15:05',
  north_bound: '16:00',
})

async function loadDbStatus() {
  loadingDb.value = true
  try {
    dbStatus.value = await settingsApi.getDatabaseStatus()
  } catch {
    ElMessage.error('获取数据库状态失败')
  } finally {
    loadingDb.value = false
  }
}

// 保存设置
async function saveSettings() {
  try {
    await settingsApi.updateSystemSettings({
      ws_push_enabled: wsEnabled.value,
      ws_push_strategy_types: wsStrategyTypes.value,
      data_source: dataSource.value,
      cache_ttl_days: cacheTtlDays.value,
      scheduler_enabled: schedulerEnabled.value,
      scheduler_times: { ...schedulerTimes },
    })
    ElMessage.success('设置已保存')
  } catch (e: any) {
    ElMessage.error('保存设置失败: ' + (e?.message || '未知错误'))
  }
}

// 加载设置
async function loadSettings() {
  try {
    const data = await settingsApi.getSystemSettings()
    wsEnabled.value = data.ws_push_enabled ?? true
    wsStrategyTypes.value = data.ws_push_strategy_types ?? ['AGGRESSIVE', 'MODERATE', 'CONSERVATIVE']
    dataSource.value = data.data_source ?? 'akshare'
    cacheTtlDays.value = data.cache_ttl_days ?? 7
    schedulerEnabled.value = data.scheduler_enabled ?? true
    if (data.scheduler_times) {
      schedulerTimes.collect = data.scheduler_times.collect || '15:00'
      schedulerTimes.calculate = data.scheduler_times.calculate || '15:05'
      schedulerTimes.north_bound = data.scheduler_times.north_bound || '16:00'
    }
  } catch { /* ignore */ }
}

onMounted(() => {
  loadSettings()
  loadNotifyConfig()
  loadCacheStats()
  loadDbStatus()
  checkDataAvailability()
})
</script>

<style lang="scss" scoped>
.settings-page { padding: 0; }
:deep(.el-tabs--border-card) {
  border-radius: var(--radius-md);
  overflow: hidden;
  border: 1px solid var(--border-secondary);
  background: var(--bg-secondary);
}
:deep(.el-tabs--border-card > .el-tabs__header) {
  background: var(--bg-tertiary);
  border-bottom: 1px solid var(--border-secondary);
}
:deep(.el-tabs--border-card > .el-tabs__header .el-tabs__item) {
  border-radius: var(--radius-md) var(--radius-md) 0 0;
}
.stat-box {
  text-align: center; padding: 20px;
  background: var(--bg-tertiary); border-radius: var(--radius-sm);
  .stat-value { font-size: 24px; font-weight: 600; color: var(--text-primary); font-family: var(--font-mono); }
  .stat-label { font-size: 13px; color: var(--text-tertiary); margin-top: 6px; }
}
.db-card {
  background: var(--bg-tertiary); border-radius: var(--radius-sm); padding: 20px;
  transition: background var(--transition-base);
  .db-header { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; font-size: 16px; font-weight: 600; color: var(--text-primary); }
  .db-info { font-size: 13px; color: var(--text-secondary); line-height: 1.8; }
}
.card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; .card-title { font-size: 16px; font-weight: 600; color: var(--text-primary); } }
.form-hint { font-size: 12px; color: var(--text-tertiary); margin-top: 4px; }

@media (max-width: 480px) {
  :deep(.el-form-item__label) { width: auto !important; display: block; text-align: left; }
  .stat-box { padding: 12px; .stat-value { font-size: 18px; } }
  .db-card { padding: 12px; .db-header { font-size: 14px; } }
}
</style>
