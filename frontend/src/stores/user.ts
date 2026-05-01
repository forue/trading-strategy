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
      
      // 1. 触发数据采集
      try {
        await schedulerApi.triggerCollect()
        ElMessage.success('数据采集完成')
        
        // 等待2秒，确保数据采集完成
        await new Promise(resolve => setTimeout(resolve, 2000))
      } catch (error) {
        ElMessage.warning('数据采集可能已完成或正在进行中')
      }
      
      // 2. 触发策略计算
      try {
        await schedulerApi.triggerStrategy()
        ElMessage.success('策略计算完成')
      } catch (error) {
        ElMessage.warning('策略计算可能已完成或正在进行中')
      }
      
      // 3. 检查今日是否有信号，如果有则运行回测
      const today = dayjs().format('YYYY-MM-DD')
      try {
        // 获取今日信号
        const signals = await strategyApi.calculateSignals('AGGRESSIVE')
        
        if (signals && signals.length > 0) {
          // 运行回测（使用默认参数）
          const backtestResult = await strategyApi.runBacktest({
            strategyType: 'AGGRESSIVE',
            startDate: today,
            endDate: today,
            initialCapital: 1000000
          })
          
          ElMessage.success(`当日回测完成，总收益: ${backtestResult.total_return?.toFixed(2)}%`)
          
          // 4. 发送通知（这里可以调用通知API）
          // 例如：发送WebSocket消息或调用通知服务
          console.log('回测完成，可以发送通知:', backtestResult)
        } else {
          ElMessage.info('今日无交易信号，跳过回测')
        }
      } catch (error) {
        console.error('回测失败:', error)
        ElMessage.warning('回测失败，可能今日数据尚未准备就绪')
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
