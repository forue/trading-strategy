import { defineStore } from 'pinia'
import { ref } from 'vue'
import { authApi } from '@/api/auth'
import { schedulerApi } from '@/api/scheduler'
import { strategyApi } from '@/api/strategy'
import { useSignalStore } from '@/stores/signal'
import type { UserInfo, LoginParams } from '@/api/auth'
import dayjs from 'dayjs'
import { ElMessage } from 'element-plus'

export const useUserStore = defineStore('user', () => {
  const token = ref<string>(localStorage.getItem('token') || '')
  const userInfo = ref<UserInfo | null>(null)
  const isLoggedIn = ref(!!token.value)

  // 检查是否为交易日
  async function checkIfTradeDay(date: string): Promise<boolean> {
    try {
      // 通过策略服务检查是否为交易日
      const response = await strategyApi.checkTradeDay(date)
      return response.is_trade_day
    } catch (error) {
      console.error('检查交易日失败:', error)
      // 如果API调用失败，使用简单判断（跳过周末）
      const day = dayjs(date).day()
      return day !== 0 && day !== 6 // 不是周六日
    }
  }

  // 检查是否超过自动回测时间点（15:05）
  function isAfterAutoBacktestTime(): boolean {
    const now = dayjs()
    const currentHour = now.hour()
    const currentMinute = now.minute()
    
    // 检查是否超过15:05
    if (currentHour > 15 || (currentHour === 15 && currentMinute >= 5)) {
      return true
    }
    return false
  }

  // 触发当日回测流程
  async function triggerDailyBacktest(): Promise<void> {
    try {
      ElMessage.info('检测到交易日已过回测时间点，正在触发当日回测...')

      // 1. 触发数据采集（内部链式触发策略计算，无需再单独调用 triggerStrategy）
      try {
        const collectResult = await schedulerApi.triggerCollect()
        ElMessage.success('数据采集完成')
        // 采集返回结果中已包含策略计算信号数
        const totalSignals = collectResult?.data?.reduce?.((sum: number, r: any) => sum + (r.signal_count || 0), 0) || 0
        if (totalSignals > 0) {
          ElMessage.success(`策略计算完成，共生成 ${totalSignals} 条信号`)
        } else {
          ElMessage.info('今日无交易信号')
        }
      } catch (error) {
        ElMessage.warning('数据采集可能已完成或正在进行中')
      }
    } catch (error: any) {
      console.error('触发回测流程失败:', error)
      ElMessage.error(`回测流程失败: ${error.message || '未知错误'}`)
    }
  }

  async function login(params: LoginParams) {
    const res = await authApi.login(params)
    token.value = res.token
    userInfo.value = res.user
    isLoggedIn.value = true
    localStorage.setItem('token', res.token)
    
    // 登录后自动连接 WebSocket
    try {
      const signalStore = useSignalStore()
      signalStore.connectWebSocket()
    } catch { /* ignore */ }
    
    // 登录成功后检查是否需要触发回测
    try {
      const today = dayjs().format('YYYY-MM-DD')
      const isTradeDay = await checkIfTradeDay(today)
      
      if (isTradeDay && isAfterAutoBacktestTime()) {
        setTimeout(() => { triggerDailyBacktest() }, 1000)
      }
    } catch (error) {
      console.error('登录后回测检查失败:', error)
    }
  }

  async function checkAuth() {
    try {
      const res = await authApi.getUserInfo()
      userInfo.value = res
      isLoggedIn.value = true
      // 页面刷新后自动重连 WebSocket
      try {
        const signalStore = useSignalStore()
        signalStore.connectWebSocket()
      } catch { /* ignore */ }
    } catch (error: any) {
      const status = error?.response?.status
      if (status === 401 || status === 403) {
        logout()
      }
    }
  }

  function logout() {
    token.value = ''
    userInfo.value = null
    isLoggedIn.value = false
    localStorage.removeItem('token')
    try {
      const signalStore = useSignalStore()
      signalStore.disconnectWebSocket()
    } catch { /* ignore */ }
  }

  return { token, userInfo, isLoggedIn, login, checkAuth, logout }
})
