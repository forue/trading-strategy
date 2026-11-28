import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

export type ReplayTaskMode = 'overlay' | 'optimize'
export type ReplayTaskStatus = 'running' | 'done' | 'failed'

// 跨页面存活的回测任务快照。组件切走后 DataReplay 会被卸载，
// 任务状态必须放全局 store，悬浮小卡才能持续显示进度与结果。
export interface ReplayTask {
  mode: ReplayTaskMode
  status: ReplayTaskStatus
  strategyType: string
  startDate: string
  endDate: string
  initialCapital: number
  progress: number
  total: number
  startedAt: number
  finishedAt: number | null
  message: string
  totalReturn: number | null
  maxDrawdown: number | null
  sharpeRatio: number | null
  // 完整结果存全局：点「查看回放详情」跳回页面后可直接恢复图表与明细，
  // 不必重跑一次回测，也不依赖页面内 ref（切路由会销毁）。
  result: any | null
}

function blankTask(): ReplayTask {
  return {
    mode: 'overlay',
    status: 'running',
    strategyType: '',
    startDate: '',
    endDate: '',
    initialCapital: 1000000,
    progress: 0,
    total: 0,
    startedAt: 0,
    finishedAt: null,
    message: '',
    totalReturn: null,
    maxDrawdown: null,
    sharpeRatio: null,
    result: null,
  }
}

const STORAGE_KEY = 'replay-task-card'

// 刷新后要恢复小卡与结果：Pinia 是纯内存态，必须落到 sessionStorage。
// 用 sessionStorage 而非 localStorage：任务卡属于当前会话，关标签页即失效。
function loadPersisted(): { task: ReplayTask | null; dismissed: boolean } {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    if (!raw) return { task: null, dismissed: false }
    const parsed = JSON.parse(raw)
    const t = parsed.task as ReplayTask | null
    if (!t) return { task: null, dismissed: false }
    // 运行中的任务也恢复：刷新后 DataReplay.onMounted 会接上后台寻优轮询。
    // 普通回放若请求已随刷新中断，续接逻辑会将其标记为失败并提示重跑。
    return { task: t, dismissed: !!parsed.dismissed }
  } catch {
    return { task: null, dismissed: false }
  }
}

export const useReplayTaskStore = defineStore('replayTask', () => {
  // null 表示当前无任务，小卡不渲染
  const persisted = loadPersisted()
  const task = ref<ReplayTask | null>(persisted.task)
  const dismissed = ref(persisted.dismissed)

  watch(
    [task, dismissed],
    () => {
      try {
        sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ task: task.value, dismissed: dismissed.value }))
      } catch { /* 存储超限/隐私模式：忽略，退化为内存态 */ }
    },
    { deep: true },
  )

  function start(mode: ReplayTaskMode, payload: {
    strategyType: string
    startDate: string
    endDate: string
    initialCapital?: number
    total?: number
  }) {
    task.value = {
      ...blankTask(),
      mode,
      strategyType: payload.strategyType,
      startDate: payload.startDate,
      endDate: payload.endDate,
      initialCapital: payload.initialCapital ?? 1000000,
      total: payload.total || 0,
      startedAt: Date.now(),
    }
    dismissed.value = false
  }

  function updateProgress(completed: number, total?: number) {
    if (!task.value) return
    task.value.progress = completed
    if (total != null) task.value.total = total
  }

  function finish(result: {
    totalReturn?: number | null
    maxDrawdown?: number | null
    sharpeRatio?: number | null
    message?: string
    data?: any
  }) {
    if (!task.value) return
    task.value.status = 'done'
    task.value.finishedAt = Date.now()
    task.value.totalReturn = result.totalReturn ?? null
    task.value.maxDrawdown = result.maxDrawdown ?? null
    task.value.sharpeRatio = result.sharpeRatio ?? null
    task.value.message = result.message || ''
    // 小卡轮询完成时只带指标、不带明细：保留已有 result，避免覆盖页面存入的完整结果
    task.value.result = result.data ?? task.value.result
    if (task.value.total > 0) task.value.progress = task.value.total
  }

  function fail(message: string) {
    if (!task.value) return
    task.value.status = 'failed'
    task.value.finishedAt = Date.now()
    task.value.message = message
  }

  function dismiss() {
    dismissed.value = true
  }

  function clear() {
    task.value = null
    dismissed.value = false
  }

  return { task, dismissed, start, updateProgress, finish, fail, dismiss, clear }
})
