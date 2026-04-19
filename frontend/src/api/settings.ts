import request from './request'

export interface NotifyChannelDingTalk {
  enabled: boolean
  webhook_url: string
  secret: string
  webhook_url_display?: string
}

export interface NotifyChannelWeCom {
  enabled: boolean
  webhook_url: string
  webhook_url_display?: string
}

export interface NotifyConfig {
  dingtalk: NotifyChannelDingTalk
  wecom: NotifyChannelWeCom
}

export interface CacheStats {
  total_keys: number
  used_memory_human: string
  peak_memory_human: string
  categories: Record<string, number>
  db_index: number
}

export interface DatabaseStatus {
  postgresql: { status: string }
  influxdb: {
    status: string
    url: string
    org: string
    bucket: string
    data_counts: Record<string, any>
  }
  redis: {
    status: string
    version: string
    used_memory: string
    connected_clients: number
    uptime_days: number
  }
}

export interface SystemSettings {
  ws_push_enabled: boolean
  ws_push_strategy_types: string[]
  data_source: string
  data_source_config: {
    name: string
    is_mock: boolean
    description: string
  }
  cache_ttl_days: number
  scheduler_enabled: boolean
  scheduler_times: {
    collect: string
    calculate: string
    north_bound: string
  }
}

export const settingsApi = {
  getCacheStats(): Promise<CacheStats> {
    return request.get('/strategy/cache/stats')
  },

  clearAllCache(): Promise<any> {
    return request.delete('/strategy/cache/clear')
  },

  clearExpiredCache(): Promise<any> {
    return request.delete('/strategy/cache/expired')
  },

  getDatabaseStatus(): Promise<DatabaseStatus> {
    return request.get('/strategy/database/status')
  },

  getSystemSettings(): Promise<SystemSettings> {
    return request.get('/strategy/settings')
  },

  updateSystemSettings(settings: Partial<SystemSettings>): Promise<any> {
    return request.put('/strategy/settings', settings)
  },

  getReplayDates(startDate?: string, endDate?: string): Promise<string[]> {
    const params: any = {}
    if (startDate) params.start_date = startDate
    if (endDate) params.end_date = endDate
    return request.get('/strategy/data/replay/dates', { params })
  },

  getReplaySectors(): Promise<{ sector_code: string; sector_name: string }[]> {
    return request.get('/strategy/data/replay/sectors')
  },

  getReplayDayData(date: string, sectorCode?: string): Promise<{
    date: string
    sectors: any[]
    count: number
  }> {
    const params: any = {}
    if (sectorCode) params.sector_code = sectorCode
    return request.get(`/strategy/data/replay/day/${date}`, { params })
  },

  getReplaySectorHistory(sectorCode: string, startDate?: string, endDate?: string): Promise<any[]> {
    const params: any = {}
    if (startDate) params.start_date = startDate
    if (endDate) params.end_date = endDate
    return request.get(`/strategy/data/replay/sector/${sectorCode}`, { params })
  },

  // ==================== 推送通道配置 ====================

  getNotifyConfig(): Promise<NotifyConfig> {
    return request.get('/signals/notify/config')
  },

  updateNotifyConfig(config: NotifyConfig): Promise<any> {
    return request.put('/signals/notify/config', config)
  },

  testNotifyChannel(channel: 'dingtalk' | 'wecom', strategyType?: string): Promise<any> {
    return request.post(`/signals/notify/test/${channel}`, null, {
      params: strategyType ? { strategy_type: strategyType } : {},
      timeout: 15000,
    })
  },

  runStrategyOverlay(data: {
    start_date: string
    end_date: string
    strategy_type: string
    initial_capital?: number
    params?: any
  }): Promise<{
    daily_signals: any[]
    nav_curve: any[]
    summary: {
      total_return: number
      annual_return: number
      max_drawdown: number
      trade_count: number
      buy_count: number
      sell_count: number
      trading_days: number
      strategy_type: string
      initial_capital: number
      final_capital: number
    }
  }> {
    return request.post('/strategy/data/replay/strategy-overlay', data)
  },
}
