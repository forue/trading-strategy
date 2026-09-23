import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'

export type StrategyType = 'AGGRESSIVE' | 'MODERATE' | 'CONSERVATIVE'

export const STRATEGY_OPTIONS: { label: string; value: StrategyType }[] = [
  { label: '激进轮动', value: 'AGGRESSIVE' },
  { label: '稳健轮动', value: 'MODERATE' },
  { label: '保守轮动', value: 'CONSERVATIVE' },
]

export const STRATEGY_LABELS: Record<string, string> = {
  AGGRESSIVE: '激进轮动',
  MODERATE: '稳健轮动',
  CONSERVATIVE: '保守轮动',
}

const STORAGE_KEY = 'global-strategy'

function loadStrategy(): StrategyType {
  const saved = localStorage.getItem(STORAGE_KEY)
  if (saved === 'AGGRESSIVE' || saved === 'MODERATE' || saved === 'CONSERVATIVE') {
    return saved
  }
  return 'MODERATE'
}

/**
 * 全局策略状态：仪表盘头部与各页面共用同一个选中策略，
 * 任意一处切换都会驱动其余页面的数据按该策略刷新。
 */
export const useStrategyStore = defineStore('strategy', () => {
  const currentStrategy = ref<StrategyType>(loadStrategy())

  const strategyLabel = computed(
    () => STRATEGY_OPTIONS.find(o => o.value === currentStrategy.value)?.label || currentStrategy.value,
  )

  function setStrategy(value: StrategyType) {
    currentStrategy.value = value
  }

  watch(currentStrategy, (value) => {
    localStorage.setItem(STORAGE_KEY, value)
  })

  return { currentStrategy, strategyLabel, setStrategy }
})
