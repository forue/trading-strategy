import { defineStore } from 'pinia'
import { ref } from 'vue'
import { signalApi } from '@/api/signal'
import type { TradeSignal } from '@/api/signal'

export const useSignalStore = defineStore('signal', () => {
  const currentSignals = ref<TradeSignal[]>([])
  const signalHistory = ref<TradeSignal[]>([])
  const wsConnection = ref<WebSocket | null>(null)
  const isConnected = ref(false)

  async function fetchTodaySignals(strategyType: string) {
    const res = await signalApi.getTodaySignals(strategyType)
    currentSignals.value = res
  }

  async function fetchSignalHistory(params: { strategyType: string; startDate: string; endDate: string }) {
    const res = await signalApi.getSignalHistory(params)
    signalHistory.value = res
  }

  function connectWebSocket() {
    const token = localStorage.getItem('token')
    if (!token) return

    const wsUrl = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws/signals?token=${token}`
    const ws = new WebSocket(wsUrl)

    ws.onopen = () => {
      isConnected.value = true
      console.log('WebSocket 连接已建立')
    }

    ws.onmessage = (event) => {
      const signal: TradeSignal = JSON.parse(event.data)
      currentSignals.value.unshift(signal)
      // 播放提示音
      const audio = new Audio('/notification.mp3')
      audio.play().catch(() => {})
      // 浏览器通知
      if (Notification.permission === 'granted') {
        new Notification('轮动信号推送', {
          body: `${signal.sector_name} ${signal.direction} 仓位${(signal.position_ratio * 100).toFixed(1)}%`,
        })
      }
    }

    ws.onclose = () => {
      isConnected.value = false
      // 5秒后重连
      setTimeout(() => connectWebSocket(), 5000)
    }

    ws.onerror = () => {
      ws.close()
    }

    wsConnection.value = ws
  }

  function disconnectWebSocket() {
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
