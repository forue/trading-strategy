import request from './request'

export interface StrategyConfig {
  id: number
  strategy_type: 'AGGRESSIVE' | 'MODERATE' | 'CONSERVATIVE'
  name: string
  params: {
    top_n?: number
    max_position?: number
    hold_days?: number
    capital_pct?: number
    stop_loss?: number
    valuation_pct_max?: number
    commission_rate?: number
    stamp_tax_rate?: number
    slippage_rate?: number
  }
  is_active: boolean
}

export interface BacktestHistoryItem {
  id: string
  strategy_type: string
  start_date: string
  end_date: string
  initial_capital: number
  total_return: number
  annual_return: number
  max_drawdown: number
  sharpe_ratio: number
  params: Record<string, any>
  created_at: string
}

export const strategyApi = {
  checkTradeDay(date: string): Promise<{ date: string; is_trade_day: boolean }> {
    return request.get('/strategy/trade-day/check', { params: { date } })
  },

  calculateSignals(strategyType: string, signalDate?: string): Promise<any[]> {
    return request.post('/strategy/calculate', null, {
      params: { strategy_type: strategyType, signal_date: signalDate },
    })
  },

  getDataAvailability(): Promise<{ has_data: boolean; min_date: string; max_date: string }> {
    return request.get('/strategy/data/availability')
  },

  collectHistory(days: number): Promise<any> {
    return request.post('/strategy/data/collect/history', null, { params: { days }, timeout: 180000 })
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

  analyzeFactors(data: {
    sector_code: string
    strategy_type?: string
    date?: string
  }): Promise<any> {
    return request.post('/strategy/factors/analyze', data)
  },

  runBacktest(data: {
    strategyType: string
    startDate: string
    endDate: string
    initialCapital: number
    strategyParams?: Record<string, any>
  }): Promise<any> {
    const body: any = {
      strategy_type: data.strategyType,
      start_date: data.startDate,
      end_date: data.endDate,
      initial_capital: data.initialCapital,
    }
    if (data.strategyParams) {
      body.params = data.strategyParams
    }
    return request.post('/strategy/backtest', body)
  },

  getBacktestHistory(strategyType?: string): Promise<BacktestHistoryItem[]> {
    const params: any = {}
    if (strategyType) params.strategy_type = strategyType
    return request.get('/strategy/backtest/history', { params })
  },

  getBacktestDetail(btId: string): Promise<any> {
    return request.get(`/strategy/backtest/${btId}`)
  },

  getConfigs(): Promise<StrategyConfig[]> {
    return request.get('/strategy/configs')
  },

  updateConfig(configId: number, config: Partial<StrategyConfig>): Promise<any> {
    return request.put(`/strategy/configs/${configId}`, config)
  },
}
