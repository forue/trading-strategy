import request from './request'

export interface Position {
  id: number
  strategy_type: string
  sector_code: string
  sector_name: string
  direction: string
  quantity: number
  avg_price: number
  current_price: number
  position_ratio: number
  opened_at: string
}

export interface NavRecord {
  nav_date: string
  total_assets: number
  cash: number
  market_value: number
  daily_return: number
  cumulative_return: number
}

export interface ReturnAttribution {
  sector_name: string
  contribution: number
  percentage: number
}

export const fundApi = {
  getPositions(strategyType?: string): Promise<Position[]> {
    return request.get('/fund/positions', { params: { strategyType } })
  },

  getNavCurve(params: { strategyType: string; startDate: string; endDate: string }): Promise<NavRecord[]> {
    return request.get('/fund/nav-curve', {
      params: {
        strategyType: params.strategyType,
        startDate: params.startDate,
        endDate: params.endDate,
      }
    })
  },

  getReturnAttribution(params: { strategyType: string; startDate: string; endDate: string }): Promise<ReturnAttribution[]> {
    return request.get('/fund/attribution', {
      params: {
        strategyType: params.strategyType,
        startDate: params.startDate,
        endDate: params.endDate,
      }
    })
  },

  getAccountSummary(): Promise<{
    total_assets: number
    cash: number
    market_value: number
    today_pnl: number
    cumulative_return: number
  }> {
    return request.get('/fund/summary')
  },
}
