<template>
  <div
    v-if="task && !dismissed"
    class="replay-task-card"
    :class="[`is-${task.status}`, { 'is-collapsed': collapsed }]"
    role="status"
    aria-live="polite"
  >
    <div class="rt-head">
      <span class="rt-title">
        <el-icon class="rt-icon"><component :is="statusIcon" /></el-icon>
        {{ statusTitle }}
      </span>
      <div class="rt-actions">
        <button class="rt-icon-btn" :title="collapsed ? '展开' : '收起'" @click="collapsed = !collapsed">
          <el-icon><component :is="collapsed ? 'ArrowDown' : 'ArrowUp'" /></el-icon>
        </button>
        <button class="rt-icon-btn" title="关闭" @click="store.dismiss()">
          <el-icon><Close /></el-icon>
        </button>
      </div>
    </div>

    <template v-if="!collapsed">
      <div class="rt-meta">
        {{ strategyLabel }} · {{ task.startDate }} ~ {{ task.endDate }}
      </div>

      <div v-if="task.mode === 'optimize'" class="rt-progress">
        <el-progress
          :percentage="percent"
          :status="task.status === 'done' ? 'success' : (task.status === 'failed' ? 'exception' : undefined)"
          :stroke-width="6"
          :show-text="false"
        />
        <span class="rt-percent">{{ task.progress }}/{{ task.total }}（{{ percent }}%）</span>
      </div>
      <div v-else class="rt-progress">
        <div class="rt-flow" :class="{ 'is-done': task.status === 'done', 'is-failed': task.status === 'failed' }">
          <span class="rt-flow-fill" />
        </div>
        <span class="rt-percent">{{ statusTitle }}</span>
      </div>

      <div v-if="task.status === 'done' && (task.totalReturn != null || task.maxDrawdown != null)" class="rt-result">
        <span v-if="task.totalReturn != null">
          总收益 <b :style="{ color: task.totalReturn >= 0 ? 'var(--accent-danger)' : 'var(--accent-success)' }">
            {{ task.totalReturn >= 0 ? '+' : '' }}{{ (task.totalReturn * 100).toFixed(2) }}%
          </b>
        </span>
        <span v-if="task.maxDrawdown != null">回撤 <b>{{ (task.maxDrawdown * 100).toFixed(2) }}%</b></span>
        <span v-if="task.sharpeRatio != null">夏普 <b>{{ task.sharpeRatio }}</b></span>
      </div>
      <div v-if="task.message" class="rt-message" :class="{ 'is-error': task.status === 'failed' }">
        {{ task.message }}
      </div>

      <button class="rt-goto" @click="goReplay">
        查看回放详情 <el-icon><ArrowRight /></el-icon>
      </button>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useReplayTaskStore } from '@/stores/replayTask'
import { settingsApi } from '@/api/settings'

const store = useReplayTaskStore()
const router = useRouter()
const collapsed = ref(false)

// 小卡常驻 MainLayout：后台任务（叠加回放/寻优）的进度与结果统一在这里轮询，
// 不依赖 DataReplay 是否挂载——切页、刷新、停在任意页面都能完成并落结果。
let pollTimer: number | null = null
async function pollTask() {
  const t = store.task
  if (!t || t.status !== 'running') return
  try {
    if (t.mode === 'optimize') {
      const p: any = await settingsApi.getOptimizeProgress()
      if (!store.task || store.task.status !== 'running') return
      store.updateProgress(p.completed, p.total)
      if (!p.active) {
        stopPolling()
        const r: any = await settingsApi.getOptimizeResult().catch(() => null)
        const result = r?.result
        store.finish({
          totalReturn: result?.best_result?.total_return ?? p.best_return ?? null,
          maxDrawdown: result?.best_result?.max_drawdown ?? null,
          sharpeRatio: result?.best_result?.sharpe_ratio ?? p.best_sharpe ?? null,
          message: `测试${p.completed}种参数`,
          data: result || undefined,
        })
      }
    } else {
      const r: any = await settingsApi.getOverlayResult().catch(() => null)
      if (!store.task || store.task.status !== 'running') return
      if (r?.status === 'running') return
      stopPolling()
      if (r?.status === 'failed') {
        store.fail(r.error || '策略回放失败')
        return
      }
      const data = r?.result
      if (!data) return
      const s = data.summary
      store.finish({
        totalReturn: s?.total_return,
        maxDrawdown: s?.max_drawdown,
        sharpeRatio: s?.sharpe_ratio,
        data,
      })
    }
  } catch { /* 接口偶发失败时下一轮再试 */ }
}
function syncPolling() {
  const t = store.task
  if (t && t.status === 'running') {
    if (pollTimer == null) {
      void pollTask()
      pollTimer = window.setInterval(pollTask, 2000)
    }
  } else {
    stopPolling()
  }
}
function stopPolling() {
  if (pollTimer != null) { clearInterval(pollTimer); pollTimer = null }
}

