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

export interface DailyPnl {
  date: string
  total_assets: number
  market_value: number
  daily_return: number
  cumulative_return: number
  daily_pnl_amount: number
}

export interface BankTransfer {
  id: number
  transfer_date: string
  direction: string
  amount: number
  remark: string
  created_at: string
}

export interface ProfitCurveData {
  nav_curve: NavRecord[]
  monthly_returns: { month: string; return_pct: number }[]
  stats: {
    total_return_pct: number
    max_drawdown_pct: number
    annual_return_pct: number
    sharpe_ratio: number
    start_date: string
    end_date: string
  }
}

export const fundApi = {
  getPositions(strategyType?: string): Promise<Position[]> {
    return request.get('/fund/positions', { params: { strategyType } })
  },

  getNavCurve(params: { strategyType: string; startDate: string; endDate: string }): Promise<NavRecord[]> {
    return request.get('/fund/nav-curve', {
      params: { strategyType: params.strategyType, startDate: params.startDate, endDate: params.endDate }
    })
  },

  getReturnAttribution(params: { strategyType: string; startDate: string; endDate: string }): Promise<ReturnAttribution[]> {
    return request.get('/fund/attribution', {
      params: { strategyType: params.strategyType, startDate: params.startDate, endDate: params.endDate }
    })
  },

  getAccountSummary(): Promise<{
    total_assets: number; cash: number; market_value: number
    today_pnl: number; cumulative_return: number; net_deposit: number
  }> {
    return request.get('/fund/summary')
  },

  getDailyPnl(month: string): Promise<DailyPnl[]> {
    return request.get('/fund/daily-pnl', { params: { month } })
  },

  getProfitCurve(months: number): Promise<ProfitCurveData> {
    return request.get('/fund/profit-curve', { params: { months } })
  },

  createTransfer(data: { transfer_date: string; direction: string; amount: number; remark?: string }): Promise<any> {
    return request.post('/fund/transfer', data)
  },

  getTransfers(startDate?: string, endDate?: string): Promise<BankTransfer[]> {
    return request.get('/fund/transfers', { params: { startDate, endDate } })
  },

  deleteTransfer(id: number): Promise<any> {
    return request.delete(`/fund/transfer/${id}`)
  },
}
