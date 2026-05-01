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

  async function fetchTodaySignals(strategyType: string) {
    const res = await signalApi.getTodaySignals(strategyType)
    currentSignals.value = res
  }

  async function fetchSignalHistory(params: { strategyType: string; startDate: string; endDate: string }) {
    const res = await signalApi.getSignalHistory(params)
    signalHistory.value = res
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
        if (msg.type === 'pong') return
        const signal: TradeSignal = msg
        currentSignals.value.unshift(signal)
        const audio = new Audio('/notification.mp3')
        audio.play().catch(() => {})
        if (Notification.permission === 'granted') {
          new Notification('轮动信号推送', {
            body: `${signal.sector_name} ${signal.direction === 'BUY' ? '买入' : '卖出'} 仓位${((signal.position_ratio || 0) * 100).toFixed(1)}%`,
          })
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
    if (wsConnection.value) {
      wsConnection.value.close()
      wsConnection.value = null
    }
  }

  return {
    currentSignals, signalHistory, isConnected,
    fetchTodaySignals, fetchSignalHistory, connectWebSocket, disconnectWebSocket,
  }
})