onMounted(syncPolling)
watch(() => [store.task?.status, store.task?.mode], syncPolling)
onUnmounted(stopPolling)

const task = computed(() => store.task)
const dismissed = computed(() => store.dismissed)

const STRATEGY_LABEL: Record<string, string> = {
  AGGRESSIVE: '激进轮动',
  MODERATE: '稳健轮动',
  CONSERVATIVE: '保守轮动',
}
const strategyLabel = computed(() => {
  const t = task.value
  if (!t) return ''
  return STRATEGY_LABEL[t.strategyType] || t.strategyType
})

const percent = computed(() => {
  const t = task.value
  if (!t || t.total <= 0) return 0
  return Math.min(100, Math.round((t.progress / t.total) * 100))
})

const statusTitle = computed(() => {
  const t = task.value
  if (!t) return ''
  if (t.status === 'running') return t.mode === 'optimize' ? '自动寻优中' : '策略回放中'
  if (t.status === 'failed') return t.mode === 'optimize' ? '寻优失败' : '回放失败'
  return t.mode === 'optimize' ? '寻优完成' : '回放完成'
})

const statusIcon = computed(() => {
  const t = task.value
  if (!t) return 'Loading'
  if (t.status === 'running') return 'Loading'
  if (t.status === 'failed') return 'WarningFilled'
  return 'SuccessFilled'
})

function goReplay() {
  router.push('/data-replay')
}
</script>

<style lang="scss" scoped>
.replay-task-card {
  position: fixed;
  right: 20px;
  bottom: 20px;
  z-index: 2000;
  width: 300px;
  box-sizing: border-box;
  padding: 12px 14px;
  border: 1px solid var(--border-primary);
  border-radius: var(--radius-md);
  background: var(--bg-surface);
  box-shadow: var(--shadow-modal);
  font-size: 12px;
  color: var(--text-secondary);
  transition: transform var(--dur-base) var(--ease);

  &.is-collapsed { width: 220px; }
}

.rt-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.rt-title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);

  .rt-icon { font-size: 15px; color: var(--accent-primary); }
}
.is-done .rt-title .rt-icon { color: var(--accent-success); }
.is-failed .rt-title .rt-icon { color: var(--accent-danger); }

.rt-actions {
  display: flex;
  gap: 2px;
}

.rt-icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  padding: 0;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: var(--text-tertiary);
  cursor: pointer;
  font-size: 13px;

  &:hover { background: var(--bg-hover); color: var(--text-primary); }
}

.rt-meta {
  margin-top: 6px;
  font-size: 11px;
  color: var(--text-tertiary);
  font-family: var(--font-mono);
}

.rt-progress {
  margin-top: 10px;
}

.rt-percent {
  display: block;
  margin-top: 4px;
  font-size: 11px;
  color: var(--text-secondary);
  font-family: var(--font-mono);
}

.rt-flow {
  position: relative;
  height: 6px;
  border-radius: 3px;
  background: var(--bg-tertiary);
  overflow: hidden;

  .rt-flow-fill {
    position: absolute;
    top: 0;
    left: 0;
    width: 35%;
    height: 100%;
    border-radius: 3px;
    background: linear-gradient(90deg, var(--accent-primary), var(--accent-warning));
    animation: rt-flow 1.4s ease-in-out infinite;
  }
  &.is-done .rt-flow-fill { width: 100%; animation: none; background: var(--accent-success); }
  &.is-failed .rt-flow-fill { width: 100%; animation: none; background: var(--accent-danger); }
}

@keyframes rt-flow {
  from { transform: translateX(-100%); }
  to { transform: translateX(320%); }
}

.rt-result {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 12px;
  margin-top: 10px;
  font-size: 11px;
  color: var(--text-tertiary);

  b { font-family: var(--font-mono); font-size: 12px; color: var(--text-primary); }
}

.rt-message {
  margin-top: 8px;
  font-size: 11px;
  line-height: 1.45;
  color: var(--text-secondary);
  word-break: break-all;
  &.is-error { color: var(--accent-danger); }
}

.rt-goto {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-top: 10px;
  padding: 4px 8px;
  border: 1px solid var(--accent-primary);
  border-radius: 4px;
  background: transparent;
  color: var(--accent-primary-text);
  cursor: pointer;
  font-size: 11px;
  font-family: var(--font-sans);

  &:hover { background: var(--accent-primary-light); }
}

@media (max-width: 480px) {
  .replay-task-card {
    right: 10px;
    bottom: 62px;
    left: 10px;
    width: auto;

    &.is-collapsed { width: auto; }
  }
}

@media (prefers-reduced-motion: reduce) {
  .rt-flow .rt-flow-fill { animation: none; width: 100%; opacity: 0.5; }
}
</style>
