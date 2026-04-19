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
  getConfigs(): Promise<StrategyConfig[]> {
    return request.get('/strategy/configs')
  },

  updateConfig(id: number, params: Partial<StrategyConfig>): Promise<StrategyConfig> {
    return request.put(`/strategy/configs/${id}`, params)
  },

  calculateSignals(strategyType: string): Promise<any> {
    return request.post('/strategy/calculate', null, { params: { strategy_type: strategyType } })
  },

  runBacktest(params: {
    strategyType: string
    startDate: string
    endDate: string
    initialCapital: number
    strategyParams?: Record<string, any>
  }): Promise<any> {
    const body: any = {
      strategy_type: params.strategyType,
      start_date: params.startDate,
      end_date: params.endDate,
      initial_capital: params.initialCapital,
    }
    if (params.strategyParams) {
      body.params = params.strategyParams
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

  getDataAvailability(): Promise<{ has_data: boolean; min_date: string; max_date: string }> {
    return request.get('/strategy/data/availability')
  },

  collectHistory(days: number): Promise<any> {
    return request.post('/data/collect/history', null, { params: { days }, timeout: 180000 })
  },
}
