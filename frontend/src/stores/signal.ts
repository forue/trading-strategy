import { defineStore } from 'pinia'
import { ref } from 'vue'
import { signalApi } from '@/api/signal'
import type { TradeSignal } from '@/api/signal'

export const useSignalStore = defineStore('signal', () => {
  const currentSignals = ref<TradeSignal[]>([])
  const signalHistory = ref<TradeSignal[]>([])
  const wsConnection = ref<WebSocket | null>(null)
  const isConnected = ref(false)
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  // 通知去重：短时间内批量推送只弹一次
  let notifyDebounce: ReturnType<typeof setTimeout> | null = null
  let pendingNotifySignals: TradeSignal[] = []

  async function fetchTodaySignals(strategyType: string) {
    const res = await signalApi.getTodaySignals(strategyType)
    currentSignals.value = res
  }

  async function fetchSignalHistory(params: { strategyType: string; startDate: string; endDate: string }) {
    const res = await signalApi.getSignalHistory(params)
    signalHistory.value = res
  }

  function showNotification(signals: TradeSignal[]) {
    if (signals.length === 0) return
    const audio = new Audio('/notification.mp3')
    audio.play().catch(() => {})
    if (Notification.permission !== 'granted') return
    if (signals.length === 1) {
      const s = signals[0]
      new Notification('轮动信号推送', {
        body: `${s.sector_name} ${s.direction === 'BUY' ? '买入' : '卖出'} 仓位${((s.position_ratio || 0) * 100).toFixed(1)}%`,
      })
    } else {
      const buys = signals.filter(s => s.direction === 'BUY').map(s => s.sector_name)
      const sells = signals.filter(s => s.direction === 'SELL').map(s => s.sector_name)
      const parts: string[] = []
      if (buys.length) parts.push(`买入: ${buys.join('、')}`)
      if (sells.length) parts.push(`卖出: ${sells.join('、')}`)
      new Notification('轮动信号推送', { body: parts.join(' | ') })
    }
  }

  function handleIncomingSignals(signals: TradeSignal[]) {
    // 将批量信号插入列表
    currentSignals.value = [...signals.reverse(), ...currentSignals.value]
    // 去抖合并：500ms 内的多批推送合并为一条通知
    pendingNotifySignals.push(...signals)
    if (notifyDebounce) clearTimeout(notifyDebounce)
    notifyDebounce = setTimeout(() => {
      showNotification([...pendingNotifySignals])
      pendingNotifySignals = []
      notifyDebounce = null
    }, 500)
  }

  function connectWebSocket() {
    if (wsConnection.value && wsConnection.value.readyState === WebSocket.OPEN) return
    if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null }

    const token = localStorage.getItem('token')
    if (!token) return

    const wsUrl = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws/signals?token=${token}`
    const ws = new WebSocket(wsUrl)

    ws.onopen = () => {
      isConnected.value = true
      console.log('WebSocket connected')
    }

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        if (msg.type === 'pong' || msg.type === 'subscribed' || msg.type === 'unsubscribed') return
        // 批量格式: { type: "signals", signals: [...], strategy_type: "..." }
        if (msg.type === 'signals' && Array.isArray(msg.signals)) {
          handleIncomingSignals(msg.signals as TradeSignal[])
        } else {
          // 兼容旧格式：单条信号
          handleIncomingSignals([msg as TradeSignal])
        }
      } catch { /* ignore non-JSON messages */ }
    }

    ws.onclose = () => {
      isConnected.value = false
      wsConnection.value = null
      reconnectTimer = setTimeout(() => connectWebSocket(), 5000)
    }

    ws.onerror = () => {
      ws.close()
    }

    wsConnection.value = ws
  }

  function disconnectWebSocket() {
    if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null }
    if (notifyDebounce) { clearTimeout(notifyDebounce); notifyDebounce = null }
    if (wsConnection.value) {
      wsConnection.value.close()
      wsConnection.value = null
    }
  }

  function clearSignals() {
    currentSignals.value = []
  }

  return {
    currentSignals, signalHistory, isConnected,
    fetchTodaySignals, fetchSignalHistory, connectWebSocket, disconnectWebSocket, clearSignals,
  }
})
