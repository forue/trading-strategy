import request from './request'

export const schedulerApi = {
  // 获取所有定时任务
  getJobs(): Promise<any[]> {
    return request.get('/scheduler/jobs')
  },

  // 手动触发数据采集
  triggerCollect(): Promise<any> {
    return request.post('/scheduler/trigger/collect')
  },

  // 手动触发策略计算
  triggerStrategy(): Promise<any> {
    return request.post('/scheduler/trigger/strategy')
  },

  // 手动触发全流程（数据采集 + 策略计算）
  triggerAll(): Promise<any> {
    return request.post('/scheduler/trigger/all')
  },

  // 检查调度服务健康状态
  healthCheck(): Promise<any> {
    return request.get('/scheduler/health')
  }
}